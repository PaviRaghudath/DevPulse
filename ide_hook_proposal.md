# FileAnalyzer — IDE Hook Integration Proposal

**Prepared for:** Manager Review
**Date:** 2026-05-27
**Feature:** Direct IDE Integration via REST API

---

## 1. What We Are Building

Currently, FileAnalyzer is a standalone web application. To analyze a log file or document, you open it in a browser and upload the file manually.

This proposal adds a **background service layer** to FileAnalyzer so that your development tools — VS Code, IntelliJ IDEA, Visual Studio — can connect to it directly. Developers no longer need to leave their IDE to get log analysis or document answers.

---

## 2. The Problem Today

| Situation | Current Workflow | Pain Point |
|---|---|---|
| App throws an error, developer wants to analyze the log | Open browser → go to FileAnalyzer → upload log → read results | Context switch, slow |
| Developer wants to ask a question about a design document | Open browser → upload file → type question | Repetitive manual steps |
| Error log alert comes in from a monitored Spring Boot server | Email arrives → open FileAnalyzer to see details | Can't stay in IDE |

---

## 3. What Changes

We add one new component: a **REST API server** that runs on the developer's machine alongside FileAnalyzer.

```
Before:
  Developer  -->  Browser  -->  FileAnalyzer (Streamlit UI)

After:
  Developer  -->  IDE Plugin  -->  FileAnalyzer API (localhost)  -->  FileAnalyzer Engine
             -->  Browser     -->  FileAnalyzer (Streamlit UI) [still works as before]
```

The existing Streamlit web UI continues to work unchanged. The new API layer is an addition, not a replacement.

---

## 4. How It Works for the Developer

### Log Analysis from the IDE
1. An error appears in the IDE terminal or a log file opens in the editor
2. Developer right-clicks → "Analyze with FileAnalyzer" (or uses a keyboard shortcut)
3. The plugin sends the file to the local FileAnalyzer API
4. Within seconds, a panel shows:
   - Error count, warning count
   - Top error messages
   - Stack trace summary
   - Suggested next steps

### Document Q&A from the IDE
1. Developer opens a PDF spec, Word doc, or any supported file in the IDE
2. Invokes FileAnalyzer from the command palette
3. Types a question — "What are the API endpoints?" or "What are the deployment requirements?"
4. Gets an AI-generated answer based on the document content, displayed inline

---

## 5. Which IDEs Are Supported

| IDE | Plugin Language | Status |
|---|---|---|
| VS Code | TypeScript / JavaScript | Plugin stub provided (ready to package) |
| IntelliJ IDEA / WebStorm | Kotlin / Java | Plugin stub provided (ready to package) |
| Visual Studio (Windows) | C# / .NET | Plugin stub provided (ready to package) |

All three IDEs connect to the same FileAnalyzer API using standard HTTP — no special integration per IDE is needed on the server side.

---

## 6. Technical Summary (Non-Technical Overview)

- **No new AI models** needed — uses the same AI engine already in FileAnalyzer
- **No cloud dependency** — runs entirely on the developer's local machine (localhost)
- **No data leaves the machine** — all analysis is local, same as today
- **No changes to existing projects** — connects to any log file or document the IDE has open
- **3 new Python packages** needed: `fastapi`, `uvicorn`, `python-multipart` (all free, open source)
- **1 new file** to implement the API (`src/api.py`, ~220 lines)
- **1 startup script** (`api_server.py`) that developers run once in the background

---

## 7. What the IDE Plugin Stub Looks Like

Below is a minimal example for VS Code (TypeScript). This is the code a developer would put in a VS Code extension:

```typescript
// Send the currently open file to FileAnalyzer and show results
const formData = new FormData();
formData.append('file', fileContent, fileName);

const response = await fetch('http://localhost:8000/analyze', {
  method: 'POST',
  body: formData
});

const analysis = await response.json();
// Display: analysis.summary, analysis.log_stats, analysis.suggested_questions
```

Similar 10-line stubs exist for IntelliJ (Kotlin) and Visual Studio (C#). These are starting points — a developer familiar with extension development can build a full plugin from these.

---

## 8. API Endpoints

| Endpoint | What It Does |
|---|---|
| `GET /health` | Check if FileAnalyzer is running |
| `POST /analyze` | Upload a file → get type detection, summary, error counts, suggested questions |
| `POST /ask` | Upload a file + question → get AI answer |
| `GET /projects` | List monitored Spring Boot / React projects |
| `POST /projects/{id}/check` | Trigger an immediate log check for a project |
| `GET /projects/{id}/alerts` | View recent alerts for a project |

A built-in API documentation page (`http://localhost:8000/docs`) is auto-generated — developers can explore and test every endpoint from a browser.

---

## 9. Implementation Scope

| Item | Effort |
|---|---|
| `src/api.py` — FastAPI application with all endpoints | Medium (1 session) |
| `api_server.py` — startup script | Trivial |
| `requirements.txt` — 3 new packages | Trivial |
| `README.md` — IDE hook documentation | Small |
| VS Code / IntelliJ / Visual Studio plugin stubs | Small (documentation-level stubs) |

**No changes** to existing pipeline, analyzer, monitor, deployer, or Streamlit UI.

---

## 10. Benefits Summary

- Developers stay in their IDE — no browser context switch for log analysis
- Faster feedback loop when debugging errors on monitored servers
- Document Q&A available directly inside the development environment
- One FileAnalyzer instance serves all IDEs simultaneously
- Minimal implementation risk — all AI logic already exists and is tested

---

## Approval Request

This document describes a non-breaking enhancement to the existing FileAnalyzer system. It adds an API layer that exposes existing capabilities to IDE plugins without modifying any current functionality.

**Requesting approval to proceed with implementation.**
