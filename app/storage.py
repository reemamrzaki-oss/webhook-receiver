import aiofiles
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import os

from dotenv import load_dotenv
load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/webhook-data"))
DATA_FILE = DATA_DIR / "data.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

async def load_data() -> Dict[str, Any]:
    try:
        async with aiofiles.open(DATA_FILE, mode='r') as f:
            content = await f.read()
            data = json.loads(content)
            # Ensure structure
            data.setdefault("chats", [])
            data.setdefault("paused_chats", [])
            data.setdefault("stats", {"total": 0, "daily": 0, "reset_date": datetime.now().date().isoformat()})
            data.setdefault("recent", [])
            return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {
            "chats": [],
            "paused_chats": [],
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

async def get_bound_chats() -> List[int]:
    data = await load_data()
    active_chats = [chat for chat in data["chats"] if chat not in data["paused_chats"]]
    return active_chats