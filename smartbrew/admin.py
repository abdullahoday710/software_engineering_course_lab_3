"""Secure administrative mode access (feature F10).

Technicians enter admin mode with a physical key, an NFC master card or a PIN.
Secrets are stored hashed in the ``settings`` table. Three wrong attempts lock
access for :data:`LOCKOUT_SECONDS`.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Callable

from . import events
from .security import verify_secret

MAX_ATTEMPTS = 3
LOCKOUT_SECONDS = 30
PHYSICAL_KEY_ID = "KEY-SB-SERVICE"


class AdminGate:
    """Checks admin credentials and enforces the lockout."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.monotonic) -> None:
        """Create the gate.

        Args:
            conn: open database connection.
            clock: time source in seconds (injectable for tests).

        Returns:
            None.
        """
        self.conn = conn
        self.clock = clock
        self.failed_attempts = 0
        self.locked_until = 0.0

    def _setting(self, key: str) -> str:
        """Read one value from the ``settings`` table.

        Args:
            key: setting name.

        Returns:
            str: stored value.
        """
        return self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()[0]

    def lock_remaining(self) -> int:
        """Seconds left in the current lockout.

        Returns:
            int: 0 when not locked.
        """
        return max(0, int(round(self.locked_until - self.clock())))

    def _fail(self, how: str) -> tuple[bool, str]:
        """Register a failed attempt and lock after too many.

        Args:
            how: credential type, used in the log message.

        Returns:
            tuple[bool, str]: always (False, user-facing message).
        """
        self.failed_attempts += 1
        events.log(self.conn, events.WARNING, "Admin", f"Failed admin login ({how})")
        if self.failed_attempts >= MAX_ATTEMPTS:
            self.failed_attempts = 0
            self.locked_until = self.clock() + LOCKOUT_SECONDS
            events.log(self.conn, events.WARNING, "Admin",
                       f"Admin access locked for {LOCKOUT_SECONDS}s after {MAX_ATTEMPTS} failures")
            return False, f"Access denied. Locked for {LOCKOUT_SECONDS} seconds."
        return False, f"Access denied ({MAX_ATTEMPTS - self.failed_attempts} attempts left)."

    def _ok(self, how: str) -> tuple[bool, str]:
        """Register a successful login.

        Args:
            how: credential type, used in the log message.

        Returns:
            tuple[bool, str]: (True, welcome message).
        """
        self.failed_attempts = 0
        events.log(self.conn, events.INFO, "Admin", f"Admin mode entered via {how}")
        return True, "Admin mode unlocked."

    def try_pin(self, pin: str) -> tuple[bool, str]:
        """Attempt access with the technician PIN.

        Args:
            pin: digits typed on the keypad.

        Returns:
            tuple[bool, str]: (granted, message).
        """
        if self.lock_remaining():
            return False, f"Locked. Try again in {self.lock_remaining()} s."
        if verify_secret(pin, self._setting("admin_pin_hash"), self._setting("admin_pin_salt")):
            return self._ok("PIN")
        return self._fail("PIN")

    def try_master_card(self, card_id: str) -> tuple[bool, str]:
        """Attempt access by tapping the NFC master card.

        Args:
            card_id: identifier read from the card.

        Returns:
            tuple[bool, str]: (granted, message).
        """
        if self.lock_remaining():
            return False, f"Locked. Try again in {self.lock_remaining()} s."
        if verify_secret(card_id.strip(), self._setting("admin_card_hash"),
                         self._setting("admin_card_salt")):
            return self._ok("NFC master card")
        return self._fail("NFC card")

    def try_physical_key(self, key_id: str) -> tuple[bool, str]:
        """Attempt access by turning the physical service key.

        Args:
            key_id: identifier reported by the key switch.

        Returns:
            tuple[bool, str]: (granted, message). Not subject to lockout.
        """
        if key_id == PHYSICAL_KEY_ID:
            return self._ok("physical key")
        return False, "Wrong key."
