"""
Deployer — two deployment paths depending on what's detected in the repo:

PATH A — CI/CD pipeline exists:
  GitHub Actions → POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches
  Jenkins        → POST /job/{job}/build  (with optional Basic auth)
  GitLab CI      → POST /projects/{id}/pipeline
  Returns a job URL for the user to track. No SSH needed.

PATH B — No CI/CD (or manual override):
  1. SSH into the target server
  2. git clone (first time) OR git pull (subsequent)
  3. Run build_command on the server  (mvn / gradlew / npm)
  4. Deploy the artifact:
       JAR  → restart systemd service  (project.restart_cmd)
       WAR  → copy to Tomcat webapps/ → restart Tomcat
       SPA  → rsync dist/ or build/ to web root → reload nginx/apache
  Streams output line-by-line via on_log callback so the UI can show live progress.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class DeployResult:
    success: bool
    method: str        # "github_actions" | "jenkins" | "gitlab_ci" | "ssh_build"
    message: str
    job_url: str = ""  # CI/CD pipeline URL (for Path A)
    output: str  = ""  # SSH command output  (for Path B)


class Deployer:

    def deploy(self, project, on_log=None) -> DeployResult:
        """
        Select and run the correct deployment path.
        on_log: optional callable(str) for live SSH output in the UI.
        """
        ct = project.cicd_type
        if ct == "github_actions":
            return self._github_actions(project)
        if ct == "jenkins":
            return self._jenkins(project)
        if ct == "gitlab_ci":
            return self._gitlab(project)
        return self._ssh_deploy(project, on_log)

    # ── PATH A — CI/CD triggers ────────────────────────────────────────────

    def _github_actions(self, project) -> DeployResult:
        from src.git_connector import GitConnector
        _, owner, repo = GitConnector().parse_url(project.git_url)

        # Resolve workflow id
        workflow_id = project.cicd_workflow
        wf_name     = workflow_id
        if not workflow_id:
            wfs = GitConnector().get_workflows(project.git_url, project.git_token)
            if not wfs:
                return DeployResult(False, "github_actions",
                                    "No workflows found in repo. Push a workflow file first.")
            # Prefer a workflow with 'deploy' in the name, else pick first
            deploy_wf = next((w for w in wfs if "deploy" in w["name"].lower()), wfs[0])
            workflow_id = deploy_wf["id"]
            wf_name     = deploy_wf["name"]

        url  = (f"https://api.github.com/repos/{owner}/{repo}"
                f"/actions/workflows/{workflow_id}/dispatches")
        body = json.dumps({"ref": project.git_branch or "main"}).encode()
        hdrs = {
            "Authorization": f"token {project.git_token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json",
            "User-Agent":    "FileAnalyzer",
        }
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=15):
                pass
            return DeployResult(
                success=True, method="github_actions",
                message=f"Workflow '{wf_name}' triggered on branch '{project.git_branch}'.",
                job_url=f"https://github.com/{owner}/{repo}/actions",
            )
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            return DeployResult(False, "github_actions", f"HTTP {e.code}: {err[:300]}")
        except Exception as e:
            return DeployResult(False, "github_actions", str(e))

    def _jenkins(self, project) -> DeployResult:
        base = (project.cicd_url or "").rstrip("/")
        if not base:
            return DeployResult(False, "jenkins",
                                "Jenkins URL not set. Add it in the project CI/CD settings.")
        job  = project.cicd_workflow or project.name.replace(" ", "_")
        url  = f"{base}/job/{urllib.parse.quote(job, safe='')}/build"
        hdrs = {"User-Agent": "FileAnalyzer"}
        if project.cicd_token:
            import base64 as b64mod
            creds = b64mod.b64encode(f"admin:{project.cicd_token}".encode()).decode()
            hdrs["Authorization"] = f"Basic {creds}"
        try:
            req = urllib.request.Request(url, data=b"", headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=15):
                pass
            return DeployResult(
                success=True, method="jenkins",
                message=f"Jenkins job '{job}' triggered.",
                job_url=f"{base}/job/{urllib.parse.quote(job, safe='')}/",
            )
        except urllib.error.HTTPError as e:
            return DeployResult(False, "jenkins", f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            return DeployResult(False, "jenkins", str(e))

    def _gitlab(self, project) -> DeployResult:
        from src.git_connector import GitConnector
        _, owner, repo = GitConnector().parse_url(project.git_url)
        proj_path = urllib.parse.quote(f"{owner}/{repo}", safe="")
        token     = project.cicd_token or project.git_token
        url       = f"https://gitlab.com/api/v4/projects/{proj_path}/pipeline"
        body      = json.dumps({"ref": project.git_branch or "main"}).encode()
        hdrs      = {
            "PRIVATE-TOKEN": token,
            "Content-Type":  "application/json",
            "User-Agent":    "FileAnalyzer",
        }
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            return DeployResult(
                success=True, method="gitlab_ci",
                message=f"GitLab pipeline #{data.get('id')} triggered on '{project.git_branch}'.",
                job_url=data.get("web_url", ""),
            )
        except urllib.error.HTTPError as e:
            return DeployResult(False, "gitlab_ci", f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            return DeployResult(False, "gitlab_ci", str(e))

    # ── PATH B — SSH: git pull → build → restart ───────────────────────────

    def _ssh_deploy(self, project, on_log) -> DeployResult:
        lines = []

        def emit(line: str):
            lines.append(line)
            log.info(f"[Deploy] {line}")
            if on_log:
                on_log(line)

        if not project.deploy_path:
            return DeployResult(False, "ssh_build",
                                "deploy_path not set — enter the directory where the repo lives on the server.")
        if not project.git_url:
            return DeployResult(False, "ssh_build", "git_url not set.")
        if not project.build_command:
            return DeployResult(False, "ssh_build",
                                "build_command not set — click Detect Project first.")

        ssh = None
        try:
            import paramiko
        except ImportError:
            return DeployResult(False, "ssh_build",
                                "paramiko not installed. Run: pip install paramiko")

        try:
            ssh = _ssh_connect(project)
            emit(f"✅ Connected to {project.host}")

            git_url = _auth_url(project.git_url, project.git_token, project.git_username)
            branch  = project.git_branch or "main"
            path    = project.deploy_path

            # ── Clone or pull ──────────────────────────────────────────────
            _, out = _run(ssh, f"[ -d '{path}/.git' ] && echo YES || echo NO")
            if out.strip() == "NO":
                emit(f"📥 Cloning {project.git_url} → {path} …")
                ok, out = _run(ssh,
                               f"git clone --branch {branch} --depth 50 {git_url} {path} 2>&1",
                               timeout=120)
            else:
                emit(f"🔄 Pulling latest {branch} …")
                ok, out = _run(ssh,
                               f"cd {path} && git fetch origin {branch} && "
                               f"git checkout {branch} && git reset --hard origin/{branch} 2>&1",
                               timeout=60)

            emit(out.strip() or "(no git output)")
            if not ok:
                return _fail("ssh_build", f"Git step failed.", lines)

            # ── Build ──────────────────────────────────────────────────────
            emit(f"🔨 Building: {project.build_command} …")
            ok, out = _run(ssh, f"cd {path} && {project.build_command} 2>&1", timeout=600)
            # Show last 4 KB of build output (avoid flooding the UI)
            tail = out[-4000:] if len(out) > 4000 else out
            emit(tail.strip() or "(no build output)")
            if not ok:
                return _fail("ssh_build", "Build failed. Check output above.", lines)

            emit("✅ Build successful.")

            # ── Deploy artifact ────────────────────────────────────────────
            ptype = project.project_type

            if ptype in ("spring_boot_jar", "maven_jar", "gradle_jar"):
                emit("🚀 Deploying JAR …")
                if project.restart_cmd:
                    ok, out = _run(ssh, f"cd {path} && {project.restart_cmd} 2>&1", timeout=60)
                    emit(out.strip() or "(service restarted)")
                else:
                    emit("⚠️  No restart_cmd — service not restarted. Set it in project settings.")

            elif ptype in ("spring_boot_war", "jsp_war"):
                emit("🚀 Deploying WAR to Tomcat …")
                ok, out = _run(ssh, f"cd {path} && cp target/*.war {project.artifact_dest or '/opt/tomcat/webapps/'} 2>&1")
                emit(out.strip() or "(WAR copied)")
                if project.restart_cmd:
                    ok, out = _run(ssh, project.restart_cmd + " 2>&1", timeout=60)
                    emit(out.strip())

            elif ptype in ("react", "angular", "vue"):
                dist     = {"react": "build", "angular": "dist", "vue": "dist"}.get(ptype, "dist")
                web_root = project.artifact_dest or "/var/www/html"
                emit(f"🚀 Copying {dist}/ → {web_root} …")
                ok, out  = _run(ssh,
                                f"sudo rsync -a --delete {path}/{dist}/ {web_root}/ 2>&1",
                                timeout=60)
                emit(out.strip() or "(files synced)")
                if project.restart_cmd:
                    ok, out = _run(ssh, project.restart_cmd + " 2>&1", timeout=30)
                    emit(out.strip())

            elif ptype == "nextjs":
                emit("🚀 Restarting Next.js server …")
                if project.restart_cmd:
                    ok, out = _run(ssh, project.restart_cmd + " 2>&1", timeout=60)
                    emit(out.strip())
                else:
                    emit("⚠️  Set restart_cmd (e.g. 'pm2 restart next-app') to restart the server.")

            elif project.restart_cmd:
                ok, out = _run(ssh, project.restart_cmd + " 2>&1", timeout=60)
                emit(out.strip())

            emit("🎉 Deploy complete!")
            return DeployResult(
                success=True, method="ssh_build",
                message="Build and deploy completed successfully.",
                output="\n".join(lines),
            )

        except Exception as e:
            emit(f"❌ {e}")
            return _fail("ssh_build", str(e), lines)
        finally:
            if ssh:
                try: ssh.close()
                except: pass


# ── SSH helpers ────────────────────────────────────────────────────────────

def _ssh_connect(project):
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {"hostname": project.host, "port": project.port,
          "username": project.username, "timeout": 30, "banner_timeout": 30}
    if project.auth_method == "key":
        kw["key_filename"] = project.ssh_key_path
    else:
        kw["password"] = project.ssh_password
    ssh.connect(**kw)
    return ssh


def _run(ssh, cmd: str, timeout: int = 120) -> tuple[bool, str]:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out  = stdout.read().decode("utf-8", errors="replace")
    err  = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code == 0, (out + err).strip()


def _auth_url(url: str, token: str, username: str = "") -> str:
    """Embed a PAT into an HTTPS git URL for passwordless clone/pull."""
    if token and url.startswith("https://"):
        user = username or "oauth2"
        return url.replace("https://", f"https://{user}:{token}@", 1)
    return url


def _fail(method: str, msg: str, lines: list) -> DeployResult:
    return DeployResult(False, method, msg, output="\n".join(lines))
