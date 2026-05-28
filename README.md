# FileAnalyzer

A local RAG (Retrieval-Augmented Generation) agent with a web UI that lets you upload documents and ask questions about them using OpenAI (ChatGPT) or Anthropic (Claude). Supports files from 1 KB to 500 MB.

## Overview

FileAnalyzer processes your documents locally — parsing, chunking, and embedding them into a persistent vector store — then uses your chosen AI provider to stream answers based on the most relevant content retrieved from the document.

**Supported file types:** PDF, DOCX, TXT, CSV
**AI providers:** OpenAI (gpt-4o, gpt-4o-mini, gpt-4-turbo) · Anthropic (claude-sonnet-4-6, claude-opus-4-6, claude-haiku)

---

## Architecture

```
File (PDF/DOCX/TXT/CSV)
  │
  ▼
Parser (streaming generator — never loads full file into memory)
  │  pdf_parser   → page-by-page via pypdf
  │  docx_parser  → paragraph batches via python-docx
  │  txt_parser   → 64KB blocks with paragraph splitting
  │  csv_parser   → pandas chunksize=10,000 rows
  │
  ▼
DocumentChunker
  │  512-char overlapping windows (64-char overlap)
  │  Cross-segment carry buffer preserves context at boundaries
  │
  ▼
EmbeddingEngine  (sentence-transformers: all-MiniLM-L6-v2, local, free)
  │  Batched encoding · 200-chunk flush cycle → ChromaDB → gc.collect()
  │
  ▼
VectorStore  (ChromaDB, persistent to data/vector_store/)
  │  One collection per document (named after file stem)
  │
  ▼ (at query time)
  │
  ├── User Question (typed in chat UI)
  │     │
  │     ▼
  │   EmbeddingEngine.embed_query()
  │     │
  │     ▼
  │   VectorStore.search() → top-6 most similar chunks
  │     │
  │     ▼
  │   Retriever.build_context() → concatenated excerpts (≤12,000 chars)
  │     │
  │     ▼
  │   LLMClient.ask_stream()
  │     ├── OpenAI provider  → streams via openai SDK
  │     └── Anthropic provider → streams via anthropic SDK
  │
  └── Answer streamed token-by-token to chat UI
```

---

## Project Structure

```
FileAnalyzer/
├── README.md                  # This file — always kept up to date
├── CLAUDE.md                  # Dev rules (update README on every change)
├── aswdeployment.md           # Step-by-step EC2 deploy guide (FileZilla + SSH)
├── app.py                     # Streamlit web UI entry point
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
├── .gitignore
│
├── src/
│   ├── __init__.py
│   ├── main.py                # (Optional) Click CLI: load, ask, chat, list, clear
│   ├── config.py              # All tunable constants + provider/model lists
│   ├── exceptions.py          # Custom exception hierarchy
│   ├── pipeline.py            # IngestionPipeline — orchestrates parse→chunk→embed→store
│   ├── chunker.py             # DocumentChunker — overlapping text windows
│   ├── embeddings.py          # EmbeddingEngine — sentence-transformers wrapper
│   ├── vector_store.py        # VectorStore — ChromaDB wrapper
│   ├── retriever.py           # Retriever — query embedding + similarity search
│   ├── llm.py                 # LLMClient — unified OpenAI + Anthropic streaming
│   ├── analyzer.py            # DocumentAnalyzer — type detection, log stats, auto-analysis
│   ├── project_config.py      # ProjectConfig, EmailConfig, AlertRecord + JSON store
│   ├── log_fetcher.py         # SSH/SFTP incremental log fetching (paramiko)
│   ├── alert_engine.py        # Error detection + HTML email alerts (smtplib)
│   ├── monitor.py             # MonitorScheduler (APScheduler) + run_check orchestrator
│   ├── git_connector.py       # GitHub/GitLab API — project type + CI/CD detection (no git needed)
│   ├── deployer.py            # CI/CD trigger (GitHub Actions/Jenkins/GitLab) + SSH build+deploy
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── base_parser.py     # Abstract BaseParser interface
│   │   ├── pdf_parser.py      # PDF: pypdf page-by-page streaming
│   │   ├── docx_parser.py     # DOCX: python-docx paragraph batches + tables
│   │   ├── txt_parser.py      # TXT: 64KB block streaming
│   │   └── csv_parser.py      # CSV: pandas chunked streaming
│   │
│   └── utils/
│       ├── __init__.py
│       ├── file_utils.py      # File validation, type detection, collection naming
│       ├── memory.py          # psutil memory monitoring + gc helpers
│       └── progress.py        # Rich progress bars and spinners (CLI)
│
└── data/
    └── vector_store/          # ChromaDB persistent storage (auto-created at runtime)
```

---

## Setup

### Requirements
- Python 3.10+
- An API key from **OpenAI** or **Anthropic** (or both)

### Install

```bash
pip install -r requirements.txt
```

> The first run downloads the `all-MiniLM-L6-v2` embedding model (~80 MB), cached automatically.

### Configure (optional)

```bash
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and/or ANTHROPIC_API_KEY
# You can also enter the key directly in the UI sidebar
```

---

## Running the Web UI

```bash
streamlit run app.py
```

Opens at **http://localhost:8501** in your browser.

### UI Workflow

```
┌──────────────────────┬──────────────────────────────────────────────────┐
│ SIDEBAR (light)      │ MAIN AREA                                        │
│                      │                                                  │
│ 🔍 FileAnalyzer      │  🔍 FileAnalyzer                                 │
│                      │  Upload a document, then ask anything about it   │
│ AI Provider          │                                                  │
│ ○ OpenAI (ChatGPT)   │  ┌──────────────────────────────────────────┐   │
│ ● Anthropic (Claude) │  │  Drop your file here or click to browse  │   │
│                      │  │  PDF · DOCX · TXT · CSV                  │   │
│ API Key: [••••••••]  │  └──────────────────────────────────────────┘   │
│ Model:  [gpt-4o ▼]   │                                                  │
│                      │  [ 🚀 Analyze Document ]                         │
│ ─────────────────    │                                                  │
│                      │  ── After upload ──────────────────────────────  │
│ 📄 Loaded Document   │                                                  │
│ report.pdf           │  🔍 Analyzing your document...                   │
│ 1,847 chunks         │    📂 Reading file...                            │
│                      │    🔬 Parsing, chunking & embedding...           │
│ [Chat][New][🗑️ Del]  │    ⚙️  1,847 chunks processed                   │
│                      │    ✅ Document ready                             │
│ 📚 Previous Docs     │                                                  │
│ annual_report   [✕]  │  ── After indexing ─────────────────────────── │
│ data_export     [✕]  │                                                  │
│                      │  🧑 What are the main findings?                 │
│                      │  🤖 Based on the document, the main...          │
│                      │     [streaming token by token]                   │
│                      │                                                  │
│                      │  📎 6 source excerpts used  ▼                   │
│                      │                                                  │
│                      │  [ Ask a question about your document... ]       │
└──────────────────────┴──────────────────────────────────────────────────┘
```

**Key UI features:**
- Light-themed sidebar with clean contrast against the main area
- Drag-and-drop file upload with file size display
- Real-time chunk progress counter during analysis
- Streaming AI answers (tokens appear as they're generated)
- Source excerpts shown per answer (collapsible)
- **Delete (✕)** button next to each document in the sidebar removes its index from ChromaDB
- **Del** button on the current document also unloads it from the session
- Previously indexed documents listed in sidebar for instant reload
- Clear chat / load new file without losing the index

---

## Monitoring Agent — Hook to Java Spring Boot Projects

FileAnalyzer acts as a monitoring sidecar to any number of remote servers.
It connects via SSH, pulls logs incrementally, detects errors, and alerts you by email.

### Architecture

```
4× Spring Boot / Apache servers on AWS EC2
        │  SSH/SFTP (paramiko)
        ▼
  LogFetcher  ──── byte-offset tracking (only new content per run)
        │
        ▼
  AlertEngine ──── DocumentAnalyzer.log_stats() — regex, no LLM cost
        │               ERROR / WARN / FATAL counts
        │               Stack trace detection
        │               Top 5 unique error messages
        ▼
  EmailConfig ──── smtplib STARTTLS (Gmail, AWS SES, SendGrid, any SMTP)
        │               HTML email with error table + summary
        ▼
  ProjectStore ─── data/alert_history.json  (last 500 alerts)
  MonitorScheduler  APScheduler BackgroundScheduler
                    one job per project, configurable interval (default 15 min)
```

### Setup (4 Spring Boot projects)

1. Go to **🔌 Projects** page → **Add Project** for each server:
   - Name, host IP, SSH username (`ec2-user`)
   - Auth: **key** → paste path to `.pem` file, or **password**
   - Log file paths (e.g. `/var/log/app/app.log`, `/opt/tomcat/logs/catalina.out`)
   - Check interval (minutes), error threshold, notify emails

2. Click **🔗 Test SSH** to verify connectivity before saving.

3. Go to **⚙️ Settings** → configure SMTP → send a test email.

4. The scheduler starts automatically. Each project is checked on its own interval.

### Data files

| File | Contents |
|---|---|
| `data/projects.json` | Project configs + email settings |
| `data/alert_history.json` | Alert records (last 500) |
| `data/log_positions.json` | Byte offsets for incremental log reads |

### Supported log formats

Any text-based log — Spring Boot default (`logback`), Apache `access_log` / `error_log`,
Tomcat `catalina.out`, custom log4j/log4j2 patterns. No configuration required.

### Git Integration & Deployment

Each project has a **Git & Deploy** tab in the project form. The flow:

```
1. Add project → Git & Deploy tab → paste git URL + branch + token
2. Click [Detect] → GitConnector reads repo via API (no git clone needed)
3. Auto-detected and saved:
      project_type  spring_boot_jar | spring_boot_war | react | angular | jsp_war | ...
      build_tool    maven | gradle | npm | yarn
      build_command mvn clean package -DskipTests  (editable)
      cicd_type     github_actions | jenkins | gitlab_ci | none
      cicd_files    .github/workflows/deploy.yml  (auto-selected)

4. Click [Deploy]:
      IF cicd detected  → trigger pipeline via API → shows pipeline URL
      IF no cicd        → SSH: git pull → build on server → restart service
```

#### Supported project types

| Type | Build | Deploy |
|---|---|---|
| Spring Boot JAR | `mvn / gradlew clean build` | systemd service restart |
| Spring Boot WAR | `mvn clean package` | copy to Tomcat webapps/ |
| JSP / Servlet WAR | `mvn clean package` | copy to Tomcat webapps/ |
| React / Vue | `npm run build` | rsync build/ to web root |
| Angular | `ng build --configuration=production` | rsync dist/ to web root |
| Next.js | `npm run build` | pm2 / systemd restart |

#### CI/CD pipeline trigger

| Provider | Method |
|---|---|
| GitHub Actions | `POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches` |
| Jenkins | `POST /job/{job}/build` with Basic auth |
| GitLab CI | `POST /projects/{id}/pipeline` with PRIVATE-TOKEN |

### Future: Auto-fix & Redeploy (Phase 2)

The `deploy_path` and `restart_cmd` fields on each project are already stored.
Phase 2 will add:
- LLM-based root cause analysis on error context
- Known-fix pattern matching (e.g. OOM → increase heap, DB connection timeout → pool config)
- SSH-based patch deployment + service restart
- Rollback on repeated errors after fix

---

## Document Intelligence (Auto-Analysis)

After every upload, FileAnalyzer automatically runs a two-stage analysis before you ask a single question:

**Stage 1 — Heuristic type detection (no LLM, instant)**

| Document type | Signals |
|---|---|
| Log File | `ERROR`/`WARN`/`INFO` keywords, ms-precision timestamps, stack traces |
| CSV / Data | `.csv` extension |
| Legal Contract | whereas, pursuant, indemnify, arbitration clauses |
| Financial | revenue, profit, balance sheet, fiscal quarter |
| Technical Doc | API, def, class, import, code fences, version/release |
| Business Report | executive summary, findings, recommendations |

**Stage 2 — LLM analysis (sampled from first 40 chunks)**
- 2–3 sentence document summary
- Up to 6 key findings extracted from the content
- Up to 6 suggested questions tailored to the document type

**Log file extras (regex, no LLM cost)**
- ERROR / WARN / FATAL / INFO / DEBUG counts
- Stack trace detection flag
- Top 5 unique error messages shown in the UI

Results appear as a panel above the chat on first load. Clicking a suggested question sends it to the AI instantly.

---

## AI Providers

### OpenAI (ChatGPT)

| Model | Speed | Quality | Cost |
|---|---|---|---|
| `gpt-4o` | Fast | Best | ~$0.005/1K tokens |
| `gpt-4o-mini` | Very fast | Good | ~$0.00015/1K tokens |
| `gpt-4-turbo` | Moderate | Excellent | ~$0.01/1K tokens |

Get an API key: https://platform.openai.com

### Anthropic (Claude)

| Model | Speed | Quality | Cost |
|---|---|---|---|
| `claude-sonnet-4-6` | Fast | Excellent | ~$0.003/1K tokens |
| `claude-opus-4-6` | Slower | Best | ~$0.015/1K tokens |
| `claude-haiku-4-5` | Very fast | Good | ~$0.00025/1K tokens |

Get an API key: https://console.anthropic.com

---

## Configuration

All constants are in `src/config.py`. Override via `.env`:

| Constant | Default | Env var | Description |
|---|---|---|---|
| `CHUNK_SIZE` | `512` | `CHUNK_SIZE` | Max characters per chunk |
| `CHUNK_OVERLAP` | `64` | `CHUNK_OVERLAP` | Overlap chars between adjacent chunks |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | `EMBEDDING_MODEL` | sentence-transformers model |
| `EMBEDDING_BATCH_SIZE` | `64` | — | Texts per embedding batch |
| `EMBED_BUFFER_SIZE` | `200` | — | Chunks buffered before ChromaDB flush |
| `TOP_K_RETRIEVAL` | `6` | `TOP_K_RETRIEVAL` | Chunks retrieved per query |
| `MAX_CONTEXT_CHARS` | `12000` | — | Max characters sent to AI |
| `LLM_MAX_TOKENS` | `1024` | — | Max tokens in AI response |
| `MAX_FILE_SIZE_MB` | `500` | — | Maximum input file size |
| `CSV_READ_CHUNK_ROWS` | `10000` | — | Rows per pandas CSV chunk |
| `TXT_STREAM_BYTES` | `65536` | — | Read buffer size for TXT files |
| `MEMORY_WARN_MB` | `1500` | — | RAM usage warning threshold |
| `VECTOR_STORE_PATH` | `data/vector_store` | — | ChromaDB persistence directory |

---

## AWS Deployment

### Option A — EC2 (Recommended: simple, persistent, ~$30/month)

Best for personal use or small teams. The embedding model and ChromaDB run directly on the instance.

**1. Launch an EC2 instance**

| Setting | Value |
|---|---|
| AMI | Ubuntu Server 22.04 LTS |
| Instance type | `t3.medium` (2 vCPU, 4 GB RAM) minimum |
| Storage | 20 GB EBS (gp3) |
| Security Group | TCP 80 open · TCP 22 restricted to your IP |

**2. Run the setup script on the instance**

```bash
# On your local machine — copy the project
scp -r E:/mkonnekt/FileAnalyzer ubuntu@<EC2_PUBLIC_IP>:/opt/fileanalyzer

# SSH into the instance
ssh ubuntu@<EC2_PUBLIC_IP>

# Run setup
chmod +x /opt/fileanalyzer/deploy/ec2-setup.sh
sudo /opt/fileanalyzer/deploy/ec2-setup.sh
```

**3. Install dependencies and configure**

```bash
cd /opt/fileanalyzer
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env          # set OPENAI_API_KEY and/or ANTHROPIC_API_KEY
```

**4. Install as a systemd service (auto-starts on reboot)**

```bash
sudo cp deploy/fileanalyzer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fileanalyzer
sudo systemctl start fileanalyzer

# Check status
sudo systemctl status fileanalyzer
sudo journalctl -u fileanalyzer -f   # live logs
```

**5. Set up nginx reverse proxy (serves on port 80)**

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/fileanalyzer
sudo ln -sf /etc/nginx/sites-available/fileanalyzer /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

**6. Access the app**

Open `http://<EC2_PUBLIC_IP>` in your browser.

> **HTTPS:** Install Certbot (`sudo snap install certbot --classic`) and run `sudo certbot --nginx` with your domain pointed at the EC2 IP.

---

### Option B — ECS Fargate + Docker (scalable, containerized)

Best for teams or when you want auto-scaling and no server management.

**Architecture:** ECR (image registry) → ECS Fargate (container) → EFS (persistent ChromaDB) → ALB (load balancer)

**1. Build and push the Docker image to ECR**

```bash
# Authenticate
aws ecr get-login-password --region <REGION> | \
  docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com

# Create ECR repo (first time only)
aws ecr create-repository --repository-name fileanalyzer --region <REGION>

# Build and push
docker build -t fileanalyzer .
docker tag fileanalyzer:latest <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/fileanalyzer:latest
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/fileanalyzer:latest
```

**2. Store API keys in Secrets Manager**

```bash
aws secretsmanager create-secret \
  --name fileanalyzer/openai-key \
  --secret-string '{"OPENAI_API_KEY":"sk-..."}' \
  --region <REGION>

aws secretsmanager create-secret \
  --name fileanalyzer/anthropic-key \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-..."}' \
  --region <REGION>
```

**3. Create EFS for ChromaDB persistence**

```bash
aws efs create-file-system --region <REGION>
# Note the FileSystemId, put it in deploy/ecs-task-definition.json
```

**4. Register the task definition**

```bash
# Edit deploy/ecs-task-definition.json — replace placeholders:
# <ACCOUNT_ID>, <REGION>, <EFS_FILE_SYSTEM_ID>

aws ecs register-task-definition \
  --cli-input-json file://deploy/ecs-task-definition.json \
  --region <REGION>
```

**5. Create ECS cluster and service, then attach an Application Load Balancer**

```bash
aws ecs create-cluster --cluster-name fileanalyzer --region <REGION>

aws ecs create-service \
  --cluster fileanalyzer \
  --service-name fileanalyzer-svc \
  --task-definition fileanalyzer \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SUBNET_ID>],securityGroups=[<SG_ID>],assignPublicIp=ENABLED}" \
  --region <REGION>
```

---

### Cost Comparison

| Option | Instance | Est. monthly cost |
|---|---|---|
| EC2 t3.medium | 2 vCPU / 4 GB | ~$30 |
| EC2 t3.large | 2 vCPU / 8 GB | ~$60 |
| ECS Fargate (1 vCPU / 3 GB, 24/7) | — | ~$35 |
| ECS Fargate (on-demand, 8h/day) | — | ~$12 |

> The embedding model (`all-MiniLM-L6-v2`) requires at least **4 GB RAM**. `t3.small` (2 GB) will OOM.

### Deployment Files

```
deploy/
├── ec2-setup.sh            # One-shot EC2 setup script
├── fileanalyzer.service    # systemd service (auto-start on reboot)
├── nginx.conf              # nginx reverse proxy config
└── ecs-task-definition.json# ECS Fargate task definition
Dockerfile                  # Container image definition
.dockerignore
```

---

## File Type Support

| Format | Parser | Streaming strategy | Notes |
|---|---|---|---|
| PDF | `pypdf` | Page-by-page iteration | Scanned/image-only PDFs (no text layer) will raise an error |
| DOCX | `python-docx` | Paragraphs in batches of 20 + tables | Embedded images are ignored |
| TXT | Built-in | 64KB block reads, paragraph splits | UTF-8 with `errors='replace'` for non-UTF-8 bytes |
| CSV | `pandas` | `chunksize=10,000` rows | Column schema + sample shown as context; very wide tables truncated at 30 cols |

---

## Memory Model

FileAnalyzer handles files up to 500 MB without running out of memory.

**Peak RAM usage:**

| Component | RAM | Notes |
|---|---|---|
| Embedding model | ~300 MB | Loaded once, cached in memory |
| Chunk embed buffer | ~100 KB | Max 200 chunks × 512 chars |
| ChromaDB index | disk (mmap) | HNSW index is memory-mapped from disk |
| Parser segment | ~64 KB–1 page | Only current segment in memory |

**Total peak: ~400–800 MB** regardless of file size.

`gc.collect()` is called after every flush cycle to prompt Python to release memory from processed chunks.

---

## Optional: CLI Usage

The original CLI still works alongside the web UI:

```bash
python -m src.main load report.pdf
python -m src.main chat report.pdf
python -m src.main ask report.pdf "What are the findings?"
python -m src.main list
python -m src.main clear report.pdf
```

---

## Troubleshooting

**API key not working**
Make sure you copied the full key. OpenAI keys start with `sk-`, Anthropic keys with `sk-ant-`.

**`No text could be extracted from file.pdf`**
The PDF is scanned/image-based. Apply OCR first (e.g., `ocrmypdf input.pdf output.pdf`).

**`File is X MB, which exceeds the 500 MB limit`**
Split the file or increase `MAX_FILE_SIZE_MB` in `src/config.py`.

**Slow first run**
The `all-MiniLM-L6-v2` model (~80 MB) is downloading. Subsequent runs use the cached model.

**Answers seem unrelated to the document**
Increase `TOP_K_RETRIEVAL` in `.env` (try `8` or `10`), or decrease `CHUNK_SIZE` for finer granularity.

**Port already in use**
Run on a different port: `streamlit run app.py --server.port 8502`
