from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4
import os
import threading
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/webhook-data"))
PORT = int(os.getenv("PORT", 8443))
RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")
MAX_BODY_SIZE = int(os.getenv("MAX_BODY_SIZE", 10_485_760))

limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start bot polling in process
    from multiprocessing import Process
    async def run_polling():
        from .bot import init_bot
        bot_app = await init_bot()
        bot_app.run_polling(drop_pending_updates=True)
    def start_polling():
        import asyncio
        asyncio.run(run_polling())
    process = Process(target=start_polling, daemon=True)
    process.start()
    yield
    # Shutdown

app = FastAPI(title="Webhook Receiver", lifespan=lifespan)

app.add_middleware(SlowAPIMiddleware)
app.state.limiter = limiter
app.state.data_file = DATA_DIR / "data.json"

@app.api_route("/webhook", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
@limiter.limit(RATE_LIMIT)
async def webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
    req_id = str(uuid4())
    ts = datetime.utcnow().isoformat()
    client_ip = request.client.host
    method = request.method
    full_url = str(request.url)
    headers = dict(request.headers)
    query_params = dict(request.query_params)
    
    body = await request.body()
    if len(body) > MAX_BODY_SIZE:
        raise HTTPException(413, "Payload too large")
    
    # Save to file and update stats
    from .storage import save_webhook_request, update_stats_and_recent
    await save_webhook_request(req_id, ts, client_ip, method, full_url, headers, query_params, body)
    await update_stats_and_recent(req_id, ts)
    
    # Async notify Telegram chats
    background_tasks.add_task(notify_telegram_chats, req_id, client_ip, ts, method, full_url, headers, body)
    
    return {"request_id": req_id, "status": "received"}

@app.get("/health")
async def health():
    return {"status": "ok", "data_dir": str(DATA_DIR)}

@app.get("/file/{req_id}")
async def download_file(req_id: str):
    from .storage import find_request_file
    file_path = await find_request_file(req_id)
    if not file_path or not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(
        file_path,
        media_type="text/plain",
        filename=f"webhook_{req_id}.txt",
        headers={"Content-Disposition": f"attachment; filename=webhook_{req_id}.txt"}
    )

async def notify_telegram_chats(req_id: str, ip: str, ts: str, method: str, url: str, headers: dict, body: bytes):
    from .bot import send_to_bound_chats
    preview_headers = str(headers)[:500] + '...' if len(str(headers)) > 500 else str(headers)
    preview_body = body.decode(errors='ignore')[:500] + '...' if len(body) > 500 else body.decode(errors='ignore')
    msg = f"🆔 {req_id}\n📍 {ip}\n⏱️ {ts}\n📦 {method} {url}\n📋 Headers: {preview_headers}\n📄 Body: {preview_body}\n🔗 http://YOUR_VPS_IP:{PORT}/file/{req_id}"
    await send_to_bound_chats(msg)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)