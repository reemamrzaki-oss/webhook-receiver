import aiofiles
import asyncio
import json
import hashlib
import fcntl
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import os

from dotenv import load_dotenv
load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/webhook-data"))
DATA_FILE = DATA_DIR / "data.json"
HASHES_FILE = DATA_DIR / "hashes.json"
LOCK_FILE = DATA_DIR / ".data.lock"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

class DataLock:
    """File-based lock to prevent race conditions on data.json"""
    def __enter__(self):
        self.fp = open(LOCK_FILE, 'w')
        fcntl.flock(self.fp, fcntl.LOCK_EX)
        return self

    def __exit__(self, *args):
        fcntl.flock(self.fp, fcntl.LOCK_UN)
        self.fp.close()

def load_data() -> Dict[str, Any]:
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
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

def save_data(data: Dict[str, Any]):
    # Atomic write: write to temp file then rename to prevent data loss
    tmp_file = DATA_FILE.with_suffix('.tmp')
    with open(tmp_file, 'w') as f:
        json.dump(data, f, indent=2)
    tmp_file.replace(DATA_FILE)

def save_webhook_request(
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
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def update_stats_and_recent(req_id: str, ts: str):
    with DataLock():
        data = load_data()
        data["stats"]["total"] += 1
        
        today = datetime.now().date().isoformat()
        if data["stats"]["reset_date"] != today:
            data["stats"]["daily"] = 1
            data["stats"]["reset_date"] = today
        else:
            data["stats"]["daily"] += 1
        
        data["recent"].insert(0, {"id": req_id, "ts": ts})
        data["recent"] = data["recent"][:5]
        
        save_data(data)

def find_request_file(req_id: str) -> Optional[Path]:
    for file_path in DATA_DIR.rglob(f"{req_id}_*.txt"):
        return file_path
    return None

def get_bound_chats(site: str = "default") -> List[int]:
    with DataLock():
        data = load_data()
        site_data = data["sites"].setdefault(site, {"chats": [], "paused_chats": []})
        active_chats = [chat for chat in site_data["chats"] if chat not in site_data["paused_chats"]]
        return active_chats

def generate_token(chat_id: int, site: str = "default") -> str:
    import secrets
    token = secrets.token_urlsafe(32)
    with DataLock():
        data = load_data()
        data["tokens"][token] = {"chat_id": chat_id, "site": site}
        save_data(data)
    return token

def verify_token(token: str) -> Optional[str]:
    with DataLock():
        data = load_data()
        token_data = data["tokens"].get(token)
        if token_data:
            return token_data["site"]
        return None

def load_hashes() -> Dict[str, Any]:
    try:
        with open(HASHES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_hashes(hashes: Dict[str, Any]):
    with open(HASHES_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)

def is_duplicate_request(headers: Dict[str, str], body: bytes) -> bool:
    # Compute SHA-256 of headers + body
    hash_input = json.dumps(headers, sort_keys=True) + body.decode('utf-8', errors='replace')
    hash_value = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    hashes = load_hashes()
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
    
    save_hashes(hashes)
    return False