import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from . import config


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(obj):
    return json.dumps(obj, ensure_ascii=False)


@contextmanager
def db():
    config.RUNTIME.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.RUNTIME / "sdr.sqlite3", timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init():
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(
            """
        CREATE TABLE IF NOT EXISTS leads (
          id TEXT PRIMARY KEY, request_id TEXT UNIQUE, title TEXT NOT NULL,
          text TEXT NOT NULL, source TEXT NOT NULL, recording_id TEXT,
          result TEXT NOT NULL, analysis TEXT NOT NULL, status TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL REFERENCES leads(id),
          reviewer TEXT NOT NULL, note TEXT NOT NULL, decision TEXT NOT NULL,
          before_json TEXT NOT NULL, after_json TEXT NOT NULL, from_version INTEGER NOT NULL,
          verification_source TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS aliases (
          id INTEGER PRIMARY KEY AUTOINCREMENT, alias TEXT NOT NULL, company_name TEXT NOT NULL,
          area TEXT NOT NULL, industry TEXT NOT NULL, source TEXT NOT NULL,
          reviewer TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(alias, area, industry, company_name)
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, status TEXT NOT NULL,
          result TEXT, error TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS uploads (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
          extension TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        """
        )


def unpack(row):
    obj = dict(row)
    obj["result"] = json.loads(obj["result"])
    obj["analysis"] = json.loads(obj["analysis"])
    return obj
