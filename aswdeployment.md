# AWS Deployment Guide (EC2 — Step by Step)

## What's Different from a WAR Deployment

| | Java WAR App (e.g. Koupons) | FileAnalyzer |
|---|---|---|
| Language | Java | Python |
| Server | Apache Tomcat | Streamlit (built-in server) |
| Deploy artifact | `.war` file | Folder of `.py` files |
| Deploy method | Drop WAR into webapps/ | SSH + pip install + start service |

FileAnalyzer cannot be dropped into Tomcat. It runs as its own Python process,
and nginx (or a reverse proxy) sits in front of it if needed.

---

## Prerequisites

- Your `.pem` key file (e.g. `aws_dev_instance_24_05_2021.pem`)
- EC2 instance IP address
- FileZilla installed (for file upload)
- Git Bash or PuTTY installed (for SSH)

---

## PART 1 — Get SSH Access (One Time)

You already have the `.pem` key. The same key used for SCP works for SSH.

### Option A — Git Bash (easiest)

```bash
ssh -i "E:\Pavithra\Deployment\Freekwent\aws_dev_instance_24_05_2021.pem" ec2-user@<EC2_PUBLIC_IP>
```

### Option B — PuTTY (GUI)

1. Download and open **PuTTYgen**
2. Open your `.pem` file → click **Save private key** → save as `.ppk`
3. Open **PuTTY**
   - Host: `<EC2_PUBLIC_IP>`, Port: `22`
   - Connection → SSH → Auth → browse to your `.ppk` file
4. Click **Open** → login as `ec2-user`

---

## PART 2 — Upload Files via FileZilla

Connect FileZilla to the server:

- Host: `sftp://<EC2_PUBLIC_IP>`
- Username: `ec2-user`
- Key file: your `.pem` → FileZilla: Edit → Settings → SFTP → Add key file
- Port: `22`

Upload the entire `FileAnalyzer` folder to:

```
/home/ec2-user/fileanalyzer/
```

Include these files (exclude `data/` and `.env`):

```
fileanalyzer/
├── app.py
├── requirements.txt
├── .env.example
└── src/
```

---

## PART 3 — Server Setup via SSH (Run Once)

SSH into the server and run each section below.

### 1. Check / install Python 3.10+

```bash
python3 --version
# If below 3.10:
sudo yum install python3.11 -y
```

### 2. Create virtual environment and install dependencies

```bash
cd /home/ec2-user/fileanalyzer
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> The first run downloads the `all-MiniLM-L6-v2` embedding model (~80 MB). Takes 2–3 min.

### 3. Set your API key

```bash
cp .env.example .env
nano .env
# Add one or both:
#   OPENAI_API_KEY=sk-...
#   ANTHROPIC_API_KEY=sk-ant-...
# Save: Ctrl+O  →  Enter  →  Ctrl+X
```

### 4. Test manually first

```bash
source .venv/bin/activate
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Open `http://<EC2_PUBLIC_IP>:8501` in your browser — you should see the UI.
Press `Ctrl+C` to stop when done testing.

### 5. Install as a systemd service (auto-starts on reboot)

```bash
sudo nano /etc/systemd/system/fileanalyzer.service
```

Paste exactly:

```ini
[Unit]
Description=FileAnalyzer Streamlit App
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/fileanalyzer
ExecStart=/home/ec2-user/fileanalyzer/.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
EnvironmentFile=/home/ec2-user/fileanalyzer/.env

[Install]
WantedBy=multi-user.target
```

Save: `Ctrl+O` → Enter → `Ctrl+X`

```bash
sudo systemctl daemon-reload
sudo systemctl enable fileanalyzer
sudo systemctl start fileanalyzer

# Verify it is running:
sudo systemctl status fileanalyzer

# Live logs:
sudo journalctl -u fileanalyzer -f
```

---

## PART 4 — Open the Port in AWS Security Group

1. Go to **AWS Console → EC2 → Instances → your instance**
2. Click the **Security Group** link
3. Click **Inbound Rules → Edit inbound rules → Add rule**
   - Type: `Custom TCP`
   - Port range: `8501`
   - Source: `My IP` (recommended) or `0.0.0.0/0` (open to everyone)
4. Click **Save rules**

Access the app at: `http://<EC2_PUBLIC_IP>:8501`

---

## PART 5 — Future Updates (Files Only via FileZilla)

After the first setup, updating is simple — no SSH needed for file changes:

1. Upload changed files via FileZilla to `/home/ec2-user/fileanalyzer/`
2. SSH in and restart the service:

```bash
sudo systemctl restart fileanalyzer
```

---

## Useful Service Commands

```bash
# Start
sudo systemctl start fileanalyzer

# Stop
sudo systemctl stop fileanalyzer

# Restart (after updating files)
sudo systemctl restart fileanalyzer

# Check status
sudo systemctl status fileanalyzer

# View live logs
sudo journalctl -u fileanalyzer -f
```

---

## Deployment Checklist

- [ ] SSH into server using Git Bash / PuTTY + `.pem` key
- [ ] Upload project folder via FileZilla to `/home/ec2-user/fileanalyzer/`
- [ ] `pip install -r requirements.txt`
- [ ] Set API key(s) in `.env`
- [ ] Test manually: `streamlit run app.py --server.port 8501 --server.address 0.0.0.0`
- [ ] Create systemd service file
- [ ] `sudo systemctl enable fileanalyzer && sudo systemctl start fileanalyzer`
- [ ] Open port `8501` in the EC2 Security Group
- [ ] Access `http://<EC2_PUBLIC_IP>:8501`

---

## Troubleshooting

**App not reachable after starting the service**
→ Check the Security Group — port 8501 must be open inbound.

**`python3.11` not found**
→ Try `python3 --version`. If 3.10+, use `python3` instead of `python3.11` in the commands.

**Service fails to start**
→ Run `sudo journalctl -u fileanalyzer -f` to see the error.

**`pip install` fails on a package**
→ Run `sudo yum install gcc python3-devel -y` then retry pip install.

**Slow first startup**
→ Normal — the embedding model is loading into memory (~300 MB). Subsequent queries are fast.
