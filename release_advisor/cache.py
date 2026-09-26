"""SQLite cache of finished reports, so repeated questions do not repeat research."""

from __future__ import annotations

import os
import sqlite3
import threading
import time

from .report import FinalReport


class ReportCache:
    def __init__(self, path: str, ttl_hours: float):
        self.ttl_seconds = ttl_hours * 3600
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS reports (key TEXT PRIMARY KEY, created REAL, body TEXT)"
        )
        self._db.commit()

    @staticmethod
    def key(location: str, agent: str, revision: str, focus: str) -> str:
        return f"{location}|{agent}|{revision}|{focus}"

    def get(self, key: str) -> FinalReport | None:
        if self.ttl_seconds <= 0:
            return None
        with self._lock:
            row = self._db.execute("SELECT created, body FROM reports WHERE key = ?", (key,)).fetchone()
        if not row or time.time() - row[0] > self.ttl_seconds:
            return None
        try:
            return FinalReport.model_validate_json(row[1])
        except ValueError:  # report saved by an older version of the app
            return None

    def put(self, key: str, report: FinalReport) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO reports (key, created, body) VALUES (?, ?, ?)",
                (key, time.time(), report.model_dump_json()),
            )
            self._db.commit()
