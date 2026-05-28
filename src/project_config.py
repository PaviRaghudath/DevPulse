"""
Project configuration management for the FileAnalyzer monitoring hook.

Stores project configs, email settings, alert history, and log-read positions
in JSON files under data/. No database required.

Files:
    data/projects.json       — project configs + email settings
    data/alert_history.json  — alert records (last 500)
    data/log_positions.json  — byte offsets for incremental log reads
"""
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR           = Path(__file__).parent.parent / "data"
PROJECTS_FILE      = DATA_DIR / "projects.json"
ALERT_HISTORY_FILE = DATA_DIR / "alert_history.json"
LOG_POSITIONS_FILE = DATA_DIR / "log_positions.json"


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class ProjectConfig:
    """A monitored Java Spring Boot / Apache project on a remote server."""
    name: str
    host: str
    username: str
    log_paths: list[str]                          # e.g. ["/var/log/app/app.log"]

    id: str               = field(default_factory=lambda: str(uuid.uuid4())[:8])
    port: int             = 22
    auth_method: str      = "key"                 # "key" | "password"
    ssh_key_path: str     = ""                    # absolute path to .pem file
    ssh_password: str     = ""
    app_type: str         = "spring_boot"         # legacy field — kept for backwards compat
    deploy_path: str      = ""                    # repo root on server, e.g. /opt/payment-service
    artifact_dest: str    = ""                    # override artifact destination (WAR→webapps, SPA→web root)
    restart_cmd: str      = ""                    # e.g. "sudo systemctl restart myapp"
    check_interval_min: int = 15
    error_threshold: int  = 0                     # 0 = any error triggers alert
    notify_emails: list[str] = field(default_factory=list)
    enabled: bool         = True
    created_at: str       = field(default_factory=lambda: datetime.utcnow().isoformat())

    # ── Git integration ─────────────────────────────────────────────────────
    git_url: str          = ""                    # https://github.com/org/repo.git
    git_branch: str       = "main"
    git_token: str        = ""                    # GitHub PAT / GitLab token
    git_username: str     = ""                    # git username for HTTPS auth (optional)

    # ── Auto-detected project type (populated by GitConnector) ─────────────
    project_type: str     = ""                    # spring_boot_jar | spring_boot_war | react | angular | ...
    build_tool: str       = ""                    # maven | gradle | npm | yarn
    build_command: str    = ""                    # e.g. "mvn clean package -DskipTests"
    artifact_path: str    = ""                    # e.g. "target/*.jar"

    # ── CI/CD pipeline (auto-detected or manual) ────────────────────────────
    cicd_type: str        = ""                    # github_actions | jenkins | gitlab_ci | circleci | none
    cicd_workflow: str    = ""                    # workflow filename or Jenkins job name
    cicd_url: str         = ""                    # Jenkins base URL or GitLab instance URL
    cicd_token: str       = ""                    # CI/CD API token (may differ from git_token)


@dataclass
class EmailConfig:
    """SMTP settings for sending alert emails."""
    smtp_host: str    = "smtp.gmail.com"
    smtp_port: int    = 587
    username: str     = ""
    password: str     = ""                        # use an app-password for Gmail
    from_address: str = ""                        # "FileAnalyzer <alerts@you.com>"
    enabled: bool     = False


@dataclass
class AlertRecord:
    """A single alert event recorded when errors exceed the project threshold."""
    project_id: str
    project_name: str
    log_file: str
    error_count: int
    warn_count: int
    top_errors: list[str]
    has_stack_traces: bool
    summary: str

    id: str           = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str    = field(default_factory=lambda: datetime.utcnow().isoformat())
    email_sent: bool  = False
    lines_analyzed: int = 0


# ── Persistent store ───────────────────────────────────────────────────────

class ProjectStore:
    """JSON-backed store for all monitoring data."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Projects ───────────────────────────────────────────────────────────

    def load_projects(self) -> list[ProjectConfig]:
        data = self._load(PROJECTS_FILE, {})
        return [ProjectConfig(**p) for p in data.get("projects", [])]

    def save_project(self, project: ProjectConfig) -> None:
        data = self._load(PROJECTS_FILE, {})
        projects = data.get("projects", [])
        for i, p in enumerate(projects):
            if p["id"] == project.id:
                projects[i] = asdict(project)
                break
        else:
            projects.append(asdict(project))
        data["projects"] = projects
        self._save(PROJECTS_FILE, data)

    def delete_project(self, project_id: str) -> None:
        data = self._load(PROJECTS_FILE, {})
        data["projects"] = [p for p in data.get("projects", []) if p["id"] != project_id]
        self._save(PROJECTS_FILE, data)

    def get_project(self, project_id: str) -> Optional[ProjectConfig]:
        return next((p for p in self.load_projects() if p.id == project_id), None)

    # ── Email config ───────────────────────────────────────────────────────

    def load_email_config(self) -> EmailConfig:
        data = self._load(PROJECTS_FILE, {})
        ec = data.get("email", {})
        if not ec:
            return EmailConfig()
        # Only pass known fields to avoid dataclass errors on old schemas
        known = {f.name for f in EmailConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return EmailConfig(**{k: v for k, v in ec.items() if k in known})

    def save_email_config(self, config: EmailConfig) -> None:
        data = self._load(PROJECTS_FILE, {})
        data["email"] = asdict(config)
        self._save(PROJECTS_FILE, data)

    # ── Alert history ──────────────────────────────────────────────────────

    def load_alerts(self, project_id: str = None, limit: int = 50) -> list[AlertRecord]:
        records = self._load(ALERT_HISTORY_FILE, [])
        alerts = []
        for r in records:
            try:
                known = {f for f in AlertRecord.__dataclass_fields__}  # type: ignore[attr-defined]
                alerts.append(AlertRecord(**{k: v for k, v in r.items() if k in known}))
            except Exception:
                continue
        if project_id:
            alerts = [a for a in alerts if a.project_id == project_id]
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)[:limit]

    def save_alert(self, alert: AlertRecord) -> None:
        records = self._load(ALERT_HISTORY_FILE, [])
        records.insert(0, asdict(alert))
        self._save(ALERT_HISTORY_FILE, records[:500])

    def alert_count_today(self, project_id: str = None) -> int:
        today = datetime.utcnow().date().isoformat()
        return sum(
            1 for a in self.load_alerts(project_id=project_id, limit=500)
            if a.timestamp.startswith(today)
        )

    # ── Log positions ──────────────────────────────────────────────────────

    def get_log_position(self, project_id: str, log_path: str) -> int:
        positions = self._load(LOG_POSITIONS_FILE, {})
        return positions.get(project_id, {}).get(log_path, 0)

    def save_log_position(self, project_id: str, log_path: str, position: int) -> None:
        positions = self._load(LOG_POSITIONS_FILE, {})
        if project_id not in positions:
            positions[project_id] = {}
        positions[project_id][log_path] = position
        self._save(LOG_POSITIONS_FILE, positions)

    def reset_log_positions(self, project_id: str) -> None:
        positions = self._load(LOG_POSITIONS_FILE, {})
        positions.pop(project_id, None)
        self._save(LOG_POSITIONS_FILE, positions)

    # ── Internal ───────────────────────────────────────────────────────────

    @staticmethod
    def _load(path: Path, default):
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return default

    @staticmethod
    def _save(path: Path, data) -> None:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
