import aiofiles
import asyncio
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import os

from dotenv import load_dotenv
load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/webhook-data"))
DATA_FILE = DATA_DIR / "data.json"
HASHES_FILE = DATA_DIR / "hashes.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

async def load_data() -> Dict[str, Any]:
    try:
        async with aiofiles.open(DATA_FILE, mode='r') as f:
            content = await f.read()
            data = json.loads(content)
            # Ensure structure
            data.setdefault("sites", {"default": {"chats": [], "paused_chats": []}})
            data.setdefault("tokens", {})  # token -> {"chat_id": int, "site": str}
            data.setdefault("stats", {"total": 0, "daily": 0, "reset_date": datetime.now().date().isoformat()})
            data.setdefault("recent", [])
            return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {
            "sites": {"default": {"chats": [], "paused_chats": []}},
            "tokens": {},
            "stats": {"total": 0, "daily": 0, "reset_date": datetime.now().date().isoformat()},
            "recent": []
        }

async def save_data(data: Dict[str, Any]):
    async with aiofiles.open(DATA_FILE, mode='w') as f:
        await f.write(json.dumps(data, indent=2))

async def save_webhook_request(
    req_id: str,
    ts: str,
    client_ip: str,
    method: str,
    url: str,
    headers: Dict[str, str],
    query_params: Dict[str, str],
    body: bytes
):
    dt = datetime.fromisoformat(ts)
    date_str = dt.strftime("%Y-%m-%d")
    dir_path = DATA_DIR / date_str
    dir_path.mkdir(parents=True, exist_ok=True)
    
    filename = f"{req_id}_{ts.replace(' ', '_').replace(':', '_')}.txt"
    file_path = dir_path / filename
    
    content = f"""REQUEST ID: {req_id}
TIMESTAMP: {ts}
SOURCE IP: {client_ip}
METHOD: {method}
URL: {url}
HEADERS:
{json.dumps(headers, indent=2)}

QUERY PARAMS:
{json.dumps(query_params, indent=2)}

BODY:
{body.decode('utf-8', errors='replace')}
"""
    
    async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
        await f.write(content)

async def update_stats_and_recent(req_id: str, ts: str):
    data = await load_data()
    data["stats"]["total"] += 1
    
    today = datetime.now().date().isoformat()
    if data["stats"]["reset_date"] != today:
        data["stats"]["daily"] = 1
        data["stats"]["reset_date"] = today
    else:
        data["stats"]["daily"] += 1
    
    data["recent"].insert(0, {"id": req_id, "ts": ts})
    data["recent"] = data["recent"][:5]
    
    await save_data(data)

async def find_request_file(req_id: str) -> Optional[Path]:
    for file_path in DATA_DIR.rglob(f"{req_id}_*.txt"):
        return file_path
    return None

async def get_bound_chats(site: str = "default") -> List[int]:
    data = await load_data()
    site_data = data["sites"].setdefault(site, {"chats": [], "paused_chats": []})
    active_chats = [chat for chat in site_data["chats"] if chat not in site_data["paused_chats"]]
    return active_chats

async def generate_token(chat_id: int, site: str = "default") -> str:
    import secrets
    token = secrets.token_urlsafe(32)
    data = await load_data()
    data["tokens"][token] = {"chat_id": chat_id, "site": site}
    await save_data(data)
    return token

async def verify_token(token: str) -> Optional[Dict[str, Any]]:
    data = await load_data()
    return data["tokens"].get(token)

async def load_hashes() -> Dict[str, str]:
    try:
        async with aiofiles.open(HASHES_FILE, mode='r') as f:
            content = await f.read()
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

async def save_hashes(hashes: Dict[str, str]):
    async with aiofiles.open(HASHES_FILE, mode='w') as f:
        await f.write(json.dumps(hashes, indent=2))

async def is_duplicate_request(headers: Dict[str, str], body: bytes) -> bool:
    # Compute SHA-256 of headers + body
    hash_input = json.dumps(headers, sort_keys=True) + body.decode('utf-8', errors='replace')
    hash_value = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    hashes = await load_hashes()
    now = datetime.utcnow()
    
    # Check if hash exists and is within last 5 minutes
    if hash_value in hashes:
        last_ts = datetime.fromisoformat(hashes[hash_value])
        if now - last_ts < timedelta(minutes=5):
            return True
    
    # Update hash with current timestamp
    hashes[hash_value] = now.isoformat()
    
    # Clean old hashes (older than 5 minutes)
    to_remove = [h for h, ts in hashes.items() if now - datetime.fromisoformat(ts) >= timedelta(minutes=5)]
    for h in to_remove:
        del hashes[h]
    
    await save_hashes(hashes)
    return False