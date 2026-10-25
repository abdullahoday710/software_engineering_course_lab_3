"""Simulated payment gateway (feature F5).

Supports EMV/contactless debit and credit cards, Apple Pay, Google Pay and the
internal prepaid employee card. No real money moves: card numbers are checked
with the Luhn algorithm and a few published-style test numbers trigger
specific outcomes, so every path can be demonstrated.

Offline behaviour (graceful fallback): cards are approved as "offline stored"
transactions up to a limit and uploaded later; wallets need the network and
are declined; prepaid cards work because their balance is held locally.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass

CARD, APPLE_PAY, GOOGLE_PAY, PREPAID = "Card", "Apple Pay", "Google Pay", "Prepaid card"
METHODS = [CARD, APPLE_PAY, GOOGLE_PAY, PREPAID]

OFFLINE_CARD_LIMIT = 100.0  # SEK, floor limit for store-and-forward
DECLINED_CARD = "4000000000000002"
INSUFFICIENT_CARD = "4000000000009995"
TEST_CARDS = {
    "4242424242424242": "Visa test card (approved)",
    "5555555555554444": "Mastercard test card (approved)",
    DECLINED_CARD: "Always declined",
    INSUFFICIENT_CARD: "Insufficient funds",
}


@dataclass(frozen=True)
class PaymentResult:
    """Outcome of a payment attempt."""

    approved: bool
    message: str
    reference: str = ""
    offline: bool = False


def luhn_valid(number: str) -> bool:
    """Validate a card number with the Luhn checksum.

    Args:
        number: card number, spaces and dashes are ignored.

    Returns:
        bool: True if 13-19 digits and the checksum is correct.
    """
    digits = [c for c in number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19 or len(digits) != len(number.replace(" ", "").replace("-", "")):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _reference(prefix: str) -> str:
    """Create a random approval reference.

    Args:
        prefix: short tag, e.g. ``"ON"`` or ``"OFF"``.

    Returns:
        str: reference such as ``"ON-7F3A9C21"``.
    """
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def pay_card(number: str, amount: float, online: bool) -> PaymentResult:
    """Charge an EMV chip / contactless debit or credit card.

    Args:
        number: card number (test numbers in :data:`TEST_CARDS`).
        amount: amount in SEK.
        online: whether the payment processor is reachable.

    Returns:
        PaymentResult: approval or decline with a user-facing message.
    """
    clean = number.replace(" ", "").replace("-", "")
    if not luhn_valid(number):
        return PaymentResult(False, "Card read error: invalid card number.")
    if not online:
        if amount > OFFLINE_CARD_LIMIT:
            return PaymentResult(False, f"Offline limit is {OFFLINE_CARD_LIMIT:.0f} SEK. Please use a prepaid card.")
        return PaymentResult(True, "Approved offline - will be settled when the network is back.",
                             _reference("OFF"), offline=True)
    if clean == DECLINED_CARD:
        return PaymentResult(False, "Card declined by issuer.")
    if clean == INSUFFICIENT_CARD:
        return PaymentResult(False, "Declined: insufficient funds.")
    return PaymentResult(True, "Card approved.", _reference("ON"))


def pay_wallet(wallet: str, amount: float, online: bool, token_ok: bool = True) -> PaymentResult:
    """Charge Apple Pay or Google Pay.

    Args:
        wallet: :data:`APPLE_PAY` or :data:`GOOGLE_PAY`.
        amount: amount in SEK.
        online: whether the wallet processor is reachable.
        token_ok: simulates the phone authorising (False = user cancelled).

    Returns:
        PaymentResult: approval or decline.
    """
    if wallet not in (APPLE_PAY, GOOGLE_PAY):
        return PaymentResult(False, "Unknown wallet.")
    if not online:
        return PaymentResult(False, f"{wallet} is unavailable offline. Please tap a card instead.")
    if not token_ok:
        return PaymentResult(False, f"{wallet} authorisation cancelled on the phone.")
    return PaymentResult(True, f"{wallet} approved.", _reference("WAL"))


def pay_prepaid(conn: sqlite3.Connection, card_id: str, amount: float) -> PaymentResult:
    """Charge an internal prepaid employee card (balance stored on the machine).

    Args:
        conn: open database connection.
        card_id: employee card identifier linked to a user.
        amount: amount in SEK.

    Returns:
        PaymentResult: approval (balance deducted) or decline.
    """
    row = conn.execute("SELECT id, prepaid_balance FROM users WHERE card_id = ?",
                       (card_id.strip(),)).fetchone()
    if row is None:
        return PaymentResult(False, "Prepaid card not recognised.")
    if row["prepaid_balance"] < amount:
        return PaymentResult(False, f"Insufficient prepaid balance ({row['prepaid_balance']:.2f} SEK).")
    conn.execute("UPDATE users SET prepaid_balance = prepaid_balance - ? WHERE id = ?",
                 (amount, row["id"]))
    conn.commit()
    return PaymentResult(True, f"Prepaid card approved. New balance "
                               f"{row['prepaid_balance'] - amount:.2f} SEK.", _reference("PRE"))


def process(conn: sqlite3.Connection, method: str, amount: float, online: bool,
            card_number: str = "", card_id: str = "", token_ok: bool = True) -> PaymentResult:
    """Dispatch a payment to the right handler.

    Args:
        conn: open database connection (needed for prepaid cards).
        method: one of :data:`METHODS`.
        amount: amount in SEK (must be > 0).
        online: network/processor availability.
        card_number: card number for :data:`CARD`.
        card_id: employee card id for :data:`PREPAID`.
        token_ok: wallet authorisation result for Apple/Google Pay.

    Returns:
        PaymentResult: outcome.
    """
    if amount <= 0:
        return PaymentResult(False, "Invalid amount.")
    if method == CARD:
        return pay_card(card_number, amount, online)
    if method in (APPLE_PAY, GOOGLE_PAY):
        return pay_wallet(method, amount, online, token_ok)
    if method == PREPAID:
        return pay_prepaid(conn, card_id, amount)
    return PaymentResult(False, "Unsupported payment method.")
