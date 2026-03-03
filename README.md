# 🚀 Webhook Receiver + Telegram Bot

[![Python](https://img.shields.io/badge/Python-FastAPI-blue?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-purple?style=flat&logo=telegram)](https://core.telegram.org/bots)
[![GitHub](https://img.shields.io/badge/GitHub-Repo-black?style=flat&logo=github)](https://github.com/reemamrzaki-oss/webhook-receiver)

Python FastAPI webhook server on **port 8443** with Telegram long-polling bot, 
file storage, rate limiting, and full Ubuntu VPS deployment.

## 📖 Table of Contents
- [✨ Features](#features)
- [🧪 Flow](#flow)
- [📦 Quick Setup](#quick-setup)
- [🧪 Test](#test)
- [🤖 Telegram Bot](#telegram-bot)
- [🔧 Troubleshooting](#troubleshooting)
- [🛠️ Customization](#customization)
- [📁 Structure](#structure)

## ✨ Features
- `/webhook`: **ALL HTTP methods** / content-types (JSON/form/text/binary, up to **10MB**)
- **Full logging**: Headers (JSON), raw body, query params, source IP, ISO timestamp, method/path, UUID ID
- **Instant 200 OK**: `{"request_id": "uuid", "status": "received"}` (no blocking)
- **Telegram notifications**: Formatted summary + download link to bound chats
- **Bot commands**: `/bind` / `/unbind` / `/pause` / `/resume` / `/status` / `/stats` / `/recent` / `/get <id>` (full file)
- `/file/{id}`: Raw download w/ attachment header (open access)
- `/health`: Status check
- **Rate limit**: 100 req/min/IP (memory)
- **Storage**: `/opt/webhook-data/YYYY-MM-DD/{uuid}_{ts}.txt` + `data.json` (stats/bindings)
- **Cleanup**: Auto-delete >30 days (systemd timer)
- **Security**: Non-root user, UFW (22/8443), env secrets

## 🧪 Flow
```mermaid
graph TD
  A[HTTP /webhook] --> B[UUID + Save File]
  B --> C[Update JSON stats/recent]
  B --> D[Async Notify Bound Chats]
  D --> E[🆔 ID 📍 IP ⏱️ TS 📦 Method<br/>📋 Headers(500) 📄 Body(500) 🔗 /file/id]
  F[Bot /get id] --> G[Send Document]
  H[daily timer] --> I[Delete old dirs]
```

## 📦 Quick Setup (Ubuntu VPS)
1. **Bot Token**: [@BotFather](https://t.me/botfather) → `/newbot` → name/username → **copy token**.

2. **Deploy**:
   ```bash
   git clone https://github.com/reemamrzaki-oss/webhook-receiver.git
   cd webhook-receiver
   sudo bash install.sh  # Prompts token, auto-setup (user/venv/UFW/systemd)
   ```

3. **Verify**:
   ```bash
   curl http://localhost:8443/health  # {"status":"ok"}
   journalctl -u webhook.service -f  # Logs
   ```

## 🧪 Test Webhook
```bash
# Plain
curl -X POST http://YOUR_IP:8443/webhook -d 'Hello!'

# JSON
curl -X POST -H "Content-Type: application/json" http://YOUR_IP:8443/webhook -d '{"test": "data"}'

# GET query
curl "http://YOUR_IP:8443/webhook?foo=bar"
```
**Response**: `{"request_id": "uuid", "status": "received"}`

Files: `/opt/webhook-data/YYYY-MM-DD/uuid_TIMESTAMP.txt`

`bash test_webhook.sh YOUR_IP` or open `test.html`.

## 🤖 Telegram Usage
1. `/start` → Commands list
2. `/bind` → Notifications on
3. Test webhook → Ping w/ preview + link
4. `/stats` → Counts | `/recent` → Last 5 | `/get uuid` → File

## 🔧 Troubleshooting
| Issue | Fix |
|-------|-----|
| Service down | `sudo systemctl status webhook.service` |
| Logs | `journalctl -u webhook.service -f` |
| Disk full | `df -h /opt` |
| Firewall | `ufw status` |
| Bot silent | Check `.env` token, restart service |
| No notify | Bot `/status` in chat, ensure bound |

## 🛠️ Customization
- Edit `/opt/webhook/.env` (PORT/RATE etc) → `sudo systemctl restart webhook.service`
- SSL: Nginx proxy + certbot

## 📁 Structure
```
/opt/webhook/
├── app/ (app.py, storage.py, bot.py, cleanup.py)
├── venv/
├── .env
└── requirements.txt
/opt/webhook-data/ (YYYY-MM-DD/*.txt + data.json)
```

**Success**: POST → 200 + file + Telegram → `/stats` increments! 🚀