"""Event log for errors, warnings and info messages (part of F10).

Active errors (``active = 1``) are shown on the admin dashboard until a
technician resolves them; every entry stays in the log for remote diagnostics.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import now_iso

INFO, WARNING, ERROR = "INFO", "WARNING", "ERROR"

# Faults a technician can simulate in the demo, mapped to what they block.
FAULTS = {
    "Grinder Jammed": "coffee",       # blocks drinks that need coffee
    "Water Heater Fault": "hot",      # blocks hot drinks
    "Milk Frother Fault": "milk",     # blocks drinks with milk
    "Payment Terminal Offline": "none",
}


@dataclass(frozen=True)
class Event:
    """One row of the event log."""

    id: int
    timestamp: str
    level: str
    source: str
    message: str
    active: bool


def log(conn: sqlite3.Connection, level: str, source: str, message: str,
        active: bool = False) -> int:
    """Append an entry to the event log.

    Args:
        conn: open database connection.
        level: ``INFO``, ``WARNING`` or ``ERROR``.
        source: subsystem that raised it (e.g. ``"Inventory"``, ``"Grinder"``).
        message: human-readable text shown on the dashboard.
        active: True for faults that stay on the dashboard until resolved.

    Returns:
        int: id of the new log entry.
    """
    cur = conn.execute(
        "INSERT INTO event_log (timestamp, level, source, message, active) VALUES (?,?,?,?,?)",
        (now_iso(), level, source, message, int(active)),
    )
    conn.commit()
    return int(cur.lastrowid)


def recent(conn: sqlite3.Connection, limit: int = 200, level: str | None = None) -> list[Event]:
    """Return the newest log entries, optionally filtered by level.

    Args:
        conn: open database connection.
        limit: maximum number of entries.
        level: only return this level, or all levels if None.

    Returns:
        list[Event]: newest first.
    """
    if level:
        rows = conn.execute(
            "SELECT * FROM event_log WHERE level = ? ORDER BY id DESC LIMIT ?", (level, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM event_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [Event(r["id"], r["timestamp"], r["level"], r["source"], r["message"],
                  bool(r["active"])) for r in rows]


def active_errors(conn: sqlite3.Connection) -> list[Event]:
    """Return all unresolved (active) faults.

    Args:
        conn: open database connection.

    Returns:
        list[Event]: active entries, oldest first.
    """
    rows = conn.execute("SELECT * FROM event_log WHERE active = 1 ORDER BY id").fetchall()
    return [Event(r["id"], r["timestamp"], r["level"], r["source"], r["message"], True)
            for r in rows]


def has_active(conn: sqlite3.Connection, message: str) -> bool:
    """Check whether a fault with this exact message is currently active.

    Args:
        conn: open database connection.
        message: fault text, e.g. ``"Grinder Jammed"``.

    Returns:
        bool: True if it is active.
    """
    row = conn.execute(
        "SELECT 1 FROM event_log WHERE active = 1 AND message = ? LIMIT 1", (message,)
    ).fetchone()
    return row is not None


def resolve(conn: sqlite3.Connection, event_id: int) -> None:
    """Mark an active fault as resolved and log the resolution.

    Args:
        conn: open database connection.
        event_id: id of the active entry.

    Returns:
        None.
    """
    row = conn.execute("SELECT message, source FROM event_log WHERE id = ?", (event_id,)).fetchone()
    conn.execute("UPDATE event_log SET active = 0 WHERE id = ?", (event_id,))
    conn.commit()
    if row:
        log(conn, INFO, row["source"], f"Resolved: {row['message']}")
