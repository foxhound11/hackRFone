"""
emitter_db.py — Persistent SQLite storage for observed RF emitters.
Tracks every signal across sessions with full history and fingerprints.

NEW FILE — can be deleted to revert this feature.
"""
import sqlite3
import json
import time
from datetime import datetime, timezone

DB_FILE = "emitters.db"

def _get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """Create the emitters table if it doesn't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS emitters (
            freq_key TEXT PRIMARY KEY,
            freq_mhz REAL NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            total_hits INTEGER DEFAULT 1,
            max_snr REAL DEFAULT 0,
            avg_snr REAL DEFAULT 0,
            max_power REAL DEFAULT -100,
            agent_label TEXT DEFAULT '',
            user_label TEXT DEFAULT '',
            is_baseline INTEGER DEFAULT 0,
            fingerprint TEXT DEFAULT '{}',
            threat_level TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            freq_mhz REAL NOT NULL,
            event_type TEXT NOT NULL,
            snr REAL DEFAULT 0,
            details TEXT DEFAULT ''
        );
    """)
    conn.close()

def upsert_emitter(freq_mhz, snr_db, power_db, agent_label="", threat_level=""):
    """Insert or update an emitter record."""
    freq_key = f"{freq_mhz:.1f}"
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM emitters WHERE freq_key=?", (freq_key,)).fetchone()
    
    if existing:
        new_hits = existing["total_hits"] + 1
        new_avg = ((existing["avg_snr"] * existing["total_hits"]) + snr_db) / new_hits
        new_max_snr = max(existing["max_snr"], snr_db)
        new_max_power = max(existing["max_power"], power_db)
        new_label = agent_label if agent_label else existing["agent_label"]
        # Do not let a frequency guess overwrite a confirmed protocol decode
        if existing["agent_label"].startswith("CONFIRMED:") and not agent_label.startswith("CONFIRMED:"):
            new_label = existing["agent_label"]
        new_threat = threat_level if threat_level else existing["threat_level"]
        conn.execute("""
            UPDATE emitters SET last_seen=?, total_hits=?, max_snr=?, avg_snr=?,
            max_power=?, agent_label=?, threat_level=?
            WHERE freq_key=?
        """, (now, new_hits, new_max_snr, round(new_avg, 2), new_max_power,
              new_label, new_threat, freq_key))
    else:
        conn.execute("""
            INSERT INTO emitters (freq_key, freq_mhz, first_seen, last_seen, total_hits,
            max_snr, avg_snr, max_power, agent_label, threat_level)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """, (freq_key, freq_mhz, now, now, snr_db, snr_db, power_db, agent_label, threat_level))
    
    conn.commit()
    conn.close()

def log_timeline_event(freq_mhz, event_type, snr=0, details=""):
    """Log a timeline event for the heatmap."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute("""
        INSERT INTO timeline (timestamp, freq_mhz, event_type, snr, details)
        VALUES (?, ?, ?, ?, ?)
    """, (now, freq_mhz, event_type, snr, details))
    conn.commit()
    conn.close()

def mark_all_as_baseline():
    """Mark every currently known emitter as baseline (used by --learn mode)."""
    conn = _get_conn()
    conn.execute("UPDATE emitters SET is_baseline=1")
    conn.commit()
    conn.close()

def get_all_emitters():
    """Return all emitters as a list of dicts."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM emitters ORDER BY last_seen DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_baseline_freqs():
    """Return set of freq_keys that are marked as baseline."""
    conn = _get_conn()
    rows = conn.execute("SELECT freq_key FROM emitters WHERE is_baseline=1").fetchall()
    conn.close()
    return {r["freq_key"] for r in rows}

def get_novel_emitters():
    """Return emitters that are NOT baseline."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM emitters WHERE is_baseline=0 ORDER BY last_seen DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_timeline(limit=200):
    """Return recent timeline events."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM timeline ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def update_fingerprint(freq_mhz, fingerprint_dict):
    """Store signal fingerprint for an emitter."""
    freq_key = f"{freq_mhz:.1f}"
    conn = _get_conn()
    conn.execute("UPDATE emitters SET fingerprint=? WHERE freq_key=?",
                 (json.dumps(fingerprint_dict), freq_key))
    conn.commit()
    conn.close()

def get_emitter_count():
    """Return count of all emitters."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM emitters").fetchone()[0]
    conn.close()
    return count

def get_baseline_count():
    """Return count of baseline emitters."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM emitters WHERE is_baseline=1").fetchone()[0]
    conn.close()
    return count


# Auto-init on import
init_db()
