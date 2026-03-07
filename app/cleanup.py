#!/usr/bin/env python3
import logging
from datetime import datetime, timedelta
from pathlib import Path
import shutil

# Setup logging
log_file = Path('/var/log/webhook') / 'cleanup.log'
log_file.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_DIR = Path('/opt/webhook-data')
PROTECTED_FILES = {'data.json', 'data.tmp', 'hashes.json', '.data.lock'}
cutoff_date = datetime.now() - timedelta(days=30)

deleted_dirs = 0
deleted_files = 0

try:
    for item in DATA_DIR.iterdir():
        if item.is_dir() and item.name.count('-') == 2 and len(item.name) == 10:
            try:
                dir_date = datetime.strptime(item.name, '%Y-%m-%d').date()
                if dir_date < cutoff_date.date():
                    shutil.rmtree(item)
                    logger.info(f"Deleted old directory: {item}")
                    deleted_dirs += 1
            except ValueError:
                logger.warning(f"Invalid date dir: {item}")
                continue
            except Exception as e:
                logger.error(f"Failed to delete {item}: {e}")
        elif item.is_file() and item.name not in PROTECTED_FILES:
            # Delete stray files (but never data.json, hashes.json, .data.lock)
            item.unlink(missing_ok=True)
            deleted_files += 1

    logger.info(f"Cleanup complete: {deleted_dirs} dirs, {deleted_files} files")
    print(f"Cleanup complete: deleted {deleted_dirs} directories.")

except Exception as e:
    logger.error(f"Cleanup failed: {e}")
    print(f"Cleanup failed: {e}")