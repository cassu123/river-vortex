"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        display/notification_display.py
Purpose:     Notification management and display routing. Receives notifications
             from Home Assistant, River Song, and system events. Routes them to
             the ambient overlay, triggers audio alerts, and manages the
             notification queue with priority ordering and auto-dismiss.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Callable, List, Optional

from core.constants import NOTIFICATION_DISPLAY_DURATION, MAX_NOTIFICATIONS_DISPLAYED

logger = logging.getLogger(__name__)


def _schedule(coro, name: str = None):
    """
    Schedule a coroutine on the running event loop, if there is one.

    push() is a synchronous method that may be called from the API thread,
    from a test, or from a subsystem callback — contexts where no event loop
    is running. asyncio.create_task() raises RuntimeError there, which would
    propagate out of push() and lose the notification entirely.

    Args:
        coro: The coroutine to schedule.
        name: Optional task name for debugging.

    Returns:
        The created Task, or None if no loop was running (the coroutine is
        closed in that case so it does not leak an un-awaited warning).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop — skipping scheduled task '%s'.", name)
        coro.close()
        return None
    return loop.create_task(coro, name=name)


class NotificationPriority(IntEnum):
    """Notification priority levels. Higher value = higher priority."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class Notification:
    """Represents a single notification."""
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    source: str = "system"
    icon: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    auto_dismiss: bool = True
    dismiss_after: int = NOTIFICATION_DISPLAY_DURATION


class NotificationDisplay:
    """
    Manages the notification queue and display lifecycle.

    Notifications are sorted by priority. High-priority notifications
    trigger audio chimes. Urgent notifications interrupt the current
    display mode.

    Integrates with:
    - AmbientMode: pushes notifications to the ambient overlay
    - AudioManager: triggers chimes for high-priority notifications
    - ScreenManager: wakes the screen for urgent notifications
    """

    def __init__(
        self,
        ambient_mode=None,
        audio_manager=None,
        screen_manager=None,
    ) -> None:
        """
        Initialize NotificationDisplay.

        Args:
            ambient_mode:   AmbientMode instance for overlay updates.
            audio_manager:  AudioManager instance for chime playback.
            screen_manager: ScreenManager instance for screen wake.
        """
        self._ambient = ambient_mode
        self._audio = audio_manager
        self._screen = screen_manager
        self._queue: List[Notification] = []
        self._dismiss_tasks: dict = {}

    def push(self, notification: Notification) -> str:
        """
        Add a notification to the display queue.

        Args:
            notification: The Notification to display.

        Returns:
            The notification ID.
        """
        # Insert sorted by priority (highest first)
        inserted = False
        for i, existing in enumerate(self._queue):
            if notification.priority > existing.priority:
                self._queue.insert(i, notification)
                inserted = True
                break
        if not inserted:
            self._queue.append(notification)

        # Trim to max display count
        self._queue = self._queue[:MAX_NOTIFICATIONS_DISPLAYED]

        logger.info(
            "Notification [%s] '%s': %s",
            notification.priority.name,
            notification.title,
            notification.message[:80],
        )

        # Push to ambient overlay
        if self._ambient:
            self._ambient.add_notification(notification.__dict__)

        # Audio chime for high+ priority
        if notification.priority >= NotificationPriority.HIGH and self._audio:
            try:
                self._audio._speaker.play_chime("intercom")
            except Exception:  # pylint: disable=broad-except
                pass

        # Wake screen for urgent notifications
        if notification.priority == NotificationPriority.URGENT and self._screen:
            _schedule(self._screen.go_dashboard(), name="notif-wake-screen")

        # Schedule auto-dismiss
        if notification.auto_dismiss:
            task = _schedule(
                self._auto_dismiss(notification.id, notification.dismiss_after),
                name=f"dismiss-{notification.id[:8]}",
            )
            if task is not None:
                self._dismiss_tasks[notification.id] = task

        return notification.id

    def dismiss(self, notification_id: str) -> None:
        """
        Manually dismiss a notification.

        Args:
            notification_id: The ID of the notification to dismiss.
        """
        self._queue = [n for n in self._queue if n.id != notification_id]
        if self._ambient:
            self._ambient.dismiss_notification(notification_id)

        # Cancel auto-dismiss task if pending
        task = self._dismiss_tasks.pop(notification_id, None)
        if task:
            task.cancel()

        logger.debug("Notification %s dismissed.", notification_id[:8])

    def get_active(self) -> List[dict]:
        """
        Return all active notifications as dicts.

        Returns:
            List of notification dicts, sorted by priority.
        """
        return [n.__dict__ for n in self._queue]

    def clear_all(self) -> None:
        """Dismiss all active notifications."""
        for n in list(self._queue):
            self.dismiss(n.id)

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _auto_dismiss(self, notification_id: str, delay: int) -> None:
        """
        Auto-dismiss a notification after a delay.

        Args:
            notification_id: The notification to dismiss.
            delay:           Seconds to wait before dismissing.
        """
        try:
            await asyncio.sleep(delay)
            self.dismiss(notification_id)
        except asyncio.CancelledError:
            pass
