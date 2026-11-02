import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DOCUMENT_TABLES = {
    "access_audit",
    "runs",
    "experiments",
    "drift_reports",
    "policy_events",
    "review_reports",
    "deployment_state",
    "adapt_proposals",
    "adapt_events",
    "canary_runs",
    "replay_cases",
}


class Store:
    """Small single-node store. Deduplicates OTLP delivery by trace/span IDs."""

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        if path != ":memory:":
            os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS spans (
                trace_id TEXT NOT NULL, span_id TEXT NOT NULL, start_ns INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(trace_id, span_id));
              CREATE INDEX IF NOT EXISTS spans_start ON spans(start_ns DESC);
              CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS drift_reports (
                id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS policy_events (
                id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS gateway_actions (
                action_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS gateway_resources (id TEXT PRIMARY KEY, count INTEGER NOT NULL);
              INSERT OR IGNORE INTO gateway_resources VALUES ('worker-alpha',0);
            """)

            for table in DOCUMENT_TABLES:
                self.db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL)"
                )

    def ingest(self, spans: list[dict]):
        with self.lock, self.db:
            self.db.executemany(
                "INSERT INTO spans VALUES(?,?,?,?) ON CONFLICT(trace_id,span_id) DO UPDATE SET start_ns=excluded.start_ns,payload=excluded.payload",
                [
                    (s["trace_id"], s["span_id"], s["start_ns"], json.dumps(s))
                    for s in spans
                ],
            )

    def spans(self, trace_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM spans WHERE trace_id=? ORDER BY start_ns",
                (trace_id,),
            ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def trace_ids(self, limit=200) -> list[str]:
        with self.lock:
            return [
                r[0]
                for r in self.db.execute(
                    "SELECT trace_id FROM spans GROUP BY trace_id ORDER BY MIN(start_ns) DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]

    def put(self, table: str, item: dict):
        if table not in DOCUMENT_TABLES:
            raise ValueError("unknown table")
        with self.lock, self.db:
            self.db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES(?,?,?)",
                (item["id"], time.time(), json.dumps(item)),
            )

    def list(self, table: str, limit=100) -> list[dict]:
        if table not in DOCUMENT_TABLES:
            raise ValueError("unknown table")
        with self.lock:
            rows = self.db.execute(
                f"SELECT payload FROM {table} ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get(self, table: str, item_id: str):
        if table not in DOCUMENT_TABLES:
            raise ValueError("unknown table")
        with self.lock:
            row = self.db.execute(
                f"SELECT payload FROM {table} WHERE id=?", (item_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def close(self):
        self.db.close()
