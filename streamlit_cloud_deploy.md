# Deploying to Streamlit Cloud

## Prerequisites
- GitHub account
- Streamlit Cloud account (free at share.streamlit.io)
- OpenAI or Anthropic API key

---

## Step 1 — Prepare the Repository

### 1.1 Create `.gitignore`
Create this file in the project root so secrets and data are never committed:

```
.env
data/
*.pem
*.key
__pycache__/
.venv/
venv/
*.pyc
.DS_Store
```

### 1.2 Create `.streamlit/secrets.toml`
Create the folder `.streamlit/` in the project root and add `secrets.toml`:

```toml
OPENAI_API_KEY = "sk-..."
ANTHROPIC_API_KEY = "sk-ant-..."
```

> **Important:** Add `secrets.toml` to `.gitignore` — never commit this file.
> Add this line to your `.gitignore`:
> ```
> .streamlit/secrets.toml
> ```

---

## Step 2 — Update app.py to Read Streamlit Secrets

In `app.py`, the sidebar reads API keys using `os.environ.get(...)`.
Add a fallback to `st.secrets` so Streamlit Cloud can provide them.

Find these two lines in `render_sidebar()` (around line 172 and 181):

```python
value=os.environ.get("OPENAI_API_KEY", ""),
```
```python
value=os.environ.get("ANTHROPIC_API_KEY", ""),
```

Replace with:

```python
value=os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", ""),
```
```python
value=os.environ.get("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY", ""),
```

---

## Step 3 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

## Step 4 — Deploy on Streamlit Cloud

1. Go to **share.streamlit.io** and sign in with GitHub
2. Click **"New app"**
3. Select your repository and branch (`main`)
4. Set **Main file path** to `app.py`
5. Click **"Advanced settings"**
6. Paste your secrets in the **Secrets** box:

```toml
OPENAI_API_KEY = "sk-..."
ANTHROPIC_API_KEY = "sk-ant-..."
```

7. Click **Deploy**

Streamlit Cloud will install all packages from `requirements.txt` automatically.
First deploy takes ~5 minutes (downloads sentence-transformers model ~80MB).

---

## Step 5 — Verify

Once deployed, your app is live at:
```
https://YOUR_USERNAME-YOUR_REPO-app-XXXXX.streamlit.app
```

Test it by:
- Opening the app URL
- Going to **Document Analysis**
- Uploading a PDF or log file
- Asking a question

---

## Known Limitations on Streamlit Cloud

| Feature | Status | Notes |
|---|---|---|
| Document Q&A | Works | Documents must be re-uploaded each session (no persistent storage) |
| Log Monitoring | Limited | SSH connections work but project configs reset on restart |
| Background Scheduler | Not reliable | App sleeps after ~15 min inactivity — scheduled checks stop |
| SSH .pem key files | Not supported | File paths on your PC don't exist on the cloud server |
| Email alerts | Works | As long as SMTP credentials are set in the Settings page |

### Recommendation
Use Streamlit Cloud for **Document Analysis and Q&A**.
For the full monitoring + deployment features, host on **AWS EC2** (see `aswdeployment.md`).

---

## Updating the App

After making code changes locally:

```bash
git add .
git commit -m "Your update message"
git push
```

Streamlit Cloud auto-detects the push and redeploys within ~1 minute.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| App crashes on startup | Check **Manage app → Logs** for the error |
| `ModuleNotFoundError` | Ensure the package is in `requirements.txt` |
| API key not working | Re-enter in Streamlit Cloud **Secrets** settings |
| Out of memory | sentence-transformers needs ~600MB RAM — free tier may struggle with large files |
| Slow first load | Normal — model downloads on cold start (~80MB) |
