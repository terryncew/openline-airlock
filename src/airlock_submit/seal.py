from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from airlock.util import canonical_json_bytes, sha256_file


def seal(payload: dict, key: str) -> dict:
    if not key:
        raise RuntimeError("AIRLOCK_EVALUATION_KEY is required")
    signature = hmac.new(key.encode(), canonical_json_bytes(payload), hashlib.sha256).hexdigest()
    return {"payload": payload, "hmac_sha256": signature}


def verify(obj: dict, key: str) -> bool:
    if not key or not isinstance(obj, dict) or not isinstance(obj.get("payload"), dict):
        return False
    expected = hmac.new(key.encode(), canonical_json_bytes(obj["payload"]), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(obj.get("hmac_sha256", "")))


def load_verified(path: Path, key: str) -> dict:
    obj = json.loads(Path(path).read_text())
    if not verify(obj, key):
        raise RuntimeError("evaluation bundle signature is invalid")
    return obj["payload"]


def file_binding(path: Path) -> dict:
    return {"name": Path(path).name, "sha256": sha256_file(Path(path)), "size": Path(path).stat().st_size}
