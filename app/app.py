from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4
import os
import multiprocessing
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
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

# 1x1 transparent PNG for image beacon fallback
TRANSPARENT_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82'

limiter = Limiter(key_func=get_remote_address)

class DynamicCORSMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            origin = headers.get(b"origin", b"").decode()
            method = scope.get("method", b"").decode()
            print(f"Middleware: Method={method}, Origin='{origin}', Path={scope.get('path', '')}")
            if method == "OPTIONS" and origin:
                print("Handling preflight")
                # Handle preflight request
                async def preflight_send(message):
                    if message["type"] == "http.response.start":
                        message["status"] = 200
                        message["headers"] = [
                            (b"access-control-allow-origin", origin.encode()),
                            (b"access-control-allow-methods", b"GET,HEAD,POST,PUT,DELETE,CONNECT,OPTIONS,TRACE,PATCH"),
                            (b"access-control-allow-headers", b"*"),
                            (b"access-control-allow-credentials", b"true"),
                            (b"vary", b"origin"),
                        ]
                    await send(message)
                await preflight_send({"type": "http.response.start", "status": 200, "headers": []})
                await preflight_send({"type": "http.response.body", "body": b""})
                return
            elif origin:
                print("Adding CORS headers to response")
                # Add CORS headers to actual requests
                async def send_wrapper(message):
                    if message["type"] == "http.response.start":
                        resp_headers = message.get("headers", [])
                        resp_headers.append((b"access-control-allow-origin", origin.encode()))
                        resp_headers.append((b"vary", b"origin"))
                        message["headers"] = resp_headers
                    await send(message)
                await self.app(scope, receive, send_wrapper)
                return
        await self.app(scope, receive, send)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init bot and start polling in process
    from .bot import init_bot
    app.state.bot_app = await init_bot()
    def run_polling():
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
        app.state.bot_app.run_polling(drop_pending_updates=True)
    process = multiprocessing.Process(target=run_polling, daemon=True)
    process.start()
    yield
    # Shutdown
    if process.is_alive():
        process.terminate()

app = FastAPI(title="Webhook Receiver", lifespan=lifespan)

# Dynamic CORS middleware for secure origin echoing and preflight handling
app.add_middleware(DynamicCORSMiddleware)

app.add_middleware(SlowAPIMiddleware)
app.state.limiter = limiter
app.state.data_file = DATA_DIR / "data.json"

@app.api_route("/webhook", methods=["GET","HEAD","POST","PUT","DELETE","CONNECT","TRACE","PATCH"])
@limiter.limit(RATE_LIMIT)
async def webhook_old(request: Request):
    raise HTTPException(403, "Access denied. Use /webhook/{token} with a valid token.")

@app.api_route("/webhook/{token}", methods=["GET","HEAD","POST","PUT","DELETE","CONNECT","TRACE","PATCH"])
@limiter.limit(RATE_LIMIT)
async def webhook_endpoint(token: str, request: Request, background_tasks: BackgroundTasks):
    # Verify token
    from .storage import verify_token
    token_data = await verify_token(token)
    if not token_data:
        raise HTTPException(403, "Invalid token")
    site = token_data["site"]

    req_id = str(uuid4())
    ts = datetime.utcnow().isoformat()
    client_ip = request.client.host
    method = request.method
    full_url = str(request.url)
    headers = dict(request.headers)
    query_params = dict(request.query_params)

    if request.method == "GET":
        body = request.query_params.get("data", "").encode()
    else:
        body = await request.body()
    if len(body) > MAX_BODY_SIZE:
        raise HTTPException(413, "Payload too large")

# Check for duplicates (but don't skip processing)
    from .storage import is_duplicate_request
    is_duplicate = is_duplicate_request(headers, body)
    if is_duplicate:
        print(f"Duplicate request detected for {req_id}, but processing anyway.")

    # Always save to file and update stats
    from .storage import save_webhook_request, update_stats_and_recent
    save_webhook_request(req_id, ts, client_ip, method, full_url, headers, query_params, body)
    update_stats_and_recent(req_id, ts)

    # Always notify Telegram chats
    await notify_telegram_chats(req_id, client_ip, ts, method, full_url, headers, body, site, request)

    # Determine response based on method and duplicate status
    if request.method == "GET":
        return Response(content=TRANSPARENT_PNG, media_type="image/png")
    else:
        status = "duplicate" if is_duplicate else "received"
        return {"request_id": req_id, "status": status}

@app.get("/health")
async def health():
    return {"status": "ok", "data_dir": str(DATA_DIR)}

@app.get("/file/{req_id}")
@limiter.limit("10/minute")  # Rate limit downloads
async def download_file(req_id: str, request: Request):
    # Basic security: only allow if request has valid referer or something, but for now, rate limited
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

async def notify_telegram_chats(req_id: str, ip: str, ts: str, method: str, url: str, headers: dict, body: bytes, site: str = "default", request: Request = None):
    try:
        print(f"Notifying Telegram for request {req_id}")
        from .bot import send_to_bound_chats
        preview_headers = str(headers)[:500] + '...' if len(str(headers)) > 500 else str(headers)
        preview_body = body.decode(errors='ignore')[:500] + '...' if len(body) > 500 else body.decode(errors='ignore')
        download_url = f"https://158.62.198.119:{PORT}/file/{req_id}"
        msg = f"🆔 {req_id}\n📍 {ip}\n⏱️ {ts}\n📦 {method} {url}\n📋 Headers: {preview_headers}\n📄 Body: {preview_body}\n🔗 {download_url}"
        await send_to_bound_chats(msg, site, req_id)
        print(f"Notification sent for {req_id}")
    except Exception as e:
        print(f"Error notifying Telegram for {req_id}: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)