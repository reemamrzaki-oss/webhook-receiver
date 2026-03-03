#!/bin/bash
set -e

# Colors
echo_green() { echo -e "\033[32m$1\033[0m"; }
echo_red() { echo -e "\033[31m$1\033[0m"; }

# Update system
apt update && apt upgrade -y
echo_green "✅ System updated"

# Install dependencies
apt install -y python3 python3-pip python3-venv ufw curl unzip wget whoami

echo_green "✅ Dependencies installed"

# Create dedicated user
useradd -m -s /bin/bash webhook || true

echo_green "✅ User 'webhook' created"

# Create directories
mkdir -p /opt/webhook-data /var/log/webhook /opt/webhook
chown -R webhook:webhook /opt/webhook* /var/log/webhook

# Copy files (assume script run from dir containing app/, requirements.txt, .env.example, *.service)
cp -r app requirements.txt .env.example webhook.service cleanup.* /opt/webhook/
chown -R webhook:webhook /opt/webhook

cd /opt/webhook

echo_green "✅ Files copied to /opt/webhook"

# Setup .env
cat > .env << 'EOF'
PORT=8443
DATA_DIR=/opt/webhook-data
MAX_BODY_SIZE=10485760
RATE_LIMIT=100/minute
EOF

echo -n "Enter Telegram Bot Token (from @BotFather): "
read -r BOT_TOKEN
echo "BOT_TOKEN=$BOT_TOKEN" >> .env
chown webhook:webhook .env

# Create virtualenv and install deps
owner=$(id -u webhook):$(id -g webhook)
su - $owner -c "
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
"

chown -R webhook:webhook venv

echo_green "✅ Python environment setup complete"

# Systemd services
cp webhook.service cleanup.service cleanup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable webhook.service cleanup.timer
systemctl start webhook.service cleanup.timer

# UFW firewall
ufw allow 22/tcp
ufw allow 8443/tcp
ufw --force enable
ufw status

echo_green "✅ Firewall configured"

# Tests
sleep 5
echo "Testing health check..."
if curl -f http://localhost:8443/health >/dev/null; then
  echo_green "✅ Health check OK"
else
  echo_red "❌ Health check failed"
fi

VPS_IP=$(curl -s ifconfig.me)
echo_green "\n🎉 Setup COMPLETE!"
echo "Webhook endpoint: http://$VPS_IP:8443/webhook"
echo "Health: http://$VPS_IP:8443/health"
echo "Files: /opt/webhook-data"
echo "Logs: journalctl -u webhook.service -f"
echo "Get bot token if not: @BotFather"