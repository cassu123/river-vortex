"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/timers.py
Purpose:     Manages voice-activated kitchen timers and alarms. Each timer
             counts down independently in the background; when it elapses,
             an optional callback fires (e.g., to play a chime through the
             speaker) and a `timer_done` event is broadcast to the frontend
             over the WebSocket hub. Driven by River Song via
             core/timers_api.py — Vortex owns the countdown state.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.presenter import presenter, timer_done_phrase
from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)


class TimerManager:
    """
    Tracks active countdown timers/alarms for this unit.

    Usage:
        manager = TimerManager(on_timer_done=lambda t: speaker.play_chime("done"))
        timer = await manager.create_timer(600, label="Pasta")
        await manager.cancel_timer(timer["id"])
        await manager.stop()  # on shutdown
    """

    def __init__(self, on_timer_done: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        """
        Initialize TimerManager.

        Args:
            on_timer_done: Optional callback invoked with the expired timer's
                            dict whenever a timer reaches zero. Called
                            synchronously — exceptions are logged and ignored.
        """
        self._timers: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._on_timer_done = on_timer_done

    async def create_timer(self, duration_seconds: int, label: str = "Timer") -> Dict[str, Any]:
        """
        Start a new countdown timer.

        Args:
            duration_seconds: How long until the timer elapses. Must be positive.
            label:            Human-readable name (e.g., "Pasta", "Nap").

        Returns:
            The new timer's public dict (id, label, duration_seconds,
            ends_at, remaining_seconds).

        Raises:
            ValueError: If duration_seconds is not positive.
        """
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive.")

        timer_id = uuid.uuid4().hex[:8]
        timer = {
            "id": timer_id,
            "label": label,
            "duration_seconds": duration_seconds,
            "ends_at": time.time() + duration_seconds,
        }
        self._timers[timer_id] = timer
        self._tasks[timer_id] = asyncio.create_task(
            self._run_timer(timer_id, duration_seconds), name=f"timer-{timer_id}"
        )

        logger.info("Timer '%s' created: %ds (id=%s).", label, duration_seconds, timer_id)
        await self._broadcast_timers()
        return self._public(timer)

    async def cancel_timer(self, timer_id: str) -> bool:
        """
        Cancel an active timer before it elapses.

        Args:
            timer_id: The timer's ID, as returned by create_timer().

        Returns:
            True if a timer with that ID was found and cancelled, False otherwise.
        """
        timer = self._timers.pop(timer_id, None)
        task = self._tasks.pop(timer_id, None)
        if task:
            task.cancel()
        if timer is None:
            return False

        logger.info("Timer '%s' (id=%s) cancelled.", timer.get("label"), timer_id)
        await self._broadcast_timers()
        return True

    def list_timers(self) -> List[Dict[str, Any]]:
        """Return the public dict for every active timer, with remaining_seconds updated."""
        return [self._public(timer) for timer in self._timers.values()]

    async def stop(self) -> None:
        """Cancel all active timers. Called during shutdown."""
        for task in self._tasks.values():
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self._timers.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_timer(self, timer_id: str, duration_seconds: int) -> None:
        """Sleep for the timer's duration, then fire completion side effects."""
        try:
            await asyncio.sleep(duration_seconds)
        except asyncio.CancelledError:
            return

        timer = self._timers.pop(timer_id, None)
        self._tasks.pop(timer_id, None)
        if timer is None:
            return

        logger.info("Timer '%s' (id=%s) finished.", timer.get("label"), timer_id)
        # Spoken even on units with a screen — a timer you have to be looking
        # at the display to notice is no use in a kitchen.
        await presenter.present(
            {"type": "timer_done", "timer": self._public(timer)},
            speech=timer_done_phrase(timer),
            speak_on_screen=True,
        )
        await self._broadcast_timers()

        if self._on_timer_done:
            try:
                self._on_timer_done(timer)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("on_timer_done callback failed: %s", exc)

    async def _broadcast_timers(self) -> None:
        """Broadcast the full list of active timers to all frontend clients."""
        await ws_hub.broadcast({"type": "timers_update", "timers": self.list_timers()})

    @staticmethod
    def _public(timer: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of `timer` with a freshly computed `remaining_seconds`."""
        remaining = max(0, round(timer["ends_at"] - time.time()))
        return {**timer, "remaining_seconds": remaining}
