import os
import mimetypes
import hashlib
from datetime import datetime
from typing import Optional

mimetypes.init()

def guess_mime_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"

def file_mtime(path: str) -> Optional[datetime]:
    try:
        return datetime.utcfromtimestamp(os.path.getmtime(path))
    except Exception:
        return None

def compute_etag_bytes(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(data)
    return h.hexdigest()