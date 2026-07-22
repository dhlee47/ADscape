"""SQLite connection + schema/taxonomy bootstrap for ADscape."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "adscape.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trials'"
    ).fetchone()
    if not existing:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    _load_taxonomy(conn)
    return conn


def _load_taxonomy(conn):
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    for bucket_id, bucket in taxonomy["buckets"].items():
        conn.execute(
            """
            INSERT INTO mechanism_buckets
                (bucket_id, description, pubmed_query, trial_keywords, preclinical_terms, representative_agents, source)
            VALUES (?, ?, ?, ?, ?, ?, 'seed')
            ON CONFLICT(bucket_id) DO UPDATE SET
                description = excluded.description,
                pubmed_query = excluded.pubmed_query,
                trial_keywords = excluded.trial_keywords,
                preclinical_terms = excluded.preclinical_terms,
                representative_agents = excluded.representative_agents
            """,
            (
                bucket_id,
                bucket["description"],
                bucket.get("pubmed_query"),
                json.dumps(bucket.get("trial_keywords", [])),
                json.dumps(bucket.get("preclinical_terms", [])),
                json.dumps(bucket.get("representative_agents", [])),
            ),
        )
    conn.commit()
