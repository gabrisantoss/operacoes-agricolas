from __future__ import annotations

import json
import socket
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def timestamp_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def check_tcp_port(host: str, port: int | str | None, timeout: float = 0.85) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_health_payload(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw[:300].decode("utf-8", errors="replace")}
    return payload if isinstance(payload, dict) else {"payload": payload}


def check_system(system: dict, http_timeout: float = 2.5, tcp_timeout: float = 0.85) -> dict:
    started = time.perf_counter()
    host = str(system.get("internal_host") or "127.0.0.1")
    port = system.get("internal_port")
    health_url = str(system.get("health_url") or "").strip()
    http_status = None
    details: dict[str, Any] = {}
    status = "unknown"

    if not system.get("enabled", True):
        return {
            "id": system.get("id"),
            "name": system.get("name"),
            "status": "offline",
            "http_status": None,
            "latency_ms": 0,
            "last_checked": timestamp_text(),
            "details": {"enabled": False},
        }

    if health_url:
        try:
            request = Request(health_url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=http_timeout) as response:
                http_status = response.status
                payload = _parse_health_payload(response.read(4096))
            details.update(payload)
            payload_ok = payload.get("ok")
            if http_status < 400 and payload_ok is not False:
                status = "online"
            elif check_tcp_port(host, port, tcp_timeout):
                status = "degraded"
            else:
                status = "offline"
        except HTTPError as exc:
            http_status = exc.code
            details["error"] = str(exc)
            status = "degraded" if check_tcp_port(host, port, tcp_timeout) else "offline"
        except (URLError, TimeoutError, OSError) as exc:
            details["error"] = str(exc)
            status = "degraded" if check_tcp_port(host, port, tcp_timeout) else "offline"
    else:
        status = "online" if check_tcp_port(host, port, tcp_timeout) else "offline"

    return {
        "id": system.get("id"),
        "name": system.get("name"),
        "status": status,
        "http_status": http_status,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "last_checked": timestamp_text(),
        "details": details,
    }


def check_systems(systems: list[dict], http_timeout: float = 2.5, tcp_timeout: float = 0.85) -> list[dict]:
    return [check_system(system, http_timeout=http_timeout, tcp_timeout=tcp_timeout) for system in systems]
