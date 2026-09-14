from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable


class DurableAuditSpool:
    """Small file-backed outbox that never persists session credentials."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._lock = threading.Lock()

    def _write_atomic(self, path: Path, item: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{path.name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def enqueue(self, payload: dict, *, event_id: str | None = None) -> str:
        identifier = str(event_id or payload.get("eventId") or uuid.uuid4().hex)
        path = self.root / f"{identifier}.json"
        with self._lock:
            if path.exists():
                return identifier
            item = {
                "eventId": identifier,
                "createdAt": time.time(),
                "attempts": 0,
                "nextAttemptAt": 0.0,
                "payload": {**payload, "eventId": identifier},
            }
            self._write_atomic(path, item)
        return identifier

    def flush(
        self,
        sender: Callable[[dict], None],
        *,
        max_items: int = 20,
        now: float | None = None,
    ) -> dict[str, int]:
        current_time = time.time() if now is None else float(now)
        sent = failed = deferred = 0
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            paths = sorted(self.root.glob("*.json"), key=lambda item: item.name)[: max(0, int(max_items))]
            for path in paths:
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    failed += 1
                    continue
                if float(item.get("nextAttemptAt") or 0) > current_time:
                    deferred += 1
                    continue
                try:
                    sender(dict(item.get("payload") or {}))
                    path.unlink()
                    sent += 1
                except Exception as exc:
                    attempts = int(item.get("attempts") or 0) + 1
                    item["attempts"] = attempts
                    item["lastError"] = str(exc)[:500]
                    item["nextAttemptAt"] = current_time + min(3600, 2 ** min(attempts, 10))
                    self._write_atomic(path, item)
                    failed += 1
        return {"sent": sent, "failed": failed, "deferred": deferred}
