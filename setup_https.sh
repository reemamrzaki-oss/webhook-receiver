#!/bin/bash

# Setup HTTPS with Let's Encrypt IP certificate
# Run as root or with sudo

set -e

echo "Setting up HTTPS for webhook receiver..."

# 1. Generate self-signed certificate (Let's Encrypt doesn't support IP certificates)
echo "Generating self-signed SSL certificate..."
sudo mkdir -p /opt/webhook/ssl
sudo openssl req -x509 -newkey rsa:4096 -keyout /opt/webhook/ssl/privkey.pem -out /opt/webhook/ssl/fullchain.pem -days 365 -nodes -subj "/C=US/ST=State/L=City/O=Organization/CN=158.62.198.119"
sudo chmod 600 /opt/webhook/ssl/privkey.pem
sudo chmod 644 /opt/webhook/ssl/fullchain.pem
sudo chown root:root /opt/webhook/ssl/*

# 2. Modify FastAPI app to use SSL
echo "Updating FastAPI app for SSL..."
sudo sed -i 's/uvicorn.run(app, host="0.0.0.0", port=PORT)/uvicorn.run(app, host="0.0.0.0", port=PORT, ssl_keyfile="\/opt\/webhook\/ssl\/privkey.pem", ssl_certfile="\/opt\/webhook\/ssl\/fullchain.pem")/' /opt/webhook/app/app.py

# 3. Restart webhook service
echo "Restarting webhook service..."
sudo systemctl restart webhook

# 4. Set up certificate renewal (manual - self-signed)
echo "Self-signed certificate created. Renew manually when needed:"
echo "sudo openssl req -x509 -newkey rsa:4096 -keyout /opt/webhook/ssl/privkey.pem -out /opt/webhook/ssl/fullchain.pem -days 365 -nodes -subj \"/C=US/ST=State/L=City/O=Organization/CN=158.62.198.119\""
echo "Then restart: sudo systemctl restart webhook"

echo "HTTPS setup complete with self-signed certificate!"
echo "New HTTPS URL: https://158.62.198.119:8443/webhook/{token}?site=..."
echo "Note: Browsers will show security warning for self-signed cert"
echo "Test with: curl -k https://158.62.198.119:8443/health"