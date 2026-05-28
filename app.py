"""
FileAnalyzer — Streamlit Web UI (multi-page monitoring agent)

Pages:
  📊 Dashboard       — all projects overview, recent alerts, error counts
  🔌 Projects        — add / edit / delete Spring Boot projects, test SSH, trigger checks
  📄 Document Analysis — manual file upload + RAG Q&A (original feature)
  ⚙️ Settings        — SMTP email config, scheduler status

Run with:
    streamlit run app.py
"""
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FileAnalyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer    {visibility: hidden;}
header    {visibility: hidden;}

[data-testid="stFileUploader"] > div {
    border: 2px dashed #4A90D9; border-radius: 16px;
    padding: 2rem; background: rgba(74,144,217,.04); transition: border-color .2s;
}
[data-testid="stFileUploader"] > div:hover {
    border-color: #2563EB; background: rgba(74,144,217,.08);
}
[data-testid="stChatMessage"] { border-radius: 12px; margin-bottom: .5rem; }

[data-testid="stSidebar"] { background:#F1F5F9; border-right:1px solid #E2E8F0; }
[data-testid="stSidebar"] * { color:#1E293B !important; }
[data-testid="stSidebar"] .stButton>button {
    background:#fff; border:1px solid #CBD5E1; color:#1E293B !important;
}
[data-testid="stSidebar"] .stButton>button:hover {
    background:#E2E8F0; border-color:#94A3B8;
}
[data-testid="stSidebar"] hr { border-color:#CBD5E1; }

.stButton>button { border-radius:8px; font-weight:500; }

/* Status badge helpers */
.badge-green  { background:#14532D; color:#86EFAC; padding:2px 10px; border-radius:12px; font-size:12px; }
.badge-red    { background:#7F1D1D; color:#FCA5A5; padding:2px 10px; border-radius:12px; font-size:12px; }
.badge-yellow { background:#713F12; color:#FDE68A; padding:2px 10px; border-radius:12px; font-size:12px; }
.badge-gray   { background:#1E293B; color:#94A3B8;  padding:2px 10px; border-radius:12px; font-size:12px; }

/* Suggested question buttons */
.sq-btn>button {
    background:rgba(74,144,217,.08)!important; border:1px solid rgba(74,144,217,.3)!important;
    color:#93C5FD!important; text-align:left!important; font-size:.85rem!important;
    white-space:normal!important; height:auto!important; min-height:2.5rem;
}
.sq-btn>button:hover { background:rgba(74,144,217,.18)!important; border-color:#60A5FA!important; }
</style>
""", unsafe_allow_html=True)


# ── Singletons ──────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_embedding_engine():
    from src.embeddings import EmbeddingEngine
    return EmbeddingEngine()

@st.cache_resource(show_spinner=False)
def get_vector_store():
    from src.vector_store import VectorStore
    return VectorStore()

@st.cache_resource(show_spinner=False)
def get_monitor():
    from src.monitor import MonitorScheduler
    sched = MonitorScheduler()
    sched.start()
    return sched

@st.cache_resource(show_spinner=False)
def get_project_store():
    from src.project_config import ProjectStore
    return ProjectStore()


# ── Session state ───────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "page":              "Dashboard",
        # Document Analysis state
        "messages":          [],
        "indexed_file_name": None,
        "collection_name":   None,
        "chunk_count":       0,
        "retriever":         None,
        "doc_analysis":      None,
        "pending_question":  None,
        # Projects page state
        "edit_project_id":   None,
        "show_add_form":     False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — navigation + context-sensitive AI provider panel
# ════════════════════════════════════════════════════════════════════════════

def render_sidebar():
    """Render sidebar navigation and return (provider, api_key, model)."""
    from src.config import OPENAI_MODELS, ANTHROPIC_MODELS

    with st.sidebar:
        st.markdown("## 🔍 FileAnalyzer")
        st.caption("Monitoring Agent + Document Q&A")
        st.divider()

        # ── Page navigation ─────────────────────────────────────────────
        st.markdown("### Navigation")
        page = st.radio(
            "page",
            ["📊 Dashboard", "🔌 Projects", "📄 Document Analysis", "⚙️ Settings"],
            label_visibility="collapsed",
            index=["📊 Dashboard", "🔌 Projects", "📄 Document Analysis", "⚙️ Settings"]
                  .index(st.session_state.page)
                  if st.session_state.page in
                  ["📊 Dashboard", "🔌 Projects", "📄 Document Analysis", "⚙️ Settings"]
                  else 0,
        )
        st.session_state.page = page
        st.divider()

        # ── AI provider (only shown for Document Analysis) ───────────────
        provider = api_key = model = ""
        if page == "📄 Document Analysis":
            st.markdown("### ⚙️ AI Provider")
            provider_label = st.radio(
                "provider",
                ["OpenAI (ChatGPT)", "Anthropic (Claude)"],
                label_visibility="collapsed",
            )
            provider = "openai" if "OpenAI" in provider_label else "anthropic"

            if provider == "openai":
                api_key = st.text_input(
                    "OpenAI API Key",
                    value=os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", ""),
                    type="password", placeholder="sk-...",
                )
                model = st.selectbox("Model", OPENAI_MODELS)
            else:
                api_key = st.text_input(
                    "Anthropic API Key",
                    value=os.environ.get("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY", ""),
                    type="password", placeholder="sk-ant-...",
                )
                model = st.selectbox("Model", ANTHROPIC_MODELS)

            st.divider()

            # Loaded document shortcuts
            if st.session_state.indexed_file_name:
                st.markdown("### 📄 Loaded")
                if st.session_state.doc_analysis:
                    a = st.session_state.doc_analysis
                    st.markdown(
                        f"<span class='badge-gray'>{a.type_icon} {a.type_label}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("")
                st.success(st.session_state.indexed_file_name)
                st.caption(f"{st.session_state.chunk_count:,} chunks")
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("💬", use_container_width=True, help="Clear chat"):
                        st.session_state.messages = []
                        st.rerun()
                with c2:
                    if st.button("📂", use_container_width=True, help="New file"):
                        _clear_doc_state(); st.rerun()
                with c3:
                    if st.button("🗑️", use_container_width=True, help="Delete index"):
                        _delete_collection(st.session_state.collection_name)
                        _clear_doc_state(); st.rerun()
                st.divider()

            # Previous documents
            store = get_vector_store()
            available = [
                c for c in store.list_collections()
                if c != st.session_state.collection_name
            ]
            if available:
                st.markdown("### 📚 Previous")
                for cname in available:
                    count = store.collection_count(cname)
                    cl, cd = st.columns([4, 1])
                    with cl:
                        if st.button(f"📄 {cname}", key=f"load_{cname}", use_container_width=True):
                            _load_collection(cname, count); st.rerun()
                    with cd:
                        if st.button("✕", key=f"del_{cname}", use_container_width=True):
                            _delete_collection(cname); st.rerun()
                st.divider()

        # ── Scheduler status (always visible) ───────────────────────────
        mon = get_monitor()
        if mon.is_running:
            st.markdown(
                f"<span class='badge-green'>⏱ Scheduler: {mon.job_count()} job(s)</span>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<span class='badge-gray'>⏸ Scheduler paused</span>",
                unsafe_allow_html=True,
            )

    return provider, api_key, model


# ════════════════════════════════════════════════════════════════════════════
#  PAGE 1 — DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

def render_dashboard():
    st.markdown("## 📊 Monitoring Dashboard")

    store    = get_project_store()
    projects = store.load_projects()
    mon      = get_monitor()

    if not projects:
        st.info(
            "No projects configured yet. Go to **🔌 Projects** to add your first "
            "Spring Boot / Apache project.",
            icon="ℹ️",
        )
        if st.button("➕ Add First Project", type="primary"):
            st.session_state.page = "🔌 Projects"
            st.session_state.show_add_form = True
            st.rerun()
        return

    # ── Top-level metrics ────────────────────────────────────────────────
    total_today   = store.alert_count_today()
    proj_with_err = sum(1 for p in projects if store.alert_count_today(p.id) > 0)
    enabled_count = sum(1 for p in projects if p.enabled)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Projects",         len(projects))
    m2.metric("Enabled",          enabled_count)
    m3.metric("Alerts today",     total_today,   delta=None)
    m4.metric("Projects w/ errors today", proj_with_err, delta=None)

    st.divider()

    # ── Project cards ─────────────────────────────────────────────────────
    st.markdown("### Project Status")
    next_runs = mon.next_run_times()

    cols = st.columns(min(len(projects), 2))
    for i, project in enumerate(projects):
        alerts_today = store.alert_count_today(project.id)
        last_alerts  = store.load_alerts(project.id, limit=1)

        if not project.enabled:
            status_badge = "<span class='badge-gray'>⏸ Disabled</span>"
        elif alerts_today > 0:
            status_badge = f"<span class='badge-red'>🔴 {alerts_today} alert(s) today</span>"
        elif last_alerts:
            status_badge = "<span class='badge-green'>✅ OK</span>"
        else:
            status_badge = "<span class='badge-gray'>⏳ Not checked yet</span>"

        last_check = (
            last_alerts[0].timestamp[:16].replace("T", " ") + " UTC"
            if last_alerts else "—"
        )
        nxt = next_runs.get(project.id)
        next_check = nxt[:16].replace("T", " ") + " UTC" if nxt else "—"

        with cols[i % 2]:
            st.markdown(f"""
<div style='background:#1E293B;border-radius:12px;padding:18px 20px;margin-bottom:12px;
            border:1px solid #334155;'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;'>
    <div>
      <span style='font-size:16px;font-weight:700;color:#F1F5F9;'>{project.name}</span><br>
      <span style='font-size:12px;color:#64748B;'>{project.host} · {project.app_type}</span>
    </div>
    {status_badge}
  </div>
  <div style='font-size:12px;color:#94A3B8;line-height:1.8;'>
    <b style='color:#CBD5E1;'>Log files:</b> {len(project.log_paths)}<br>
    <b style='color:#CBD5E1;'>Last check:</b> {last_check}<br>
    <b style='color:#CBD5E1;'>Next check:</b> {next_check}<br>
    <b style='color:#CBD5E1;'>Interval:</b> every {project.check_interval_min} min
  </div>
</div>
""", unsafe_allow_html=True)
            if st.button("▶ Check Now", key=f"dash_check_{project.id}", use_container_width=True):
                with st.spinner(f"Checking {project.name}…"):
                    result = mon.run_now(project.id)
                _show_check_result(result)
                st.rerun()

    # ── Recent alerts table ───────────────────────────────────────────────
    st.divider()
    st.markdown("### Recent Alerts")
    recent = store.load_alerts(limit=20)

    if not recent:
        st.markdown(
            "<div style='text-align:center;padding:2rem;color:#64748B;'>"
            "No alerts recorded yet.</div>",
            unsafe_allow_html=True,
        )
        return

    for a in recent:
        ts = a.timestamp[:16].replace("T", " ") + " UTC"
        with st.expander(
            f"🔴 {a.project_name}  ·  {a.error_count} errors  ·  {ts}",
            expanded=False,
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Errors",  a.error_count)
            c2.metric("Warnings", a.warn_count)
            c3.metric("Lines",   f"{a.lines_analyzed:,}")
            c4.metric("Email",   "✅ Sent" if a.email_sent else "—")
            st.caption(f"Log: {a.log_file}")
            if a.top_errors:
                st.markdown("**Top error messages:**")
                for e in a.top_errors:
                    st.code(e, language=None)
            if a.has_stack_traces:
                st.warning("Stack traces detected in this log segment.")
            st.markdown(f"_{a.summary}_")


# ════════════════════════════════════════════════════════════════════════════
#  PAGE 2 — PROJECTS
# ════════════════════════════════════════════════════════════════════════════

def render_projects():
    st.markdown("## 🔌 Projects")
    st.caption("Connect FileAnalyzer to your Java Spring Boot / Apache servers on AWS.")

    store = get_project_store()
    mon   = get_monitor()

    # ── Add / Edit form ───────────────────────────────────────────────────
    editing_id = st.session_state.edit_project_id
    editing    = store.get_project(editing_id) if editing_id else None

    if st.session_state.show_add_form or editing:
        with st.form("project_form", clear_on_submit=False):
            st.markdown(f"#### {'✏️ Edit' if editing else '➕ Add'} Project")

            tab_server, tab_git, tab_monitor = st.tabs(["🖥️ Server & SSH", "🔀 Git & Deploy", "🔔 Monitoring"])

            with tab_server:
                c1, c2 = st.columns(2)
                with c1:
                    name     = st.text_input("Project name *",     value=editing.name     if editing else "", placeholder="Payment Service")
                    host     = st.text_input("Server host / IP *", value=editing.host     if editing else "", placeholder="52.9.150.108")
                    username = st.text_input("SSH username *",     value=editing.username if editing else "ec2-user")
                    port     = st.number_input("SSH port", value=editing.port if editing else 22, min_value=1, max_value=65535)
                with c2:
                    auth_method = st.radio("Auth method", ["key", "password"],
                        index=0 if not editing else (0 if editing.auth_method == "key" else 1),
                        horizontal=True)
                    ssh_key = st.text_input(
                        "PEM key path" if auth_method == "key" else "SSH password",
                        value=(editing.ssh_key_path if editing else "") if auth_method == "key"
                              else (editing.ssh_password if editing else ""),
                        type="password" if auth_method == "password" else "default",
                        placeholder="E:\\Pavithra\\Deployment\\key.pem" if auth_method == "key" else "",
                    )
                    deploy_path  = st.text_input("Repo path on server",
                        value=editing.deploy_path if editing else "", placeholder="/opt/payment-service",
                        help="Directory where the repo is (or will be) cloned on the server.")
                    restart_cmd  = st.text_input("Restart command",
                        value=editing.restart_cmd if editing else "",
                        placeholder="sudo systemctl restart payment-service")
                    artifact_dest = st.text_input("Artifact destination (optional override)",
                        value=editing.artifact_dest if editing else "",
                        placeholder="/opt/tomcat/webapps  or  /var/www/html")

            with tab_git:
                gc1, gc2 = st.columns(2)
                with gc1:
                    git_url    = st.text_input("Git repository URL",
                        value=editing.git_url if editing else "",
                        placeholder="https://github.com/org/payment-service.git")
                    git_branch = st.text_input("Branch to deploy",
                        value=editing.git_branch if editing else "main")
                    git_token  = st.text_input("Git token (GitHub PAT / GitLab token)",
                        value=editing.git_token if editing else "", type="password",
                        help="Personal Access Token with repo + workflow scopes.")
                    git_username = st.text_input("Git username (optional for HTTPS auth)",
                        value=editing.git_username if editing else "")
                with gc2:
                    # CI/CD
                    project_type  = st.text_input("Project type (auto-filled by Detect)",
                        value=editing.project_type if editing else "",
                        placeholder="spring_boot_jar  (click Detect below)")
                    build_tool    = st.text_input("Build tool",
                        value=editing.build_tool if editing else "", placeholder="maven | gradle | npm")
                    build_command = st.text_input("Build command",
                        value=editing.build_command if editing else "",
                        placeholder="mvn clean package -DskipTests")
                    artifact_path = st.text_input("Artifact path",
                        value=editing.artifact_path if editing else "", placeholder="target/*.jar")

                st.markdown("**CI/CD pipeline**")
                ci1, ci2 = st.columns(2)
                with ci1:
                    cicd_type     = st.selectbox("CI/CD type",
                        ["none", "github_actions", "jenkins", "gitlab_ci", "circleci", "bitbucket"],
                        index=["none","github_actions","jenkins","gitlab_ci","circleci","bitbucket"]
                              .index(editing.cicd_type) if editing and editing.cicd_type in
                              ["none","github_actions","jenkins","gitlab_ci","circleci","bitbucket"] else 0)
                    cicd_workflow = st.text_input("Workflow / job name",
                        value=editing.cicd_workflow if editing else "",
                        placeholder=".github/workflows/deploy.yml  or  jenkins-job-name")
                with ci2:
                    cicd_url   = st.text_input("CI/CD URL (Jenkins only)",
                        value=editing.cicd_url if editing else "", placeholder="http://jenkins.company.com")
                    cicd_token = st.text_input("CI/CD token",
                        value=editing.cicd_token if editing else "", type="password",
                        help="GitHub token, Jenkins API token, or GitLab token for triggering pipelines.")

            with tab_monitor:
                st.markdown("**Log file paths** (one per line)")
                default_paths = "\n".join(editing.log_paths) if editing else (
                    "/var/log/app/app.log\n/opt/tomcat/logs/catalina.out"
                )
                log_paths_raw = st.text_area("Log paths", value=default_paths, height=100, label_visibility="collapsed")
                mc1, mc2 = st.columns(2)
                with mc1:
                    interval  = st.number_input("Check every (minutes)",
                        value=editing.check_interval_min if editing else 15, min_value=1, max_value=1440)
                    threshold = st.number_input("Alert threshold (errors)",
                        value=editing.error_threshold if editing else 0, min_value=0,
                        help="0 = alert on ANY error")
                with mc2:
                    notify_raw = st.text_input("Notify emails (comma-separated)",
                        value=", ".join(editing.notify_emails) if editing else "",
                        placeholder="dev@company.com, ops@company.com")
                    enabled = st.checkbox("Enable monitoring", value=editing.enabled if editing else True)

            col_save, col_cancel = st.columns([1, 4])
            with col_save:
                submitted = st.form_submit_button("💾 Save", type="primary", use_container_width=True)
            with col_cancel:
                if st.form_submit_button("Cancel"):
                    st.session_state.show_add_form   = False
                    st.session_state.edit_project_id = None
                    st.rerun()

            if submitted:
                if not name or not host or not username:
                    st.error("Name, host, and username are required.")
                else:
                    from src.project_config import ProjectConfig
                    import uuid
                    pid = editing.id if editing else str(uuid.uuid4())[:8]
                    proj = ProjectConfig(
                        id=pid,
                        name=name.strip(),
                        host=host.strip(),
                        username=username.strip(),
                        port=int(port),
                        auth_method=auth_method,
                        ssh_key_path=ssh_key.strip()  if auth_method == "key"      else (editing.ssh_key_path  if editing else ""),
                        ssh_password=ssh_key.strip()  if auth_method == "password" else (editing.ssh_password  if editing else ""),
                        deploy_path=deploy_path.strip(),
                        artifact_dest=artifact_dest.strip(),
                        restart_cmd=restart_cmd.strip(),
                        log_paths=[p.strip() for p in log_paths_raw.splitlines() if p.strip()],
                        check_interval_min=int(interval),
                        error_threshold=int(threshold),
                        notify_emails=[e.strip() for e in notify_raw.split(",") if e.strip()],
                        enabled=enabled,
                        created_at=editing.created_at if editing else datetime.utcnow().isoformat(),
                        # Git & CI/CD
                        git_url=git_url.strip(),
                        git_branch=git_branch.strip() or "main",
                        git_token=git_token,
                        git_username=git_username.strip(),
                        project_type=project_type.strip(),
                        build_tool=build_tool.strip(),
                        build_command=build_command.strip(),
                        artifact_path=artifact_path.strip(),
                        cicd_type=cicd_type,
                        cicd_workflow=cicd_workflow.strip(),
                        cicd_url=cicd_url.strip(),
                        cicd_token=cicd_token,
                    )
                    store.save_project(proj)
                    mon.sync_projects(store.load_projects())
                    st.session_state.show_add_form   = False
                    st.session_state.edit_project_id = None
                    st.success(f"Project '{name}' saved.")
                    st.rerun()

        st.divider()

    # ── Project list ──────────────────────────────────────────────────────
    projects = store.load_projects()

    if not projects and not st.session_state.show_add_form:
        st.info("No projects yet. Add your first project above.")

    if not st.session_state.show_add_form and not editing:
        if st.button("➕ Add Project", type="primary"):
            st.session_state.show_add_form  = True
            st.session_state.edit_project_id = None
            st.rerun()

    for project in projects:
        alerts_today = store.alert_count_today(project.id)
        status_icon  = "✅" if project.enabled and alerts_today == 0 else ("🔴" if alerts_today > 0 else "⏸")

        with st.expander(
            f"{status_icon}  {project.name}  ·  {project.host}  ·  {project.app_type}",
            expanded=False,
        ):
            ci1, ci2, ci3 = st.columns(3)
            ci1.markdown(f"**Host:** `{project.host}:{project.port}`")
            ci2.markdown(f"**User:** `{project.username}`")
            ci3.markdown(f"**Auth:** `{project.auth_method}`")

            st.markdown("**Log paths:**")
            for lp in project.log_paths:
                st.code(lp, language=None)

            st.markdown(
                f"**Interval:** every {project.check_interval_min} min  ·  "
                f"**Threshold:** {project.error_threshold} errors  ·  "
                f"**Notify:** {', '.join(project.notify_emails) or '—'}"
            )
            if project.deploy_path:
                st.markdown(f"**Deploy path:** `{project.deploy_path}`  ·  **Restart:** `{project.restart_cmd}`")

            # ── Server info ────────────────────────────────────────────────
            ci1, ci2, ci3 = st.columns(3)
            ci1.markdown(f"**Host:** `{project.host}:{project.port}`")
            ci2.markdown(f"**User:** `{project.username}`  ·  **Auth:** `{project.auth_method}`")
            ci3.markdown(f"**Interval:** every {project.check_interval_min} min")

            # ── Git & project type info ─────────────────────────────────────
            if project.git_url:
                st.markdown("---")
                g1, g2, g3 = st.columns(3)
                g1.markdown(f"**Git:** `{project.git_url.split('/')[-1]}`  branch `{project.git_branch}`")
                if project.project_type:
                    from src.git_connector import _TYPE_ICONS, _TYPE_LABELS, _CICD_LABELS
                    icon  = _TYPE_ICONS.get(project.project_type, "📦")
                    label = _TYPE_LABELS.get(project.project_type, project.project_type)
                    g2.markdown(f"**Type:** {icon} {label}")
                    if project.cicd_type and project.cicd_type != "none":
                        g3.markdown(f"**CI/CD:** ✅ {_CICD_LABELS.get(project.cicd_type, project.cicd_type)}")
                    else:
                        g3.markdown("**CI/CD:** SSH build+deploy")
                if project.build_command:
                    st.code(project.build_command, language="bash")

            # ── Action buttons ─────────────────────────────────────────────
            st.markdown("---")
            ba, bb, bc, bd, be = st.columns(5)
            with ba:
                if st.button("🔗 Test SSH", key=f"test_{project.id}", use_container_width=True):
                    from src.log_fetcher import LogFetcher
                    with st.spinner("Connecting…"):
                        ok, err = LogFetcher().test_connection(project)
                    if ok:
                        st.success("SSH OK ✅")
                    else:
                        st.error(f"Failed: {err}")

            with bb:
                if st.button("▶ Check Logs", key=f"check_{project.id}", use_container_width=True):
                    with st.spinner(f"Checking {project.name}…"):
                        result = mon.run_now(project.id)
                    _show_check_result(result)

            with bc:
                detect_label = "🔍 Detect" if not project.project_type else "🔍 Re-detect"
                if st.button(detect_label, key=f"detect_{project.id}", use_container_width=True,
                             help="Read git repo and auto-detect project type + CI/CD"):
                    if not project.git_url:
                        st.error("Set git_url in the Git & Deploy tab first.")
                    else:
                        with st.spinner(f"Reading {project.git_url.split('/')[-1]}…"):
                            from src.git_connector import GitConnector
                            info = GitConnector().detect_project(
                                project.git_url, project.git_token, project.git_branch
                            )
                        _show_detect_result(info)
                        if info.confidence != "low":
                            # Auto-save detected fields back to project
                            project.project_type  = info.project_type
                            project.build_tool    = info.build_tool
                            project.build_command = info.build_command
                            project.artifact_path = info.artifact_path
                            project.cicd_type     = info.cicd_type
                            project.cicd_workflow = (info.cicd_files[0] if info.cicd_files else "")
                            store.save_project(project)
                            st.success("Project type saved ✅")
                            st.rerun()

            with bd:
                if st.button("✏️ Edit", key=f"edit_{project.id}", use_container_width=True):
                    st.session_state.edit_project_id = project.id
                    st.session_state.show_add_form   = False
                    st.rerun()

            with be:
                if st.button("🗑️ Delete", key=f"del_{project.id}", use_container_width=True):
                    store.delete_project(project.id)
                    store.reset_log_positions(project.id)
                    mon.sync_projects(store.load_projects())
                    st.rerun()

            # ── Deploy button ───────────────────────────────────────────────
            if project.git_url and (project.project_type or project.build_command):
                st.markdown("---")
                cicd = project.cicd_type
                if cicd and cicd != "none":
                    from src.git_connector import _CICD_LABELS
                    btn_label = f"🚀 Deploy via {_CICD_LABELS.get(cicd, cicd)}"
                    help_txt  = "Trigger the CI/CD pipeline via API"
                else:
                    btn_label = "🚀 Build & Deploy via SSH"
                    help_txt  = "SSH → git pull → build → restart on server"

                if st.button(btn_label, key=f"deploy_{project.id}",
                             type="primary", use_container_width=False, help=help_txt):
                    _run_deploy(project)

            # ── Reset log positions ─────────────────────────────────────────
            if st.button("↺ Reset log positions", key=f"reset_{project.id}",
                         help="Force re-read from end of log file on next check"):
                store.reset_log_positions(project.id)
                st.success("Log positions reset.")


def _show_detect_result(info):
    """Render a ProjectTypeInfo card in the UI."""
    from src.git_connector import _CICD_LABELS
    conf_color = {"high": "#22C55E", "medium": "#F59E0B", "low": "#EF4444"}.get(info.confidence, "#94A3B8")
    cicd_label = _CICD_LABELS.get(info.cicd_type, info.cicd_type)

    st.markdown(f"""
<div style='background:#1E293B;border-radius:10px;padding:16px 20px;border:1px solid #334155;margin:8px 0;'>
  <div style='font-size:22px;margin-bottom:6px;'>{info.type_icon} <strong style='color:#F1F5F9;font-size:16px;'>{info.type_label}</strong>
    <span style='font-size:11px;color:{conf_color};margin-left:8px;'>● {info.confidence} confidence</span>
  </div>
  <table style='font-size:13px;border-collapse:collapse;width:100%;'>
    <tr><td style='color:#94A3B8;padding:3px 0;width:130px;'>Build tool</td>
        <td style='color:#F1F5F9;'><code>{info.build_tool}</code></td></tr>
    <tr><td style='color:#94A3B8;padding:3px 0;'>Build command</td>
        <td style='color:#F1F5F9;'><code>{info.build_command or "—"}</code></td></tr>
    <tr><td style='color:#94A3B8;padding:3px 0;'>Artifact path</td>
        <td style='color:#F1F5F9;'><code>{info.artifact_path or "—"}</code></td></tr>
    <tr><td style='color:#94A3B8;padding:3px 0;'>Deploy method</td>
        <td style='color:#F1F5F9;'>{info.deploy_method}</td></tr>
    <tr><td style='color:#94A3B8;padding:3px 0;'>CI/CD pipeline</td>
        <td style='color:{"#22C55E" if info.cicd_type != "none" else "#64748B"};'>
          {"✅ " if info.cicd_type != "none" else ""}{cicd_label}
          {(" — " + ", ".join(info.cicd_files)) if info.cicd_files else ""}
        </td></tr>
    <tr><td style='color:#94A3B8;padding:3px 0;'>Detected from</td>
        <td style='color:#64748B;font-size:12px;'>{", ".join(info.detected_from) or "—"}</td></tr>
  </table>
</div>
""", unsafe_allow_html=True)


def _run_deploy(project):
    """Run deployment and stream output to the UI."""
    from src.deployer import Deployer

    output_box = st.empty()
    lines: list[str] = []

    def on_log(line: str):
        lines.append(line)
        output_box.code("\n".join(lines), language=None)

    with st.spinner("Deploying…"):
        result = Deployer().deploy(project, on_log=on_log)

    if result.success:
        st.success(f"✅ {result.message}")
        if result.job_url:
            st.markdown(f"**Pipeline URL:** [{result.job_url}]({result.job_url})")
    else:
        st.error(f"❌ Deployment failed: {result.message}")
        if result.output:
            with st.expander("Full output", expanded=True):
                st.code(result.output, language=None)


def _show_check_result(result: dict):
    if result.get("error"):
        st.error(result["error"])
        return
    alerts = result.get("alerts", [])
    errors = result.get("errors", [])
    no_new = result.get("no_new_content", [])

    if alerts:
        for a in alerts:
            st.error(f"🔴 {a['log'].split('/')[-1]}: {a['errors']} error(s), {a['warns']} warning(s)")
    elif errors:
        for e in errors:
            st.warning(f"⚠️ {e['log']}: {e['msg']}")
    elif no_new:
        st.info("No new log content since last check.")
    else:
        st.success("✅ No errors detected in new log content.")


# ════════════════════════════════════════════════════════════════════════════
#  PAGE 3 — DOCUMENT ANALYSIS (original feature)
# ════════════════════════════════════════════════════════════════════════════

def render_document_analysis(provider: str, api_key: str, model: str):
    if st.session_state.indexed_file_name:
        render_chat_ui(provider, api_key, model)
    else:
        render_upload_ui(provider, api_key, model)


def render_upload_ui(provider: str, api_key: str, model: str):
    st.markdown("""
<div style="text-align:center;padding:2rem 0 1rem;">
    <h1 style="font-size:2.8rem;margin-bottom:.25rem;">🔍 Document Analysis</h1>
    <p style="font-size:1.1rem;color:#94A3B8;">
        Upload a document — get instant AI analysis and answers.
    </p>
</div>
""", unsafe_allow_html=True)
    st.markdown("""
<div style="text-align:center;margin-bottom:2rem;">
  <span style="background:#1E3A5F;color:#60A5FA;padding:4px 12px;border-radius:20px;margin:4px;display:inline-block;font-size:.85rem;">📄 PDF</span>
  <span style="background:#1E3A5F;color:#60A5FA;padding:4px 12px;border-radius:20px;margin:4px;display:inline-block;font-size:.85rem;">📝 DOCX</span>
  <span style="background:#1E3A5F;color:#60A5FA;padding:4px 12px;border-radius:20px;margin:4px;display:inline-block;font-size:.85rem;">📃 TXT</span>
  <span style="background:#1E3A5F;color:#60A5FA;padding:4px 12px;border-radius:20px;margin:4px;display:inline-block;font-size:.85rem;">📊 CSV</span>
  <span style="background:#1E3A5F;color:#60A5FA;padding:4px 12px;border-radius:20px;margin:4px;display:inline-block;font-size:.85rem;">🖥️ LOG</span>
</div>
""", unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        uploaded_file = st.file_uploader(
            "Drop your file here or click to browse",
            type=["pdf", "docx", "txt", "csv", "log"],
        )
        if uploaded_file:
            size_mb = len(uploaded_file.getvalue()) / (1024 ** 2)
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:.6rem .2rem;"
                f"color:#94A3B8;font-size:.85rem;'>"
                f"<span>📁 {uploaded_file.name}</span><span>{size_mb:.2f} MB</span></div>",
                unsafe_allow_html=True,
            )
            if not api_key:
                st.warning(
                    f"Enter your {'OpenAI' if provider == 'openai' else 'Anthropic'} "
                    "API key in the sidebar.", icon="🔑",
                )
                return
            if st.button("🚀 Analyze Document", type="primary", use_container_width=True):
                _run_ingestion(uploaded_file, provider, api_key, model)

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    for col_obj, icon, title, desc in [
        (c1, "🧠", "Auto Document Intelligence", "Detects type, extracts findings, suggests questions"),
        (c2, "🖥️", "Log File Analysis",          "Counts ERRORs/WARNs, finds stack traces, top errors"),
        (c3, "💬", "Deep Q&A",                   "Answers grounded in your document with source excerpts"),
    ]:
        col_obj.markdown(f"""
<div style="text-align:center;padding:1.2rem;background:rgba(255,255,255,.03);
            border-radius:12px;border:1px solid rgba(255,255,255,.07);">
  <div style="font-size:2rem;">{icon}</div>
  <strong>{title}</strong>
  <p style="color:#94A3B8;font-size:.85rem;margin-top:.3rem;">{desc}</p>
</div>""", unsafe_allow_html=True)


def _run_ingestion(uploaded_file, provider: str, api_key: str, model: str):
    from src.pipeline import IngestionPipeline
    from src.retriever import Retriever
    from src.utils.file_utils import collection_name_from_path

    engine   = get_embedding_engine()
    store    = get_vector_store()
    pipeline = IngestionPipeline(engine, store)
    suffix   = Path(uploaded_file.name).suffix
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue()); tmp_path = tmp.name

        collection_name = collection_name_from_path(uploaded_file.name)

        with st.status("🔍 Analyzing your document…", expanded=True) as status:
            st.write("📂 Reading file…")
            chunk_ctr = st.empty()
            prog      = st.progress(0.0)
            done      = [0]

            def on_progress(n):
                done[0] += n
                chunk_ctr.markdown(f"⚙️  **{done[0]:,}** chunks processed")
                prog.progress(min(done[0] / max(done[0] + 200, 1), 0.95))

            st.write("🔬 Parsing, chunking & embedding…")
            try:
                result = pipeline.ingest(tmp_path, force_reindex=True,
                                         on_progress=on_progress,
                                         collection_name=collection_name)
            except Exception as e:
                status.update(label="❌ Error", state="error")
                st.error(f"Failed to index: {e}"); return

            prog.progress(1.0)
            chunk_ctr.markdown(
                f"✅  **{result.chunk_count:,}** chunks indexed in {result.duration_seconds:.1f}s"
            )

            # Auto-analysis
            st.write("🧠 Detecting document type and generating insights…")
            doc_analysis = None
            try:
                from src.analyzer import DocumentAnalyzer
                from src.llm import LLMClient
                llm  = LLMClient(provider=provider, api_key=api_key, model=model)
                ana  = DocumentAnalyzer()
                doc_analysis = ana.analyze(uploaded_file.name, store, llm)
                st.write(
                    f"{doc_analysis.type_icon} Detected: **{doc_analysis.type_label}** — "
                    f"{len(doc_analysis.suggested_questions)} questions generated"
                )
            except Exception as e:
                st.write(f"⚠️ Auto-analysis skipped: {e}")

            status.update(
                label=f"✅ Document ready — {result.chunk_count:,} chunks indexed",
                state="complete", expanded=False,
            )

        store.get_or_create_collection(collection_name)
        st.session_state.indexed_file_name = uploaded_file.name
        st.session_state.collection_name   = collection_name
        st.session_state.chunk_count       = result.chunk_count
        st.session_state.messages          = []
        st.session_state.retriever         = Retriever(engine, store)
        st.session_state.doc_analysis      = doc_analysis
        st.session_state.pending_question  = None
        st.rerun()

    finally:
        if tmp_path and Path(tmp_path).exists():
            try: Path(tmp_path).unlink()
            except: pass


def render_chat_ui(provider: str, api_key: str, model: str):
    from src.llm import LLMClient

    col_info, col_meta = st.columns([3, 1])
    with col_info:
        st.markdown(f"### 💬 Chat with **{st.session_state.indexed_file_name}**")
    with col_meta:
        st.metric("Chunks indexed", f"{st.session_state.chunk_count:,}")
    st.divider()

    if not api_key:
        st.warning(
            f"Enter your {'OpenAI' if provider=='openai' else 'Anthropic'} API key.", icon="🔑"
        ); return

    retriever = st.session_state.retriever
    if not retriever:
        st.error("No retriever found. Please re-upload the document."); return

    # Analysis panel
    analysis = st.session_state.doc_analysis
    if analysis:
        if not st.session_state.messages:
            _render_analysis_panel(analysis)
        else:
            with st.expander(
                f"{analysis.type_icon} {analysis.type_label} — Summary & Suggested Questions",
                expanded=False,
            ):
                _render_analysis_panel(analysis)
        st.divider()

    if not st.session_state.messages and not analysis:
        st.markdown("""
<div style="text-align:center;padding:3rem 0;color:#64748B;">
  <div style="font-size:2.5rem;margin-bottom:.5rem;">💭</div>
  <p>Ask anything about your document below.</p>
</div>""", unsafe_allow_html=True)

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="🧑" if msg["role"]=="user" else "🤖"):
            st.markdown(msg["content"])

    typed = st.chat_input("Ask a question about your document…")
    question = st.session_state.pending_question or typed
    if st.session_state.pending_question:
        st.session_state.pending_question = None
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(question)

    with st.spinner("Searching document…"):
        try:
            chunks = retriever.retrieve(question)
        except Exception as e:
            st.error(f"Retrieval error: {e}"); return

    if not chunks:
        ans = "I couldn't find relevant content in the document to answer that question."
        st.session_state.messages.append({"role": "assistant", "content": ans})
        with st.chat_message("assistant", avatar="🤖"): st.markdown(ans)
        return

    context = retriever.build_context(chunks)
    llm     = LLMClient(provider=provider, api_key=api_key, model=model)

    with st.chat_message("assistant", avatar="🤖"):
        ph = st.empty(); full = ""
        try:
            for token in llm.ask_stream(question, context):
                full += token; ph.markdown(full + "▌")
            ph.markdown(full)
        except Exception as e:
            ph.error(f"AI error: {e}"); full = f"Error: {e}"

    st.session_state.messages.append({"role": "assistant", "content": full})
    with st.expander(f"📎 {len(chunks)} source excerpt(s)", expanded=False):
        for i, c in enumerate(chunks):
            st.markdown(f"**Excerpt {i+1}**")
            st.text(c["text"][:600] + ("…" if len(c["text"])>600 else ""))
            if i < len(chunks)-1: st.divider()


def _render_analysis_panel(analysis):
    badge_col, stats_col = st.columns([2, 5])
    with badge_col:
        st.markdown(
            f"<div style='padding:.6rem 0;'><span style='background:#1E3A5F;color:#60A5FA;"
            f"padding:5px 14px;border-radius:20px;font-size:.95rem;font-weight:600;'>"
            f"{analysis.type_icon} {analysis.type_label}</span></div>",
            unsafe_allow_html=True,
        )
    if analysis.log_stats:
        ls = analysis.log_stats
        with stats_col:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ERRORS",   ls.error_count)
            m2.metric("WARNINGS", ls.warn_count)
            m3.metric("FATAL",    ls.fatal_count)
            m4.metric("INFO",     ls.info_count)
        if ls.has_stack_traces:
            st.markdown(
                "<span style='color:#F87171;font-size:.85rem;'>⚠️ Stack traces detected</span>",
                unsafe_allow_html=True,
            )

    with st.expander("📋 Summary & Key Findings", expanded=True):
        st.markdown(f"_{analysis.summary}_")
        if analysis.key_findings:
            st.markdown("**Key Findings**")
            for f in analysis.key_findings:
                st.markdown(f"- {f}")
        if analysis.log_stats and analysis.log_stats.top_errors:
            st.markdown("**Top Error Messages (from sample)**")
            for e in analysis.log_stats.top_errors:
                st.code(e, language=None)

    if analysis.suggested_questions:
        st.markdown(
            "<p style='color:#94A3B8;font-size:.85rem;margin-bottom:.4rem;'>"
            "💡 <strong>Suggested questions</strong> — click to ask instantly</p>",
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for i, q in enumerate(analysis.suggested_questions):
            with cols[i % 2]:
                st.markdown('<div class="sq-btn">', unsafe_allow_html=True)
                if st.button(q, key=f"sq_{i}", use_container_width=True):
                    st.session_state.pending_question = q; st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
#  PAGE 4 — SETTINGS
# ════════════════════════════════════════════════════════════════════════════

def render_settings():
    st.markdown("## ⚙️ Settings")

    store     = get_project_store()
    email_cfg = store.load_email_config()
    mon       = get_monitor()

    # ── Email / SMTP ──────────────────────────────────────────────────────
    st.markdown("### 📧 Email Alert Configuration")
    st.caption(
        "Used by all projects to send error alerts. "
        "For Gmail: create an App Password at myaccount.google.com/apppasswords."
    )

    with st.form("email_form"):
        c1, c2 = st.columns(2)
        with c1:
            smtp_host = st.text_input("SMTP host",     value=email_cfg.smtp_host, placeholder="smtp.gmail.com")
            username  = st.text_input("SMTP username", value=email_cfg.username,  placeholder="alerts@company.com")
            from_addr = st.text_input("From address",  value=email_cfg.from_address, placeholder="FileAnalyzer <alerts@company.com>")
        with c2:
            smtp_port = st.number_input("SMTP port", value=email_cfg.smtp_port, min_value=1, max_value=65535)
            password  = st.text_input("SMTP password / App password", value=email_cfg.password, type="password")
            enabled   = st.checkbox("Enable email alerts", value=email_cfg.enabled)

        test_recipient = st.text_input("Send test email to", placeholder="you@example.com")

        col_s, col_t = st.columns([1, 1])
        with col_s:
            save_clicked = st.form_submit_button("💾 Save Email Settings", type="primary")
        with col_t:
            test_clicked = st.form_submit_button("📨 Send Test Email")

        if save_clicked:
            from src.project_config import EmailConfig
            cfg = EmailConfig(
                smtp_host=smtp_host.strip(), smtp_port=int(smtp_port),
                username=username.strip(), password=password,
                from_address=from_addr.strip(), enabled=enabled,
            )
            store.save_email_config(cfg)
            st.success("Email settings saved.")

        if test_clicked:
            if not username or not password:
                st.error("Fill in SMTP username and password first.")
            elif not test_recipient:
                st.error("Enter a recipient email address.")
            else:
                from src.project_config import EmailConfig
                from src.alert_engine import AlertEngine
                cfg = EmailConfig(smtp_host=smtp_host, smtp_port=int(smtp_port),
                                  username=username, password=password,
                                  from_address=from_addr, enabled=True)
                with st.spinner("Sending…"):
                    ok, err = AlertEngine().send_test_email(cfg, test_recipient.strip())
                if ok:
                    st.success(f"Test email sent to {test_recipient} ✅")
                else:
                    st.error(f"Send failed: {err}")

    st.divider()

    # ── Scheduler status ──────────────────────────────────────────────────
    st.markdown("### ⏱ Scheduler Status")
    if mon.is_running:
        st.success(f"Background scheduler is running — {mon.job_count()} active job(s).")
        next_runs = mon.next_run_times()
        if next_runs:
            rows = []
            for pid, nxt in next_runs.items():
                proj = store.get_project(pid)
                rows.append({
                    "Project": proj.name if proj else pid,
                    "Next Run (UTC)": (nxt[:16].replace("T", " ") if nxt else "—"),
                })
            import pandas as pd
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("Scheduler is not running. apscheduler may not be installed.")
        if st.button("▶ Start Scheduler"):
            mon.start()
            st.rerun()

    col_sync, col_stop = st.columns(2)
    with col_sync:
        if st.button("🔄 Re-sync project jobs"):
            mon.sync_projects(store.load_projects())
            st.success("Jobs synced.")
    with col_stop:
        if st.button("⏹ Stop Scheduler"):
            mon.stop(); st.rerun()

    st.divider()

    # ── Danger zone ───────────────────────────────────────────────────────
    st.markdown("### 🗑️ Danger Zone")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Clear all alert history", use_container_width=True):
            from src.project_config import ALERT_HISTORY_FILE
            if ALERT_HISTORY_FILE.exists():
                ALERT_HISTORY_FILE.write_text("[]", encoding="utf-8")
            st.success("Alert history cleared.")
    with c2:
        if st.button("Reset all log positions", use_container_width=True):
            from src.project_config import LOG_POSITIONS_FILE
            if LOG_POSITIONS_FILE.exists():
                LOG_POSITIONS_FILE.write_text("{}", encoding="utf-8")
            st.success("All log positions reset — next checks will read from end of files.")


# ════════════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════════════

def _clear_doc_state():
    st.session_state.indexed_file_name = None
    st.session_state.collection_name   = None
    st.session_state.chunk_count       = 0
    st.session_state.messages          = []
    st.session_state.retriever         = None
    st.session_state.doc_analysis      = None
    st.session_state.pending_question  = None


def _load_collection(col_name: str, count: int):
    from src.retriever import Retriever
    engine = get_embedding_engine()
    vs     = get_vector_store()
    vs.get_or_create_collection(col_name)
    st.session_state.indexed_file_name = col_name
    st.session_state.collection_name   = col_name
    st.session_state.chunk_count       = count
    st.session_state.messages          = []
    st.session_state.retriever         = Retriever(engine, vs)
    st.session_state.doc_analysis      = None
    st.session_state.pending_question  = None


def _delete_collection(col_name: str):
    from src.exceptions import CollectionNotFoundError
    vs = get_vector_store()
    try:
        vs.delete_collection(col_name)
        st.toast(f"Deleted index for '{col_name}'", icon="🗑️")
    except CollectionNotFoundError:
        st.toast(f"'{col_name}' not found", icon="⚠️")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    provider, api_key, model = render_sidebar()

    # Sync scheduler jobs on every render (lightweight — only updates when needed)
    try:
        store    = get_project_store()
        projects = store.load_projects()
        if projects:
            get_monitor().sync_projects(projects)
    except Exception:
        pass

    page = st.session_state.page
    if page == "📊 Dashboard":
        render_dashboard()
    elif page == "🔌 Projects":
        render_projects()
    elif page == "📄 Document Analysis":
        render_document_analysis(provider, api_key, model)
    elif page == "⚙️ Settings":
        render_settings()


if __name__ == "__main__":
    main()
