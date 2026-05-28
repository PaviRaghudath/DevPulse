"""
LogFetcher — connects to remote AWS EC2 servers via SSH/SFTP (paramiko) and
fetches only new log content since the last read (incremental byte-offset tracking).

Supports:
  - PEM key auth (ec2-user + .pem file)
  - Password auth
  - Log rotation detection (file shrinks → reset position)
  - 2 MB cap per fetch to keep memory bounded
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

MAX_FETCH_BYTES = 2 * 1024 * 1024   # 2 MB per file per fetch


@dataclass
class FetchResult:
    log_path: str
    content: str
    bytes_read: int
    new_position: int
    error: str = ""


class LogFetcher:
    """
    Fetches new content from remote log files via SFTP.
    Positions are persisted by ProjectStore so only fresh bytes are read each run.
    """

    def test_connection(self, project) -> tuple[bool, str]:
        """
        Verify SSH connectivity. Returns (ok, error_message).
        Safe to call from the UI — never raises.
        """
        try:
            ssh = self._connect(project)
            ssh.close()
            return True, ""
        except Exception as e:
            return False, str(e)

    def fetch_new_logs(self, project, store) -> list[FetchResult]:
        """
        Fetch new content from every log_path configured on the project.
        Returns one FetchResult per path (content="" if nothing new).
        """
        results: list[FetchResult] = []
        ssh = sftp = None

        try:
            ssh  = self._connect(project)
            sftp = ssh.open_sftp()
            for path in project.log_paths:
                result = self._fetch_one(sftp, project, path, store)
                if result.error:
                    log.warning(f"[LogFetcher] {project.name}/{path}: {result.error}")
                elif result.bytes_read:
                    log.info(f"[LogFetcher] {project.name}/{path}: {result.bytes_read:,} bytes read")
                results.append(result)

        except Exception as e:
            log.error(f"[LogFetcher] SSH failed for '{project.name}': {e}")
            for p in project.log_paths:
                results.append(FetchResult(p, "", 0, 0, error=str(e)))
        finally:
            _close(sftp)
            _close(ssh)

        return results

    # ── Internal ───────────────────────────────────────────────────────────

    def _fetch_one(self, sftp, project, log_path: str, store) -> FetchResult:
        try:
            file_size = sftp.stat(log_path).st_size
            last_pos  = store.get_log_position(project.id, log_path)

            # No new content
            if file_size == last_pos:
                return FetchResult(log_path, "", 0, last_pos)

            # Log rotation: file is smaller than our saved position
            if file_size < last_pos:
                log.info(f"[LogFetcher] Rotation detected for {log_path} — resetting.")
                last_pos = max(0, file_size - MAX_FETCH_BYTES)

            # On very first fetch: only read the tail so we don't flood on large existing logs
            if last_pos == 0:
                last_pos = max(0, file_size - MAX_FETCH_BYTES)

            # Cap how many bytes we pull in one pass
            read_from    = max(last_pos, file_size - MAX_FETCH_BYTES)
            bytes_to_read = file_size - read_from

            with sftp.open(log_path, "rb") as f:
                f.seek(read_from)
                raw = f.read(bytes_to_read)

            content = raw.decode("utf-8", errors="replace")
            store.save_log_position(project.id, log_path, file_size)

            return FetchResult(log_path, content, bytes_to_read, file_size)

        except Exception as e:
            return FetchResult(log_path, "", 0, 0, error=str(e))

    def _connect(self, project):
        try:
            import paramiko
        except ImportError:
            raise ImportError(
                "paramiko is not installed. Run: pip install paramiko"
            )

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs: dict = {
            "hostname": project.host,
            "port":     project.port,
            "username": project.username,
            "timeout":  15,
            "banner_timeout": 15,
        }

        if project.auth_method == "key":
            if not project.ssh_key_path:
                raise ValueError(
                    f"Project '{project.name}': ssh_key_path is empty. "
                    "Set the path to your .pem file."
                )
            kwargs["key_filename"] = project.ssh_key_path
        elif project.auth_method == "password":
            if not project.ssh_password:
                raise ValueError(f"Project '{project.name}': ssh_password is empty.")
            kwargs["password"] = project.ssh_password
        else:
            raise ValueError(f"Unknown auth_method '{project.auth_method}'.")

        ssh.connect(**kwargs)
        return ssh


def _close(obj) -> None:
    if obj:
        try:
            obj.close()
        except Exception:
            pass
