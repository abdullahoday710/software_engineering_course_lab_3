"""User accounts, login and preference profiles (feature F1)."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .catalog import MILK_OPTIONS
from .db import now_iso
from .security import hash_secret, verify_secret

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 6


class AccountError(ValueError):
    """Raised when account creation or login fails; the message is user-facing."""


@dataclass(frozen=True)
class User:
    """A registered user and their preference profile."""

    id: int
    name: str
    email: str
    card_id: str | None
    default_milk: str
    default_strength: int
    prepaid_balance: float


def _row_to_user(row: sqlite3.Row) -> User:
    """Map a ``users`` row to a :class:`User` (without secrets).

    Args:
        row: database row.

    Returns:
        User: public user data.
    """
    return User(row["id"], row["name"], row["email"], row["card_id"], row["default_milk"],
                row["default_strength"], row["prepaid_balance"])


def create_account(conn: sqlite3.Connection, name: str, email: str, password: str,
                   card_id: str | None = None) -> User:
    """Register a new user, optionally linked to an NFC/employee card.

    Args:
        conn: open database connection.
        name: display name (not empty).
        email: unique e-mail address used for login.
        password: at least 6 characters; stored only as a salted hash.
        card_id: optional NFC/employee card identifier for tap login.

    Returns:
        User: the created user.

    Raises:
        AccountError: invalid input, or e-mail/card already registered.
    """
    name, email = name.strip(), email.strip().lower()
    card_id = (card_id or "").strip() or None
    if not name:
        raise AccountError("Please enter your name.")
    if not EMAIL_RE.match(email):
        raise AccountError("Please enter a valid e-mail address.")
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Password must be at least {MIN_PASSWORD} characters.")
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise AccountError("This e-mail is already registered.")
    if card_id and conn.execute("SELECT 1 FROM users WHERE card_id = ?", (card_id,)).fetchone():
        raise AccountError("This card is already linked to another account.")
    pw_hash, salt = hash_secret(password)
    cur = conn.execute(
        "INSERT INTO users (name, email, pw_hash, salt, card_id, created_at) VALUES (?,?,?,?,?,?)",
        (name, email, pw_hash, salt, card_id, now_iso()),
    )
    conn.commit()
    return get_user(conn, int(cur.lastrowid))


def login_with_credentials(conn: sqlite3.Connection, email: str, password: str) -> User:
    """Log in with e-mail and password.

    Args:
        conn: open database connection.
        email: registered e-mail (case-insensitive).
        password: plain-text password.

    Returns:
        User: the logged-in user.

    Raises:
        AccountError: unknown e-mail or wrong password (same message for both).
    """
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    if row is None or not verify_secret(password, row["pw_hash"], row["salt"]):
        raise AccountError("Wrong e-mail or password.")
    return _row_to_user(row)


def login_with_card(conn: sqlite3.Connection, card_id: str) -> User:
    """Log in by tapping an NFC/employee card.

    Args:
        conn: open database connection.
        card_id: identifier read from the card.

    Returns:
        User: the user linked to the card.

    Raises:
        AccountError: card not linked to any account.
    """
    row = conn.execute("SELECT * FROM users WHERE card_id = ?", (card_id.strip(),)).fetchone()
    if row is None:
        raise AccountError("Card not recognised. Create an account and link this card first.")
    return _row_to_user(row)


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    """Load a user by id (fresh copy, e.g. after a balance change).

    Args:
        conn: open database connection.
        user_id: primary key.

    Returns:
        User: the user.

    Raises:
        AccountError: no such user.
    """
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AccountError("User not found.")
    return _row_to_user(row)


def update_preferences(conn: sqlite3.Connection, user_id: int, default_milk: str,
                       default_strength: int) -> User:
    """Store the user's preference profile.

    Args:
        conn: open database connection.
        user_id: the user.
        default_milk: preferred milk, one of the catalogue milk options.
        default_strength: preferred strength 1-5.

    Returns:
        User: updated user.

    Raises:
        AccountError: invalid milk or strength.
    """
    if default_milk not in MILK_OPTIONS[1:]:
        raise AccountError("Unknown milk type.")
    if not 1 <= int(default_strength) <= 5:
        raise AccountError("Strength must be between 1 and 5.")
    conn.execute("UPDATE users SET default_milk = ?, default_strength = ? WHERE id = ?",
                 (default_milk, int(default_strength), user_id))
    conn.commit()
    return get_user(conn, user_id)


def link_card(conn: sqlite3.Connection, user_id: int, card_id: str) -> User:
    """Link (or replace) the NFC/employee card of a user.

    Args:
        conn: open database connection.
        user_id: the user.
        card_id: new card identifier.

    Returns:
        User: updated user.

    Raises:
        AccountError: empty id or card linked to someone else.
    """
    card_id = card_id.strip()
    if not card_id:
        raise AccountError("Card ID is empty.")
    other = conn.execute("SELECT id FROM users WHERE card_id = ?", (card_id,)).fetchone()
    if other and other["id"] != user_id:
        raise AccountError("This card is already linked to another account.")
    conn.execute("UPDATE users SET card_id = ? WHERE id = ?", (card_id, user_id))
    conn.commit()
    return get_user(conn, user_id)
