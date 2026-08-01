"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/surfaces.py
Purpose:     The surface store — what a unit is currently being asked to show.

             A "surface" is a small declarative card descriptor: a kind, a
             payload, a priority and a lifetime. River Song decides WHAT is
             worth the screen right now (it knows the room, the time, who is
             home, what is cooking); the unit only decides HOW to draw it.

             That split is the whole point. Adding "show me the bin day the
             night before" becomes a server-side change, not a frontend
             release on every unit in the house.

             Surfaces are deliberately NOT persisted. They are a live view of
             what matters this minute — after a reboot River Song re-pushes
             whatever is still true, and a stale card from three hours ago is
             worse than a blank screen.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.presenter import presenter

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# The contract. Mirrored in frontend/src/surfaces/surfaceContract.js — change
# one and you must change the other.
# ─────────────────────────────────────────────────────────────────────────────

#: Card shapes the renderer knows how to draw. Every kind added here is a
#: permanent commitment, so the list stays short on purpose.
SURFACE_KINDS = ("note", "list", "stat", "media", "image", "alert", "confirm")

#: How insistent a surface is.
#:   ambient  — idle-time filler, shown only when nothing else wants the screen
#:   normal   — the usual "here is something useful now"
#:   high     — pushes past ambient content and wakes the screen
#:   critical — takes over the display entirely (doorbell, alarm, smoke)
SURFACE_PRIORITIES = ("ambient", "normal", "high", "critical")

#: Numeric weight, so surfaces can be compared. Higher wins.
PRIORITY_WEIGHT = {"ambient": 0, "normal": 1, "high": 2, "critical": 3}

#: Priorities that justify interrupting whatever is on screen.
INTERRUPTING_PRIORITIES = ("high", "critical")

#: Lifetime used when River Song does not specify one.
DEFAULT_TTL_SECONDS = 120

#: Upper bound on a lifetime. Nothing pins itself to the screen forever — a
#: surface that is still true will be re-pushed.
MAX_TTL_SECONDS = 86400

#: How many surfaces a unit will hold at once. Beyond this the lowest-priority
#: oldest ones are dropped, so a misbehaving caller cannot exhaust memory on a
#: box with 1GB of RAM.
MAX_SURFACES = 32


class SurfaceStore:
    """
    Holds the surfaces this unit has been asked to show.

    Usage:
        store = SurfaceStore()
        await store.push({"id": "garage", "kind": "alert", "priority": "high",
                          "title": "Garage door open", "ttl_seconds": 600})
        store.top()              # the surface that should be on screen
        await store.withdraw("garage")
    """

    def __init__(self, on_interrupt: Optional[Callable[[], Awaitable[None]]] = None) -> None:
        """
        Args:
            on_interrupt: Awaited when a high or critical surface arrives, to
                bring the screen back from screensaver or backlight-off. Wired
                to ScreenManager.wake by the orchestrator; left None on a
                screenless Mini and in tests.
        """
        self._surfaces: Dict[str, Dict[str, Any]] = {}
        self._on_interrupt = on_interrupt

    def set_interrupt_handler(
        self, handler: Optional[Callable[[], Awaitable[None]]]
    ) -> None:
        """Wire the screen-wake callback after construction (see core/main.py)."""
        self._on_interrupt = handler

    # ─────────────────────────────────────────────────────────────────────────
    # Reading
    # ─────────────────────────────────────────────────────────────────────────

    def all(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Return every live surface, most important first.

        Args:
            now: Unix timestamp to evaluate expiry against. Injectable so
                 tests do not have to sleep.

        Returns:
            Live surfaces sorted by priority then recency.
        """
        self._prune(now)
        return sorted(
            self._surfaces.values(),
            key=lambda s: (s["weight"], s["created_at"]),
            reverse=True,
        )

    def top(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Return the single surface that should be on screen, or None.

        Highest priority wins; ties go to the most recently pushed, because
        when two things matter equally the newer one is the news.
        """
        live = self.all(now)
        return live[0] if live else None

    # ─────────────────────────────────────────────────────────────────────────
    # Writing
    # ─────────────────────────────────────────────────────────────────────────

    async def push(self, raw: Dict[str, Any],
                   speech: Optional[str] = None) -> Dict[str, Any]:
        """
        Add or replace a surface and tell the frontend.

        Replacing by id rather than appending is what lets a surface update
        itself — "the garage is still open" must not stack up eight deep.

        Args:
            raw:    The descriptor. See normalise() for the accepted fields.
            speech: What River should say aloud, if anything. A screenless
                    Mini has no other way to deliver this, so an interrupting
                    surface carrying speech is spoken on every unit.

        Returns:
            The normalised surface as stored.
        """
        surface = self.normalise(raw)
        self._surfaces[surface["id"]] = surface
        self._enforce_capacity()

        # Something urgent is no use painted onto a screen whose backlight is
        # off. Wake first, so the card is already there when the panel lights.
        if surface["priority"] in INTERRUPTING_PRIORITIES and self._on_interrupt:
            try:
                await self._on_interrupt()
            except Exception as exc:  # pylint: disable=broad-except
                # A dead backlight must not swallow the card — a Mini has no
                # screen at all and still needs the announcement below.
                logger.error("Could not wake the screen for '%s': %s",
                             surface["id"], exc)

        await presenter.present(
            {"type": "surface", "surface": surface},
            speech=speech,
            # A screened unit stays quiet for ordinary cards — it can just show
            # them. High and critical are the ones you must notice without
            # looking at the panel, so those speak on every form factor.
            speak_on_screen=surface["priority"] in INTERRUPTING_PRIORITIES,
            interrupt=surface["priority"] == "critical",
        )
        return surface

    async def withdraw(self, surface_id: str) -> bool:
        """
        Remove a surface before it expires and tell the frontend.

        Args:
            surface_id: The id given when it was pushed.

        Returns:
            True if a surface was actually removed.
        """
        removed = self._surfaces.pop(str(surface_id), None) is not None
        if removed:
            await presenter.present(
                {"type": "surface_remove", "id": str(surface_id)}
            )
        return removed

    async def clear(self) -> None:
        """Drop everything. Used when a unit is unpaired or re-provisioned."""
        self._surfaces.clear()
        await presenter.present({"type": "surfaces_update", "surfaces": []})

    # ─────────────────────────────────────────────────────────────────────────
    # Normalisation
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def normalise(raw: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        """
        Turn a raw descriptor into a stored surface.

        Every field is defended. A malformed surface must degrade into
        something harmless rather than blanking a wall panel — the unit has no
        keyboard, so there is nowhere to recover from a crash.

        Args:
            raw: Descriptor as received from River Song.
            now: Unix timestamp to compute expiry from.

        Returns:
            A surface dict ready to store and broadcast.
        """
        now = time.time() if now is None else now

        kind = raw.get("kind")
        kind = kind if kind in SURFACE_KINDS else "note"

        priority = raw.get("priority")
        priority = priority if priority in SURFACE_PRIORITIES else "normal"

        surface_id = str(raw.get("id") or f"{kind}-{int(now * 1000)}")

        try:
            ttl = float(raw.get("ttl_seconds") or 0)
        except (TypeError, ValueError):
            ttl = 0.0
        if not 0 < ttl <= MAX_TTL_SECONDS:
            ttl = float(DEFAULT_TTL_SECONDS) if ttl <= 0 else float(MAX_TTL_SECONDS)

        items = raw.get("items")
        items = [str(i) for i in items[:8]] if isinstance(items, list) else []

        actions = raw.get("actions")
        actions = [a for a in actions[:3] if isinstance(a, dict)] \
            if isinstance(actions, list) else []

        value = raw.get("value")

        return {
            "id": surface_id,
            "kind": kind,
            "priority": priority,
            "weight": PRIORITY_WEIGHT[priority],
            "title": str(raw.get("title") or ""),
            "body": str(raw.get("body") or ""),
            "value": "" if value is None else str(value),
            "unit": str(raw.get("unit") or ""),
            "items": items,
            "image_url": str(raw.get("image_url") or ""),
            "icon": str(raw.get("icon") or ""),
            "actions": actions,
            "created_at": now,
            # Absolute expiry, computed once. Comparing against a deadline
            # survives a suspended process; counting down does not.
            "expires_at": now + ttl,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _prune(self, now: Optional[float] = None) -> None:
        """Drop anything past its lifetime."""
        now = time.time() if now is None else now
        expired = [sid for sid, s in self._surfaces.items() if s["expires_at"] <= now]
        for sid in expired:
            del self._surfaces[sid]

    def _enforce_capacity(self) -> None:
        """Keep the store bounded, shedding the least important oldest first."""
        if len(self._surfaces) <= MAX_SURFACES:
            return
        ordered = sorted(
            self._surfaces.values(),
            key=lambda s: (s["weight"], s["created_at"]),
        )
        for surface in ordered[: len(self._surfaces) - MAX_SURFACES]:
            logger.warning("Surface capacity reached; dropping '%s'.", surface["id"])
            del self._surfaces[surface["id"]]


# Module-level singleton — imported by the API layer, mirroring ws_hub.
surface_store = SurfaceStore()
