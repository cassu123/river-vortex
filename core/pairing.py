"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/pairing.py
Purpose:     Pairing PIN management for first-run setup. While a unit is
             unconfigured, it generates a one-time numeric PIN that is shown
             on its display. The River Song app must echo this PIN back to
             the unit's setup API to prove the user is standing in front of
             the correct device before any credentials are exchanged.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import secrets
from typing import Optional

from core.constants import PAIRING_PIN_LENGTH
from core.presenter import presenter

logger = logging.getLogger(__name__)


class PairingSession:
    """
    Holds the current pairing PIN for an unconfigured unit.

    A new PIN is generated on demand (typically once at startup, the first
    time /setup/info is requested while unconfigured) and is cleared once
    pairing succeeds.
    """

    def __init__(self) -> None:
        """Initialize with no active PIN."""
        self._pin: Optional[str] = None

    def generate(self) -> str:
        """
        Generate a new random numeric pairing PIN and store it.

        Returns:
            The newly generated PIN as a zero-padded string of
            PAIRING_PIN_LENGTH digits.
        """
        self._pin = "".join(str(secrets.randbelow(10)) for _ in range(PAIRING_PIN_LENGTH))
        logger.info("Pairing PIN generated (shown on device display).")
        return self._pin

    @property
    def pin(self) -> Optional[str]:
        """Return the current PIN, or None if not yet generated."""
        return self._pin

    def verify(self, candidate: str) -> bool:
        """
        Check whether `candidate` matches the current pairing PIN.

        Uses a constant-time comparison to avoid timing side-channels.

        Args:
            candidate: The PIN submitted by the River Song app.

        Returns:
            True if a PIN has been generated and `candidate` matches it.
        """
        if self._pin is None:
            return False
        return secrets.compare_digest(self._pin, str(candidate))

    def clear(self) -> None:
        """Clear the current PIN (called once pairing succeeds)."""
        self._pin = None

    async def announce(self) -> None:
        """
        Make the current pairing PIN perceivable on this unit.

        A unit with a screen displays it. A Mini has nowhere to show it, so it
        reads the digits aloud — otherwise a screenless unit could never be
        set up at all, because the PIN would exist only in a log file.

        Digits are spaced so they are spoken individually ("four one seven
        two") rather than as one large number.
        """
        if self._pin is None:
            return

        spoken = " ".join(self._pin)
        await presenter.present(
            {"type": "pairing_pin", "pin": self._pin},
            speech=(
                f"To set me up, open River Song and enter the code {spoken}. "
                f"Again, {spoken}."
            ),
            speak_on_screen=False,  # a screen already shows it
        )


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton — import this everywhere
# ─────────────────────────────────────────────────────────────────────────────

pairing_session = PairingSession()
