"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/routines.py
Purpose:     Guided routine session management — step-by-step walkthroughs
             such as cooking mode, workout mode, or a bedtime checklist.
             River Song supplies the title and steps (and recognizes
             follow-up commands like "next step" / "repeat" / "done");
             Vortex owns the on-screen step display, ducks/restores
             background media on Home Assistant media players for the
             duration, and broadcasts step updates over the WebSocket hub.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.constants import ROUTINE_DUCK_VOLUME_LEVEL
from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)


class RoutineError(Exception):
    """Raised for invalid routine operations (e.g., advancing with none active)."""


class RoutineSession:
    """
    Manages the single guided routine active on this unit, if any.

    Usage:
        session = RoutineSession(device_control=dc, on_mode_change=screen.set_mode)
        await session.start("Spaghetti Carbonara", [
            {"instruction": "Boil a large pot of salted water."},
            {"instruction": "Cook the pasta for 9 minutes.", "duration_seconds": 540},
            {"instruction": "Whisk eggs, pecorino, and black pepper in a bowl."},
        ])
        await session.next_step()
        await session.stop()
    """

    def __init__(
        self,
        device_control: Optional[Any] = None,
        on_mode_change: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """
        Initialize RoutineSession.

        Args:
            device_control: Optional home_assistant.device_control.DeviceControl
                             used to duck/restore media player volume. If None
                             (e.g., no Home Assistant configured), ducking is skipped.
            on_mode_change:  Optional async callable(display_mode: str) used to
                             switch the on-device display — typically
                             ScreenManager.set_mode. If None, the display is
                             left as-is.
        """
        self._device_control = device_control
        self._on_mode_change = on_mode_change
        self._title: str = ""
        self._steps: List[Dict[str, Any]] = []
        self._step_index: int = 0
        self._active: bool = False
        self._ducked_players: Dict[str, float] = {}

    @property
    def active(self) -> bool:
        """Return True if a routine is currently in progress."""
        return self._active

    async def start(self, title: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Begin a new guided routine, replacing any in-progress routine.

        Args:
            title: Human-readable routine name (e.g., a recipe name).
            steps: Ordered list of step dicts. Each must have an
                   "instruction" string, and may include an optional
                   "duration_seconds" (e.g., for a cook/rest timer).

        Returns:
            The new routine state (see get_state()).

        Raises:
            RoutineError: If `steps` is empty.
        """
        if not steps:
            raise RoutineError("A routine requires at least one step.")

        if self._active:
            logger.info("Replacing in-progress routine '%s' with '%s'.", self._title, title)
            await self._restore_media()

        self._title = title
        self._steps = steps
        self._step_index = 0
        self._active = True

        await self._duck_media()
        await self._set_mode("routine")
        await self._broadcast()
        logger.info("Routine '%s' started (%d step(s)).", title, len(steps))
        return self.get_state()

    async def next_step(self) -> Dict[str, Any]:
        """
        Advance to the next step, or stop the routine if already on the last step.

        Returns:
            The updated routine state.

        Raises:
            RoutineError: If no routine is active.
        """
        self._require_active()
        if self._step_index < len(self._steps) - 1:
            self._step_index += 1
            await self._broadcast()
            return self.get_state()
        return await self.stop()

    async def previous_step(self) -> Dict[str, Any]:
        """
        Go back to the previous step (no-op on the first step).

        Returns:
            The updated routine state.

        Raises:
            RoutineError: If no routine is active.
        """
        self._require_active()
        if self._step_index > 0:
            self._step_index -= 1
            await self._broadcast()
        return self.get_state()

    async def stop(self) -> Dict[str, Any]:
        """
        End the active routine: restores ducked media volumes and switches
        the display back to ambient mode.

        Returns:
            The (now inactive) routine state.

        Raises:
            RoutineError: If no routine is active.
        """
        self._require_active()
        self._active = False
        await self._restore_media()
        await self._set_mode("ambient")
        await self._broadcast()
        logger.info("Routine '%s' stopped.", self._title)
        return self.get_state()

    def get_state(self) -> Dict[str, Any]:
        """
        Return the current routine state.

        Returns:
            Dict with `active` and, when a routine has been started at least
            once, `title`, `step_index`, `step_count`, `step`, and
            `is_last_step`.
        """
        if not self._steps:
            return {"active": False}

        return {
            "active": self._active,
            "title": self._title,
            "step_index": self._step_index,
            "step_count": len(self._steps),
            "step": self._steps[self._step_index],
            "is_last_step": self._step_index == len(self._steps) - 1,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _require_active(self) -> None:
        if not self._active:
            raise RoutineError("No routine is currently active.")

    async def _broadcast(self) -> None:
        await ws_hub.broadcast({"type": "routine_update", "routine": self.get_state()})

    async def _set_mode(self, mode: str) -> None:
        if self._on_mode_change:
            try:
                await self._on_mode_change(mode)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Failed to switch display to '%s': %s", mode, exc)

    async def _duck_media(self) -> None:
        """Lower the volume of any currently-playing media players, remembering their levels."""
        self._ducked_players = {}
        if not self._device_control:
            return

        try:
            players = await self._device_control.get_all_media_players()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not query media players for ducking: %s", exc)
            return

        for player in players:
            if player.get("state") != "playing":
                continue
            entity_id = player.get("entity_id")
            volume = player.get("attributes", {}).get("volume_level")
            if entity_id is None or volume is None:
                continue
            self._ducked_players[entity_id] = volume
            await self._device_control.set_media_volume(entity_id, ROUTINE_DUCK_VOLUME_LEVEL)

        if self._ducked_players:
            logger.info("Ducked %d media player(s) for routine.", len(self._ducked_players))

    async def _restore_media(self) -> None:
        """Restore the volume of any media players ducked by _duck_media()."""
        if not self._device_control or not self._ducked_players:
            self._ducked_players = {}
            return

        for entity_id, volume in self._ducked_players.items():
            await self._device_control.set_media_volume(entity_id, volume)

        logger.info("Restored volume for %d media player(s).", len(self._ducked_players))
        self._ducked_players = {}
