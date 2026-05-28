"""
DocumentAnalyzer — auto-analyzes uploaded documents to identify type,
extract key findings, generate a summary, and suggest relevant questions.

Flow:
  1. Sample raw text from the vector store (no embedding needed).
  2. Heuristic type detection via regex — fast, no LLM cost.
  3. For LOG_FILE: extract error/warn/fatal counts and top error messages.
  4. LLM call for: summary, key findings, suggested questions.
  5. Parse structured response into AnalysisResult.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm import LLMClient
    from src.vector_store import VectorStore

log = logging.getLogger(__name__)

# ── Document type registry ─────────────────────────────────────────────────
# Maps internal key → (human label, icon)
DOC_TYPES: dict[str, tuple[str, str]] = {
    "LOG_FILE":        ("Log File",            "🖥️"),
    "CSV_DATA":        ("Data / Spreadsheet",  "📊"),
    "BUSINESS_REPORT": ("Business Report",     "📈"),
    "LEGAL_CONTRACT":  ("Legal Contract",      "⚖️"),
    "TECHNICAL_DOC":   ("Technical Document",  "⚙️"),
    "FINANCIAL":       ("Financial Document",  "💰"),
    "GENERAL":         ("Document",            "📄"),
}

# ── Prompt template ────────────────────────────────────────────────────────
_PROMPT = """\
You are a document analysis expert. Analyze the document sample below and respond \
EXACTLY in the structured format shown. No extra text before or after.

TYPE: [choose exactly one: LOG_FILE, CSV_DATA, BUSINESS_REPORT, LEGAL_CONTRACT, TECHNICAL_DOC, FINANCIAL, GENERAL]
SUMMARY: [2-3 sentences — what is this document, its purpose, and the most important content]
FINDINGS:
- [key finding or notable observation 1]
- [key finding or notable observation 2]
- [key finding or notable observation 3]
- [key finding or notable observation 4]
- [key finding or notable observation 5]
QUESTIONS:
- [highly relevant question a user of this document would want answered]
- [another specific, useful question]
- [another specific, useful question]
- [another specific, useful question]
- [another specific, useful question]
- [another specific, useful question]

File name: {file_name}
Detected type hint: {type_hint}
Document sample:
---
{sample}
---"""

_SAMPLE_CHARS = 8000   # max chars of document text sent to LLM for analysis


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class LogStats:
    """Regex-extracted stats from log files — no LLM needed."""
    error_count: int = 0
    warn_count: int = 0
    info_count: int = 0
    fatal_count: int = 0
    debug_count: int = 0
    has_stack_traces: bool = False
    top_errors: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Full analysis result returned by DocumentAnalyzer.analyze()."""
    doc_type: str           # internal key, e.g. "LOG_FILE"
    type_label: str         # human label, e.g. "Log File"
    type_icon: str          # emoji, e.g. "🖥️"
    summary: str
    key_findings: list[str]
    suggested_questions: list[str]
    log_stats: LogStats | None = None   # only populated for LOG_FILE


# ── Analyzer ───────────────────────────────────────────────────────────────

class DocumentAnalyzer:
    """
    Analyzes a document that has already been ingested into a VectorStore.
    Samples chunks directly (no embedding query), detects document type,
    then calls the LLM for summary, findings, and suggested questions.
    """

    def analyze(
        self,
        file_name: str,
        vector_store: "VectorStore",
        llm_client: "LLMClient",
    ) -> AnalysisResult:
        """Run full document analysis. Returns AnalysisResult."""
        # 1. Sample raw text from the store
        chunks = vector_store.get_sample(n=40)
        sample = "\n\n".join(c["text"] for c in chunks)[:_SAMPLE_CHARS]

        if not sample.strip():
            return self._fallback(file_name, "GENERAL")

        # 2. Heuristic type detection (no LLM)
        type_hint = self._detect_type(file_name, sample)

        # 3. Log-specific regex stats
        log_stats = self._extract_log_stats(sample) if type_hint == "LOG_FILE" else None

        # 4. LLM analysis
        try:
            result = self._llm_analysis(file_name, type_hint, sample, llm_client)
        except Exception as e:
            log.warning(f"[Analyzer] LLM call failed ({e}), using fallback.")
            result = self._fallback(file_name, type_hint)

        result.log_stats = log_stats
        return result

    # ── Heuristic type detection ───────────────────────────────────────────

    def _detect_type(self, file_name: str, sample: str) -> str:
        name = file_name.lower()

        # Extension fast-path
        if name.endswith(".csv"):
            return "CSV_DATA"
        if name.endswith(".log"):
            return "LOG_FILE"

        # Content scoring
        if self._is_log(sample):
            return "LOG_FILE"

        sl = sample.lower()

        if sum([
            bool(re.search(r'\b(whereas|pursuant|indemnif|liabilit|herein|covenant)\b', sl)),
            bool(re.search(r'\b(agreement|contract|shall|obligations?|party|parties)\b', sl)),
            bool(re.search(r'\b(terms and conditions|governing law|arbitration|clause)\b', sl)),
        ]) >= 2:
            return "LEGAL_CONTRACT"

        if sum([
            bool(re.search(r'\$[\d,]+|\bUSD\b|\bEUR\b|\bGBP\b', sample)),
            bool(re.search(r'\b(revenue|profit|loss|ebitda|balance sheet|income statement)\b', sl)),
            bool(re.search(r'\b(fiscal|quarter|annual report|financial results)\b', sl)),
        ]) >= 2:
            return "FINANCIAL"

        if sum([
            bool(re.search(r'\b(api|endpoint|function|class|method|parameter|config)\b', sl)),
            bool(re.search(r'```|def |class |import |#include|SELECT |FROM ', sample)),
            bool(re.search(r'\b(installation|requirements?|dependencies|version|release)\b', sl)),
        ]) >= 2:
            return "TECHNICAL_DOC"

        if sum([
            bool(re.search(r'\b(executive summary|findings?|recommendations?|conclusion)\b', sl)),
            bool(re.search(r'\b(analysis|survey|research|study|report)\b', sl)),
        ]) >= 2:
            return "BUSINESS_REPORT"

        return "GENERAL"

    def _is_log(self, text: str) -> bool:
        score = sum([
            bool(re.search(r'\b(ERROR|WARN|INFO|DEBUG|FATAL|CRITICAL|SEVERE)\b', text)),
            bool(re.search(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', text)),
            bool(re.search(r'\[ERROR\]|\[WARN\]|\[INFO\]|\[DEBUG\]|\[FATAL\]', text)),
            bool(re.search(r'(Exception|Traceback|NullPointerException|at com\.|at org\.)', text)),
            bool(re.search(r'\d{2}:\d{2}:\d{2}[.,]\d{3}', text)),   # ms-precision timestamps
        ])
        return score >= 2

    # ── Log statistics ─────────────────────────────────────────────────────

    def _extract_log_stats(self, text: str) -> LogStats:
        stats = LogStats(
            error_count=len(re.findall(r'\bERROR\b|\[ERROR\]', text)),
            warn_count=len(re.findall(r'\bWARN(?:ING)?\b|\[WARN\]', text)),
            info_count=len(re.findall(r'\bINFO\b|\[INFO\]', text)),
            fatal_count=len(re.findall(r'\bFATAL\b|\bCRITICAL\b|\bSEVERE\b|\[FATAL\]', text)),
            debug_count=len(re.findall(r'\bDEBUG\b|\[DEBUG\]', text)),
            has_stack_traces=bool(re.search(
                r'(Traceback \(most recent|Exception in thread|at com\.|'
                r'at org\.|Caused by:|NullPointerException|\.printStackTrace)',
                text,
            )),
        )

        # Unique error messages — strip timestamps, keep first 5
        error_lines = re.findall(r'(?:ERROR|FATAL|CRITICAL)[^\n]{0,200}', text)
        seen: set[str] = set()
        top: list[str] = []
        for line in error_lines:
            clean = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.,\d]*\s*', '', line)
            clean = clean.strip()[:120]
            if clean and clean not in seen:
                seen.add(clean)
                top.append(clean)
            if len(top) >= 5:
                break
        stats.top_errors = top

        return stats

    # ── LLM analysis ───────────────────────────────────────────────────────

    def _llm_analysis(
        self,
        file_name: str,
        type_hint: str,
        sample: str,
        llm_client: "LLMClient",
    ) -> AnalysisResult:
        prompt = _PROMPT.format(
            file_name=file_name,
            type_hint=type_hint,
            sample=sample,
        )
        raw = llm_client.complete(prompt)
        return self._parse(raw, type_hint)

    # ── Response parser ────────────────────────────────────────────────────

    def _parse(self, raw: str, fallback_type: str) -> AnalysisResult:
        doc_type = fallback_type

        m = re.search(r'^TYPE:\s*(\S+)', raw, re.MULTILINE)
        if m and m.group(1).upper() in DOC_TYPES:
            doc_type = m.group(1).upper()

        summary = ""
        m = re.search(r'^SUMMARY:\s*(.+?)(?=\nFINDINGS:|\nQUESTIONS:|$)', raw, re.MULTILINE | re.DOTALL)
        if m:
            summary = m.group(1).strip()

        findings: list[str] = []
        m = re.search(r'FINDINGS:\s*\n(.*?)(?=\nQUESTIONS:|$)', raw, re.DOTALL)
        if m:
            findings = _parse_bullets(m.group(1))

        questions: list[str] = []
        m = re.search(r'QUESTIONS:\s*\n(.+?)$', raw, re.DOTALL)
        if m:
            questions = _parse_bullets(m.group(1))

        label, icon = DOC_TYPES.get(doc_type, ("Document", "📄"))
        return AnalysisResult(
            doc_type=doc_type,
            type_label=label,
            type_icon=icon,
            summary=summary or "Document analyzed and ready for questions.",
            key_findings=findings[:6],
            suggested_questions=questions[:6],
        )

    # ── Fallback ───────────────────────────────────────────────────────────

    def _fallback(self, file_name: str, type_hint: str) -> AnalysisResult:
        label, icon = DOC_TYPES.get(type_hint, ("Document", "📄"))
        return AnalysisResult(
            doc_type=type_hint,
            type_label=label,
            type_icon=icon,
            summary=f"'{file_name}' has been indexed and is ready for questions.",
            key_findings=["Document parsed and embedded successfully."],
            suggested_questions=[
                "What is the main topic of this document?",
                "Can you summarize the key points?",
                "What are the most important findings or conclusions?",
                "Are there any action items or recommendations?",
                "What data or evidence is presented?",
            ],
        )


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_bullets(text: str) -> list[str]:
    """Extract bullet lines from a block of text."""
    return [
        line.lstrip("-•* \t").strip()
        for line in text.splitlines()
        if line.strip() and line.strip()[0] in ("-", "•", "*")
        and len(line.lstrip("-•* \t").strip()) > 2
    ]
