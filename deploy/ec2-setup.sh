#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# FileAnalyzer — EC2 Setup Script
# Run this once on a fresh Ubuntu 22.04 EC2 instance:
#   chmod +x deploy/ec2-setup.sh && sudo ./deploy/ec2-setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

APP_DIR="/opt/fileanalyzer"
APP_USER="ubuntu"

echo "==> Updating system packages..."
apt-get update -y && apt-get upgrade -y

echo "==> Installing Python 3.11 and system tools..."
apt-get install -y python3.11 python3.11-venv python3-pip nginx curl git

echo "==> Creating app directory at $APP_DIR..."
mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

echo ""
echo "==> NEXT STEPS (run as the ubuntu user, not root):"
echo ""
echo "  1. Upload your code to $APP_DIR:"
echo "       scp -r E:/mkonnekt/FileAnalyzer/* ubuntu@<EC2_IP>:$APP_DIR/"
echo "     OR clone from git:"
echo "       git clone <your-repo-url> $APP_DIR"
echo ""
echo "  2. Create a Python virtual environment and install dependencies:"
echo "       cd $APP_DIR"
echo "       python3.11 -m venv .venv"
echo "       source .venv/bin/activate"
echo "       pip install -r requirements.txt"
echo ""
echo "  3. Create your .env file with API keys:"
echo "       cp $APP_DIR/.env.example $APP_DIR/.env"
echo "       nano $APP_DIR/.env"
echo "     Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY"
echo ""
echo "  4. Install the systemd service:"
echo "       sudo cp $APP_DIR/deploy/fileanalyzer.service /etc/systemd/system/"
echo "       sudo systemctl daemon-reload"
echo "       sudo systemctl enable fileanalyzer"
echo "       sudo systemctl start fileanalyzer"
echo ""
echo "  5. Set up nginx reverse proxy:"
echo "       sudo cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/fileanalyzer"
echo "       sudo ln -sf /etc/nginx/sites-available/fileanalyzer /etc/nginx/sites-enabled/"
echo "       sudo rm -f /etc/nginx/sites-enabled/default"
echo "       sudo nginx -t && sudo systemctl restart nginx"
echo ""
echo "  6. Open ports in your EC2 Security Group:"
echo "       Inbound rule: TCP 80  from 0.0.0.0/0  (HTTP)"
echo "       Inbound rule: TCP 443 from 0.0.0.0/0  (HTTPS — optional, needs SSL cert)"
echo "       Inbound rule: TCP 22  from <your-IP>  (SSH — restrict to your IP)"
echo ""
echo "  7. Access the app at: http://<EC2_PUBLIC_IP>"
echo ""
echo "==> System setup complete."
