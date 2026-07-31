"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/presenter.py
Purpose:     Decides HOW a unit tells the user something.

             Vortex units come in different shapes: a 10" Hub Max, a 7" Hub,
             and a screenless Mini. They all run this same image. Before this
             module existed every subsystem published straight to ws_hub —
             a WebSocket to the browser — so on a Mini a finished timer, a
             recipe step, and an announcement all fired into nothing.

             Subsystems now hand events to the presenter, which fans them out
             to whatever this unit actually has:

               screen  → ws_hub, when the unit has a display
               voice   → spoken aloud, whenever the event carries a phrase
               chime   → last-resort audible fallback (handled in voice.py)

             A Mini says "your 8 minute timer is done". A Hub shows the banner
             AND says it, because a timer you cannot hear is useless. A silent
             list refresh carries no phrase and so is never spoken.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, Optional

from core.config import config
from core.voice import voice
from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)


class Presenter:
    """
    Routes user-facing events to the output surfaces this unit has.

    Usage:
        await presenter.present(
            {"type": "timer_done", "timer": {...}},
            speech="Your 8 minute timer is done.",
            speak_on_screen=True,
        )
    """

    def __init__(self) -> None:
        """Initialize. Capability is read lazily so config load order is free."""
        self._has_screen: Optional[bool] = None

    @property
    def has_screen(self) -> bool:
        """
        True if this unit has a display.

        Derived from the profile's `form_factor` when set, falling back to the
        `capabilities.display` flag. A Mini declares form_factor "mini".
        """
        if self._has_screen is None:
            form_factor = str(config.get("form_factor", "") or "").lower()
            if form_factor:
                self._has_screen = form_factor != "mini"
            else:
                self._has_screen = bool(config.get("cap_display", True))
        return self._has_screen

    def reset(self) -> None:
        """Clear the cached capability. Used by tests and after a config reload."""
        self._has_screen = None

    async def present(
        self,
        message: Dict[str, Any],
        speech: Optional[str] = None,
        speak_on_screen: bool = False,
        interrupt: bool = False,
    ) -> None:
        """
        Deliver an event to every surface this unit has.

        Args:
            message:         The JSON event for the frontend. Always broadcast
                             — harmless when nothing is connected.
            speech:          What to say aloud. None means this event is
                             visual-only (e.g. a list refresh) and is never
                             spoken on any unit.
            speak_on_screen: Speak even on a unit that has a screen. Use for
                             anything the user must notice without looking —
                             timers finishing, announcements, recipe steps.
            interrupt:       Cut off audio currently playing.

        A failure on one surface never prevents the other from running: a
        screenless unit must still speak if the WebSocket broadcast throws,
        and a Hub must still show the banner if the speaker is broken.
        """
        try:
            await ws_hub.broadcast(message)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Screen broadcast failed for '%s': %s",
                         message.get("type"), exc)

        if not speech:
            return

        # Screened units stay quiet unless the event is important enough to
        # interrupt — otherwise the kitchen Hub would narrate every state change.
        if self.has_screen and not speak_on_screen:
            return

        try:
            await voice.speak(speech, interrupt=interrupt)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Speech failed for '%s': %s", message.get("type"), exc)


# ─────────────────────────────────────────────────────────────────────────────
# Phrase builders
# ─────────────────────────────────────────────────────────────────────────────
# Kept here rather than scattered through the subsystems so every spoken
# phrase in the product reads consistently and can be reviewed in one place.

def describe_duration(seconds: int) -> str:
    """
    Render a duration the way a person would say it.

    Args:
        seconds: Total duration in seconds.

    Returns:
        A spoken-form string, e.g. "8 minute", "1 hour 30 minute".
    """
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    if secs and not hours:
        parts.append(f"{secs} second" + ("s" if secs != 1 else ""))
    return " ".join(parts) or "0 seconds"


def timer_done_phrase(timer: Dict[str, Any]) -> str:
    """
    Build what River says when a timer finishes.

    Prefers the timer's label ("the pasta timer is done") and falls back to
    its duration ("your 8 minute timer is done") when it is unlabelled.
    """
    label = (timer.get("label") or "").strip()
    if label:
        return f"Your {label} timer is done."
    duration = timer.get("duration_seconds") or timer.get("total_seconds") or 0
    if duration:
        return f"Your {describe_duration(int(duration))} timer is done."
    return "Your timer is done."


def routine_step_phrase(routine: Dict[str, Any]) -> Optional[str]:
    """
    Build what River says when a guided routine moves to a new step.

    This is the heart of cooking mode on a screenless unit — the step text
    IS the interface. Returns None when there is nothing to announce.
    """
    if not routine.get("active"):
        return None

    step = routine.get("step")
    if not step:
        return None

    if isinstance(step, dict):
        # "instruction" is the canonical field — see RoutineSession's presets
        # and the RoutineStep model in core/routines_api.py. "text" is only a
        # tolerated alias; reading the wrong one leaves River silent on every
        # single step, which is the entire feature on a screenless unit.
        text = step.get("instruction") or step.get("text")
    else:
        text = str(step)
    if not text:
        return None

    index = routine.get("step_index")
    count = routine.get("step_count")
    if isinstance(index, int) and isinstance(count, int) and count > 0:
        return f"Step {index + 1} of {count}. {text}"
    return str(text)


# Module-level singleton — import this, mirroring the ws_hub pattern.
presenter = Presenter()
