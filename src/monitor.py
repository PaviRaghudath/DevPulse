"""
MonitorScheduler — background APScheduler that runs per-project log checks
on configurable intervals. Designed as a Streamlit @st.cache_resource singleton.

Each project gets its own job. Jobs persist across Streamlit reruns because the
scheduler runs in a daemon thread. Results are written to ProjectStore (JSON) so
the UI can read them without thread-safety concerns.
"""
import logging
from typing import Optional

log = logging.getLogger(__name__)


class MonitorScheduler:
    """Singleton APScheduler wrapper. Instantiate once via @st.cache_resource."""

    def __init__(self):
        self._scheduler = None
        self._job_map: dict[str, str] = {}   # project_id → APScheduler job_id

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the background scheduler. Returns True if running."""
        if self.is_running:
            return True
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler(
                job_defaults={"misfire_grace_time": 60, "coalesce": True},
                timezone="UTC",
            )
            self._scheduler.start()
            log.info("[Monitor] Background scheduler started.")
            return True
        except ImportError:
            log.warning("[Monitor] apscheduler not installed — scheduled checks unavailable.")
            return False
        except Exception as e:
            log.error(f"[Monitor] Scheduler start failed: {e}")
            return False

    def stop(self) -> None:
        if self.is_running:
            self._scheduler.shutdown(wait=False)
            log.info("[Monitor] Scheduler stopped.")

    @property
    def is_running(self) -> bool:
        return bool(self._scheduler and self._scheduler.running)

    # ── Project sync ───────────────────────────────────────────────────────

    def sync_projects(self, projects: list) -> None:
        """
        Reconcile the scheduler job list with the current project list.
        Call this whenever projects are added, edited, or deleted.
        """
        if not self.start():
            return

        active_ids = {p.id for p in projects}

        # Remove jobs for deleted/disabled projects
        for pid in list(self._job_map):
            if pid not in active_ids:
                self._remove_job(pid)

        # Add/reschedule jobs for enabled projects
        for project in projects:
            if project.enabled:
                self._upsert_job(project)
            else:
                self._remove_job(project.id)

    def _upsert_job(self, project) -> None:
        job_id = f"mon_{project.id}"
        kwargs = {"minutes": max(1, project.check_interval_min)}

        if project.id in self._job_map:
            try:
                self._scheduler.reschedule_job(job_id, trigger="interval", **kwargs)
                return
            except Exception:
                pass   # job may have been removed externally

        self._scheduler.add_job(
            _scheduled_check,
            trigger="interval",
            kwargs={"project_id": project.id},
            id=job_id,
            replace_existing=True,
            **kwargs,
        )
        self._job_map[project.id] = job_id
        log.info(f"[Monitor] Scheduled '{project.name}' every {project.check_interval_min} min.")

    def _remove_job(self, project_id: str) -> None:
        job_id = self._job_map.pop(project_id, f"mon_{project_id}")
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

    # ── Manual trigger ─────────────────────────────────────────────────────

    def run_now(self, project_id: str) -> dict:
        """
        Immediately run a check for one project (called from the UI).
        Returns a summary dict: {"project", "alerts": [...], "errors": [...]}.
        """
        from src.project_config import ProjectStore
        from src.log_fetcher import LogFetcher
        from src.alert_engine import AlertEngine

        store   = ProjectStore()
        project = store.get_project(project_id)
        if not project:
            return {"error": f"Project '{project_id}' not found."}

        return run_check(project, store, LogFetcher(), AlertEngine())

    # ── Status ─────────────────────────────────────────────────────────────

    def job_count(self) -> int:
        return len(self._job_map)

    def next_run_times(self) -> dict[str, Optional[str]]:
        """project_id → next run ISO timestamp (or None)."""
        result: dict[str, Optional[str]] = {}
        if not self.is_running:
            return result
        for pid, jid in self._job_map.items():
            try:
                job = self._scheduler.get_job(jid)
                nf  = job.next_fire_time
                result[pid] = nf.isoformat() if nf else None
            except Exception:
                result[pid] = None
        return result


# ── Top-level check function (called by APScheduler and run_now) ────────────

def _scheduled_check(project_id: str) -> None:
    """Entry point for APScheduler jobs — loads its own dependencies."""
    from src.project_config import ProjectStore
    from src.log_fetcher import LogFetcher
    from src.alert_engine import AlertEngine
    store   = ProjectStore()
    project = store.get_project(project_id)
    if project and project.enabled:
        run_check(project, store, LogFetcher(), AlertEngine())


def run_check(project, store, fetcher, engine) -> dict:
    """
    Core check pipeline: fetch new log content → analyze → alert if needed.
    Writes AlertRecords to ProjectStore. Returns a summary dict for the UI.
    """
    summary = {"project": project.name, "alerts": [], "errors": [], "no_new_content": []}
    email_cfg = store.load_email_config()

    fetch_results = fetcher.fetch_new_logs(project, store)

    for fr in fetch_results:
        if fr.error:
            summary["errors"].append({"log": fr.log_path, "msg": fr.error})
            continue

        if not fr.content.strip():
            summary["no_new_content"].append(fr.log_path)
            continue

        alert = engine.analyze_content(project, fr.log_path, fr.content)
        if alert is None:
            continue

        # Send email
        if project.notify_emails:
            engine.send_alert_email(alert, email_cfg, project.notify_emails)

        store.save_alert(alert)
        summary["alerts"].append({
            "log":    fr.log_path,
            "errors": alert.error_count,
            "warns":  alert.warn_count,
            "id":     alert.id,
        })
        log.info(
            f"[Monitor] Alert recorded — {project.name}/{fr.log_path}: "
            f"{alert.error_count} errors, {alert.warn_count} warnings"
        )

    return summary
