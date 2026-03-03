#!/bin/bash

# Setup HTTPS with Let's Encrypt IP certificate
# Run as root or with sudo

set -e

echo "Setting up HTTPS for webhook receiver..."

# 1. Install acme.sh
echo "Installing acme.sh..."
curl https://get.acme.sh | sh -s email=your-email@example.com
source ~/.bashrc
export PATH="$HOME/.acme.sh:$PATH"

# 2. Request certificate for IP
echo "Requesting certificate for IP 158.62.198.119..."
acme.sh --issue --standalone -d 158.62.198.119 --server letsencrypt

# 3. Create SSL directory and copy certificates
echo "Setting up SSL certificates..."
sudo mkdir -p /opt/webhook/ssl
sudo cp ~/.acme.sh/158.62.198.119/fullchain.cer /opt/webhook/ssl/fullchain.pem
sudo cp ~/.acme.sh/158.62.198.119/158.62.198.119.key /opt/webhook/ssl/privkey.pem
sudo chmod 600 /opt/webhook/ssl/privkey.pem
sudo chmod 644 /opt/webhook/ssl/fullchain.pem
sudo chown root:root /opt/webhook/ssl/*

# 4. Modify FastAPI app to use SSL
echo "Updating FastAPI app for SSL..."
sudo sed -i 's/uvicorn.run(app, host="0.0.0.0", port=PORT)/uvicorn.run(app, host="0.0.0.0", port=PORT, ssl_keyfile="\/opt\/webhook\/ssl\/privkey.pem", ssl_certfile="\/opt\/webhook\/ssl\/fullchain.pem")/' /opt/webhook/app/app.py

# 5. Restart webhook service
echo "Restarting webhook service..."
sudo systemctl restart webhook

# 6. Set up automatic renewal
echo "Setting up automatic renewal..."
(crontab -l ; echo "0 0 * * * ~/.acme.sh/acme.sh --cron --home ~/.acme.sh && sudo systemctl restart webhook") | crontab -

# 7. Close port 80 (optional)
echo "Closing port 80..."
sudo ufw delete allow 80/tcp || true

echo "HTTPS setup complete!"
echo "New HTTPS URL: https://158.62.198.119:8443/webhook/{token}?site=..."
echo "Test with: curl -k https://158.62.198.119:8443/health"