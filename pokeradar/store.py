"""Atomic, append-only audit log and restart-safe dry-run outbox."""

from contextlib import contextmanager
import hashlib
import json
import sqlite3

from .core import PRODUCT, eligible

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, checked_at TEXT,
 status TEXT NOT NULL, raw TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY, observation_id INTEGER NOT NULL REFERENCES observations(id),
 created_at TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, observation_id INTEGER NOT NULL REFERENCES observations(id),
 dedupe_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monitor_state (
 rule TEXT PRIMARY KEY, watermark TEXT, armed INTEGER NOT NULL, episode INTEGER NOT NULL);
"""


@contextmanager
def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(SCHEMA)
    for table in ("observations", "decisions", "outbox"):
        for operation in ("UPDATE", "DELETE"):
            connection.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation}
                BEFORE {operation} ON {table} BEGIN
                SELECT RAISE(ABORT, 'append-only audit table'); END""")
    try:
        yield connection
    finally:
        connection.close()


def ingest(connection, raw, observation, demo_rule=False):
    rule = "fixture-usd100-v1" if demo_rule else "unverified-v1"
    now = observation["received_at"]
    # Serialize state decisions and outbox insertion across independent processes.
    connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute(
            "INSERT INTO observations(recorded_at,checked_at,status,raw,payload) VALUES(?,?,?,?,?)",
            (now, observation["checked_at"], observation["status"], raw, json.dumps(observation)))
        observation_id = cursor.lastrowid
        connection.execute("INSERT OR IGNORE INTO monitor_state VALUES(?,NULL,1,0)", (rule,))
        state = connection.execute("SELECT * FROM monitor_state WHERE rule=?", (rule,)).fetchone()
        watermark, armed, episode = state["watermark"], state["armed"], state["episode"]
        checked = observation["checked_at"]
        ordered = checked is not None and (watermark is None or checked > watermark)
        allowed, reason = eligible(observation, demo_rule)
        action = "suppressed"
        if not ordered:
            reason = "duplicate or out-of-order timestamp"
        else:
            # Failed/uncertain observations cannot rearm an existing stock episode.
            if observation["fresh"] and observation["identity_ok"]:
                watermark = checked
                if observation["status"] == "sold_out" and not armed:
                    armed, episode = 1, episode + 1
            if allowed and armed:
                key = hashlib.sha256(f"{PRODUCT.id}:{rule}:{episode}".encode()).hexdigest()
                payload = dict(mode="fixture", dry_run=True, label="SYNTHETIC — NOT A PURCHASE SIGNAL",
                               product_id=PRODUCT.id, sku=PRODUCT.sku, url=PRODUCT.url,
                               checked_at=checked, decided_at=now,
                               price_cents=observation["price_cents"], currency="USD",
                               rule=rule, episode=episode)
                connection.execute("INSERT INTO outbox(observation_id,dedupe_key,payload) VALUES(?,?,?)",
                                   (observation_id, key, json.dumps(payload)))
                armed, action = 0, "dry_run_alert"
            elif allowed:
                reason = "stock episode already alerted"
        connection.execute("UPDATE monitor_state SET watermark=?,armed=?,episode=? WHERE rule=?",
                           (watermark, armed, episode, rule))
        connection.execute("INSERT INTO decisions(observation_id,created_at,action,reason) VALUES(?,?,?,?)",
                           (observation_id, now, action, reason))
        connection.commit()
        return dict(observation_id=observation_id, status=observation["status"], action=action, reason=reason)
    except Exception:
        connection.rollback()
        raise
