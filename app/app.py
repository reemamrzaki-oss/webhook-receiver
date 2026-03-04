from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4
import os
import multiprocessing
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/webhook-data"))
PORT = int(os.getenv("PORT", 8443))
RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")
MAX_BODY_SIZE = int(os.getenv("MAX_BODY_SIZE", 10_485_760))

# 1x1 transparent PNG – returned for every GET request
TRANSPARENT_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82'

limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init bot and start polling in separate process
    from .bot import init_bot
    app.state.bot_app = await init_bot()
    def run_polling():
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
        app.state.bot_app.run_polling(drop_pending_updates=True)
    process = multiprocessing.Process(target=run_polling, daemon=True)
    process.start()
    yield
    if process.is_alive():
        process.terminate()

app = FastAPI(title="Ultimate Webhook Receiver", lifespan=lifespan)

# CORS – allow everything
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

# ----------------------------------------------------------------------
# Background task to process GET data (so we return PNG instantly)
# ----------------------------------------------------------------------
async def process_get_data(token: str, site: str, data: str, request: Request):
    try:
        from .storage import verify_token, save_webhook_request, update_stats_and_recent, is_duplicate_request
        token_data = await verify_token(token)
        if not token_data:
            print(f"Invalid token {token} for site {site}")
            return
        # site from token_data overrides passed site
        site = token_data["site"]

        req_id = str(uuid4())
        ts = datetime.utcnow().isoformat()
        client_ip = request.client.host
        method = "GET"
        full_url = str(request.url)
        headers = dict(request.headers)
        query_params = dict(request.query_params)
        body = data.encode()

        if len(body) > MAX_BODY_SIZE:
            print(f"Payload too large for {req_id}")
            return

        # Duplicate check (optional)
        is_duplicate = is_duplicate_request(headers, body)
        if is_duplicate:
            print(f"Duplicate request {req_id}, but processing anyway.")

        save_webhook_request(req_id, ts, client_ip, method, full_url, headers, query_params, body)
        update_stats_and_recent(req_id, ts)

        # Notify Telegram (import here to avoid circular imports)
        from .bot import send_to_bound_chats
        preview_headers = str(headers)[:500] + '...' if len(str(headers)) > 500 else str(headers)
        preview_body = body.decode(errors='ignore')[:500] + '...' if len(body) > 500 else body.decode(errors='ignore')
        download_url = f"https://{request.url.hostname}:{PORT}/file/{req_id}"
        msg = f"🆔 {req_id}\n📍 {client_ip}\n⏱️ {ts}\n📦 {method} {full_url}\n📋 Headers: {preview_headers}\n📄 Body: {preview_body}\n🔗 {download_url}"
        await send_to_bound_chats(msg, site, req_id)
        print(f"Processed GET for {req_id}")
    except Exception as e:
        print(f"Error in process_get_data: {e}")

# ----------------------------------------------------------------------
# Webhook endpoints
# ----------------------------------------------------------------------
@app.api_route("/webhook", methods=["GET","HEAD","POST","PUT","DELETE","CONNECT","TRACE","PATCH"])
@limiter.limit(RATE_LIMIT)
async def webhook_old(request: Request):
    # For backward compatibility – return PNG even for bad requests
    if request.method == "GET":
        return Response(content=TRANSPARENT_PNG, media_type="image/png")
    raise HTTPException(403, "Access denied. Use /webhook/{token} with a valid token.")

@app.api_route("/webhook/{token}", methods=["GET","HEAD","POST","PUT","DELETE","CONNECT","TRACE","PATCH"])
@limiter.limit(RATE_LIMIT)
async def webhook_endpoint(token: str, request: Request, background_tasks: BackgroundTasks):
    # For GET requests, return PNG immediately and process data in background
    if request.method == "GET":
        data = request.query_params.get("data", "")
        site = request.query_params.get("site", "unknown")
        background_tasks.add_task(process_get_data, token, site, data, request)
        return Response(content=TRANSPARENT_PNG, media_type="image/png")

    # For non-GET, verify token and process normally (but still return PNG? optional)
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
    body = await request.body()
    if len(body) > MAX_BODY_SIZE:
        raise HTTPException(413, "Payload too large")

    from .storage import is_duplicate_request, save_webhook_request, update_stats_and_recent
    is_duplicate = is_duplicate_request(headers, body)
    if is_duplicate:
        print(f"Duplicate request {req_id}, but processing anyway.")

    save_webhook_request(req_id, ts, client_ip, method, full_url, headers, query_params, body)
    update_stats_and_recent(req_id, ts)

    from .bot import send_to_bound_chats
    preview_headers = str(headers)[:500] + '...' if len(str(headers)) > 500 else str(headers)
    preview_body = body.decode(errors='ignore')[:500] + '...' if len(body) > 500 else body.decode(errors='ignore')
    download_url = f"https://{request.url.hostname}:{PORT}/file/{req_id}"
    msg = f"🆔 {req_id}\n📍 {client_ip}\n⏱️ {ts}\n📦 {method} {full_url}\n📋 Headers: {preview_headers}\n📄 Body: {preview_body}\n🔗 {download_url}"
    await send_to_bound_chats(msg, site, req_id)

    # For non-GET, return JSON (but PNG would also work – keep JSON for clarity)
    status = "duplicate" if is_duplicate else "received"
    return {"request_id": req_id, "status": status}

# ----------------------------------------------------------------------
# Health and file download
# ----------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "data_dir": str(DATA_DIR)}

@app.get("/file/{req_id}")
@limiter.limit("10/minute")
async def download_file(req_id: str, request: Request):
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)