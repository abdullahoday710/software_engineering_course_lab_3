"""Automatic transaction recording and history (feature F6)."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from .catalog import Customization, Drink
from .db import now_iso


@dataclass(frozen=True)
class Transaction:
    """One completed purchase including its customisation."""

    id: int
    user_id: int | None
    drink_id: int
    drink_name: str
    custom: Customization
    price: float
    payment_method: str
    payment_ref: str
    offline: bool
    synced: bool
    timestamp: str


def _row_to_tx(row: sqlite3.Row) -> Transaction:
    """Map a ``transactions`` row to a :class:`Transaction`.

    Args:
        row: database row.

    Returns:
        Transaction: the record.
    """
    custom = Customization(milk=row["milk"], strength=row["strength"],
                           temperature=row["temperature"], syrup=row["syrup"],
                           syrup_shots=row["syrup_shots"], extra_shot=bool(row["extra_shot"]))
    return Transaction(row["id"], row["user_id"], row["drink_id"], row["drink_name"], custom,
                       row["price"], row["payment_method"], row["payment_ref"],
                       bool(row["offline"]), bool(row["synced"]), row["timestamp"])


def record(conn: sqlite3.Connection, user_id: int | None, drink: Drink, custom: Customization,
           price: float, payment_method: str, payment_ref: str, offline: bool = False,
           timestamp: str | None = None) -> Transaction:
    """Store a completed transaction with all customisation parameters.

    Called automatically after the payment is approved and the drink dispensed.

    Args:
        conn: open database connection.
        user_id: logged-in user, or None for an anonymous customer.
        drink: dispensed drink.
        custom: its customisation.
        price: amount charged in SEK.
        payment_method: e.g. ``"Card"``, ``"Apple Pay"``, ``"Prepaid card"``.
        payment_ref: approval reference from the payment gateway.
        offline: True if the payment was stored offline (not yet settled).
        timestamp: ISO time; defaults to now (tests pass fixed times).

    Returns:
        Transaction: the stored record.
    """
    cur = conn.execute(
        "INSERT INTO transactions (user_id, drink_id, drink_name, milk, strength, temperature,"
        " syrup, syrup_shots, extra_shot, price, payment_method, payment_ref, offline, synced,"
        " timestamp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, drink.id, drink.name, custom.milk, custom.strength, custom.temperature,
         custom.syrup, custom.syrup_shots, int(custom.extra_shot), price, payment_method,
         payment_ref, int(offline), int(not offline), timestamp or now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_tx(row)


def history(conn: sqlite3.Connection, user_id: int | None = None,
            limit: int = 100) -> list[Transaction]:
    """Return recent transactions, for one user or for the whole machine.

    Args:
        conn: open database connection.
        user_id: filter by user; None returns all transactions.
        limit: maximum rows.

    Returns:
        list[Transaction]: newest first.
    """
    if user_id is None:
        rows = conn.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [_row_to_tx(r) for r in rows]


def drink_counts(conn: sqlite3.Connection, user_id: int) -> Counter:
    """Count how often a user ordered each drink (input for recommendations).

    Args:
        conn: open database connection.
        user_id: the user.

    Returns:
        Counter: drink_id -> number of orders.
    """
    rows = conn.execute("SELECT drink_id, COUNT(*) AS n FROM transactions WHERE user_id = ?"
                        " GROUP BY drink_id", (user_id,)).fetchall()
    return Counter({r["drink_id"]: r["n"] for r in rows})


def unsynced(conn: sqlite3.Connection) -> list[Transaction]:
    """Return offline payments that still have to be uploaded.

    Args:
        conn: open database connection.

    Returns:
        list[Transaction]: oldest first.
    """
    rows = conn.execute("SELECT * FROM transactions WHERE synced = 0 ORDER BY id").fetchall()
    return [_row_to_tx(r) for r in rows]


def mark_synced(conn: sqlite3.Connection, tx_ids: list[int]) -> None:
    """Mark offline transactions as uploaded to the payment processor.

    Args:
        conn: open database connection.
        tx_ids: transaction ids.

    Returns:
        None.
    """
    conn.executemany("UPDATE transactions SET synced = 1 WHERE id = ?", [(i,) for i in tx_ids])
    conn.commit()
