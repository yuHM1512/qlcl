"""Kéo sản lượng ra chuyền (chuyền treo) trực tiếp từ app chuyền treo của từng XN.

Trang nhập liệu QC hỏi `/api/qc/hanging-output` mỗi 30 giây; QLCL gọi
`GET <HANGING_APP_URLS[don_vi]>/api/qlcl/hanging-output?mono=&date=` (X-API-Key = QLCL_API_KEY)
và cache kết quả HANGING_OUTPUT_CACHE_SECONDS giây cho mỗi (đơn vị, MONo, ngày),
nên nhiều máy QC cùng mở một kế hoạch chỉ tạo ~1 truy vấn MES mỗi chu kỳ cache.
Lỗi cũng được cache ngắn để XN mất kết nối không làm mọi request chờ hết timeout.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from app_core import core

# Cloudflare chặn User-Agent mặc định của urllib → dùng UA trình duyệt (giống app chuyền treo).
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_ERROR_CACHE_SECONDS = 20

_cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}
_key_locks: Dict[Tuple[str, str, str], threading.Lock] = {}
_lock = threading.Lock()


class LiveOutputError(RuntimeError):
    pass


def base_url_for(don_vi: str) -> Optional[str]:
    return core.HANGING_APP_URLS.get((don_vi or "").strip())


def _fetch(base_url: str, mono: str, day: str) -> Dict[str, Any]:
    query = urllib.parse.urlencode({"mono": mono, "date": day})
    req = urllib.request.Request(f"{base_url}/api/qlcl/hanging-output?{query}", method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", _USER_AGENT)
    if core._PUSH_API_KEY:
        req.add_header("X-API-Key", core._PUSH_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=core.HANGING_OUTPUT_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise LiveOutputError(f"app chuyền treo trả lỗi {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LiveOutputError(f"không kết nối được app chuyền treo: {exc}") from exc
    except ValueError as exc:
        raise LiveOutputError("app chuyền treo trả dữ liệu không phải JSON") from exc
    try:
        return {"qty": int(data["qty"])}
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveOutputError("app chuyền treo trả thiếu qty") from exc


def get_live_output(don_vi: str, mono: str, day: str, *, force: bool = False) -> Optional[Dict[str, Any]]:
    """{"qty": int, "fetched_at": epoch} hoặc None nếu đơn vị chưa cấu hình URL.

    Raise LiveOutputError khi gọi lỗi (kể cả lỗi còn trong cache ngắn hạn).
    `force=True` (nút làm mới) bỏ qua cache.
    """
    base_url = base_url_for(don_vi)
    if not base_url:
        return None
    key = (don_vi, mono, day)
    started = time.monotonic()
    if not force:
        cached = _fresh_entry(key, started)
        if cached is not None:
            return _unwrap(cached)

    # Single-flight: mỗi (đơn vị, MONo, ngày) chỉ 1 request gọi sang XN tại một thời điểm.
    # Request đến cùng lúc chờ rồi dùng luôn kết quả vừa lấy (kể cả khi bấm Làm mới).
    with _key_lock(key):
        with _lock:
            hit = _cache.get(key)
        if hit and hit[0] >= started:
            return _unwrap(hit[1])
        try:
            entry = _fetch(base_url, mono, day)
        except LiveOutputError as exc:
            _store(key, {"error": str(exc)})
            raise
        entry["fetched_at"] = time.time()
        _store(key, entry)
        return dict(entry)


def _fresh_entry(key, now: float) -> Optional[Dict[str, Any]]:
    with _lock:
        hit = _cache.get(key)
    if not hit:
        return None
    stored_at, entry = hit
    ttl = _ERROR_CACHE_SECONDS if "error" in entry else core.HANGING_OUTPUT_CACHE_SECONDS
    return entry if now - stored_at < ttl else None


def _unwrap(entry: Dict[str, Any]) -> Dict[str, Any]:
    if "error" in entry:
        raise LiveOutputError(entry["error"])
    return dict(entry)


def _key_lock(key) -> threading.Lock:
    with _lock:
        lock = _key_locks.get(key)
        if lock is None:
            lock = _key_locks[key] = threading.Lock()
        return lock


def _store(key, entry: Dict[str, Any]) -> None:
    with _lock:
        _cache[key] = (time.monotonic(), entry)
        if len(_cache) > 2000:  # chặn tăng vô hạn: bỏ các mục cũ nhất
            for old_key, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:500]:
                _cache.pop(old_key, None)
                _key_locks.pop(old_key, None)


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _key_locks.clear()
