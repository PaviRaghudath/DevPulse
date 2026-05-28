"""
AlertEngine — analyzes fetched log content and sends HTML email alerts.

Uses DocumentAnalyzer._extract_log_stats() for fast regex-based error detection
(no LLM API call needed for the core alert path — cost-free).

Email is sent via built-in smtplib with STARTTLS.
Works with Gmail app-passwords, AWS SES SMTP, SendGrid, or any standard SMTP server.
"""
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.analyzer import DocumentAnalyzer
from src.project_config import AlertRecord, EmailConfig, ProjectConfig

log = logging.getLogger(__name__)


class AlertEngine:
    """Analyze log content, build alert records, and dispatch email notifications."""

    def __init__(self):
        self._analyzer = DocumentAnalyzer()

    # ── Analysis ───────────────────────────────────────────────────────────

    def analyze_content(
        self,
        project: ProjectConfig,
        log_path: str,
        content: str,
        llm_client=None,     # optional — used for richer summaries when available
    ) -> Optional[AlertRecord]:
        """
        Analyze fetched log content.
        Returns an AlertRecord if errors exceed project.error_threshold, else None.
        No LLM call is made unless llm_client is passed and errors are found.
        """
        if not content.strip():
            return None

        stats = self._analyzer._extract_log_stats(content)
        total_errors = stats.error_count + stats.fatal_count

        # Check threshold
        if total_errors <= project.error_threshold and not stats.has_stack_traces:
            return None

        summary = self._build_summary(
            project.name, log_path, stats, content, llm_client
        )

        return AlertRecord(
            project_id=project.id,
            project_name=project.name,
            log_file=log_path,
            error_count=total_errors,
            warn_count=stats.warn_count,
            top_errors=stats.top_errors,
            has_stack_traces=stats.has_stack_traces,
            summary=summary,
            lines_analyzed=content.count("\n"),
        )

    def _build_summary(self, project_name, log_path, stats, content, llm_client) -> str:
        parts = [
            f"{stats.error_count + stats.fatal_count} error(s) detected in {log_path.split('/')[-1]}.",
            f"Warnings: {stats.warn_count}.",
        ]
        if stats.has_stack_traces:
            parts.append("Stack traces present.")
        if stats.top_errors:
            parts.append("Top error: " + stats.top_errors[0][:120])

        # If LLM is available, get a richer one-line summary
        if llm_client and (stats.error_count + stats.fatal_count) > 0:
            try:
                snippet = content[-3000:]   # last 3K chars — most relevant
                brief = llm_client.complete(
                    f"In one sentence, summarize the main problem in this log snippet:\n\n{snippet}"
                )
                if brief:
                    parts.append(f"AI summary: {brief.strip()}")
            except Exception:
                pass

        return " ".join(parts)

    # ── Email ──────────────────────────────────────────────────────────────

    def send_alert_email(
        self,
        alert: AlertRecord,
        email_cfg: EmailConfig,
        recipients: list[str],
    ) -> bool:
        """
        Send an HTML alert email to `recipients`.
        Returns True if sent successfully.
        """
        if not email_cfg.enabled or not email_cfg.username:
            log.info("[AlertEngine] Email disabled / not configured — skipping.")
            return False
        if not recipients:
            log.info("[AlertEngine] No recipients — skipping.")
            return False

        try:
            msg = self._build_message(alert, email_cfg, recipients)
            self._smtp_send(msg, email_cfg)
            alert.email_sent = True
            log.info(f"[AlertEngine] Alert email sent → {recipients}")
            return True
        except Exception as e:
            log.error(f"[AlertEngine] Email send failed: {e}")
            return False

    def send_test_email(self, email_cfg: EmailConfig, recipient: str) -> tuple[bool, str]:
        """Send a test email to verify SMTP settings. Returns (ok, error_msg)."""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "[FileAnalyzer] Test email — SMTP connection OK"
            msg["From"]    = email_cfg.from_address or email_cfg.username
            msg["To"]      = recipient
            msg.attach(MIMEText(
                "<h2 style='font-family:Arial;'>✅ FileAnalyzer email is working!</h2>"
                "<p style='font-family:Arial;color:#64748B;'>Your SMTP settings are correct. "
                "Alert emails will be delivered to this address.</p>",
                "html",
            ))
            self._smtp_send(msg, email_cfg)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── Email building ─────────────────────────────────────────────────────

    def _build_message(
        self,
        alert: AlertRecord,
        cfg: EmailConfig,
        recipients: list[str],
    ) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"[FileAnalyzer Alert] {alert.project_name} — "
            f"{alert.error_count} ERROR(s) in {alert.log_file.split('/')[-1]}"
        )
        msg["From"] = cfg.from_address or cfg.username
        msg["To"]   = ", ".join(recipients)
        msg.attach(MIMEText(self._html_body(alert), "html"))
        return msg

    def _html_body(self, a: AlertRecord) -> str:
        ts = a.timestamp[:19].replace("T", " ") + " UTC"
        error_rows = "".join(
            f"<tr><td style='padding:6px 12px;font-family:monospace;font-size:12px;"
            f"color:#FCA5A5;border-bottom:1px solid #1E293B;'>{e}</td></tr>"
            for e in (a.top_errors or ["(no specific message extracted)"])
        )
        stack_badge = (
            "<span style='display:inline-block;background:#7F1D1D;color:#FCA5A5;"
            "padding:2px 10px;border-radius:4px;font-size:11px;margin-bottom:12px;'>"
            "⚠️ Stack traces detected</span>"
        ) if a.has_stack_traces else ""

        return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:20px;background:#0F172A;font-family:Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;background:#1E293B;border-radius:12px;overflow:hidden;">

  <div style="background:#DC2626;padding:22px 28px;">
    <h2 style="margin:0;color:#fff;font-size:20px;">🚨 FileAnalyzer Alert</h2>
    <p style="margin:4px 0 0;color:#FEE2E2;font-size:13px;">{ts}</p>
  </div>

  <div style="padding:24px 28px;">
    <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
      <tr><td style="color:#94A3B8;padding:5px 0;width:140px;font-size:13px;">Project</td>
          <td style="color:#F1F5F9;font-weight:600;font-size:14px;">{a.project_name}</td></tr>
      <tr><td style="color:#94A3B8;padding:5px 0;font-size:13px;">Log file</td>
          <td style="color:#F1F5F9;font-size:13px;">{a.log_file}</td></tr>
      <tr><td style="color:#94A3B8;padding:5px 0;font-size:13px;">Errors</td>
          <td style="color:#F87171;font-weight:700;font-size:22px;">{a.error_count}</td></tr>
      <tr><td style="color:#94A3B8;padding:5px 0;font-size:13px;">Warnings</td>
          <td style="color:#FCD34D;font-weight:600;font-size:15px;">{a.warn_count}</td></tr>
      <tr><td style="color:#94A3B8;padding:5px 0;font-size:13px;">Lines scanned</td>
          <td style="color:#F1F5F9;font-size:13px;">{a.lines_analyzed:,}</td></tr>
    </table>

    {stack_badge}

    <h3 style="color:#E2E8F0;font-size:13px;margin:0 0 8px;text-transform:uppercase;
               letter-spacing:0.05em;">Top Error Messages</h3>
    <table style="width:100%;background:#0F172A;border-radius:8px;border-collapse:collapse;
                  margin-bottom:16px;">
      {error_rows}
    </table>

    <p style="color:#CBD5E1;font-size:13px;line-height:1.7;margin:0;">{a.summary}</p>
  </div>

  <div style="padding:14px 28px;background:#0F172A;border-top:1px solid #1E3A5F;">
    <p style="color:#475569;font-size:11px;margin:0;text-align:center;">
      FileAnalyzer Monitoring Agent &nbsp;|&nbsp; automated alert &nbsp;|&nbsp;
      alert id: {a.id}
    </p>
  </div>
</div>
</body></html>"""

    def _smtp_send(self, msg: MIMEMultipart, cfg: EmailConfig) -> None:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(cfg.username, cfg.password)
            server.send_message(msg)
