"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/main.py
Purpose:     Primary entry point and system orchestrator for River Vortex.
             Initializes all subsystems, manages the application lifecycle,
             handles graceful shutdown, and coordinates the main event loop.
             This is the process root — everything starts and stops here.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core import announce_api, intercom_api, lists_api, routines_api, setup_api, timers_api
from core.announce import AnnouncementSession
from core.config import Config, ConfigError, config
from core.constants import (
    BACKEND_HOST,
    BACKEND_PORT,
    CORS_ALLOWED_ORIGINS,
    FRONTEND_BUILD_DIR,
    PROFILE_PATH,
    RESTART_DELAY_SECONDS,
    SYSTEM_NAME,
    VERSION,
    VortexState,
)
from core.lists import ListsStore
from core.routines import RoutineSession
from core.timers import TimerManager
from core.ws_hub import ws_hub
from telemetry.logger import setup_logging

# ─────────────────────────────────────────────────────────────────────────────
# Module logger — configured after setup_logging() is called
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI application factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app(
    restart_callback: Optional[Callable[[], None]] = None,
    timer_manager: Optional[TimerManager] = None,
    routine_session: Optional[RoutineSession] = None,
    announcement_session: Optional[AnnouncementSession] = None,
    intercom_manager: Optional[Any] = None,
    lists_store: Optional[ListsStore] = None,
) -> FastAPI:
    """
    Build and configure the FastAPI application instance.

    Registers CORS middleware, mounts the React frontend static build,
    and includes all API routers. Called once at startup.

    Args:
        restart_callback:     Optional zero-argument callable that restarts
                               the process. Wired into the setup/pairing API
                               so it can apply new configuration after pairing.
        timer_manager:        Optional TimerManager backing
                               /api/vortex/v1/timers. If None, those endpoints
                               respond 503.
        routine_session:      Optional RoutineSession backing
                               /api/vortex/v1/routine. If None, those
                               endpoints respond 503.
        announcement_session: Optional AnnouncementSession backing
                               /api/vortex/v1/announce. If None, that
                               endpoint responds 503.
        intercom_manager:     Optional intercom.intercom_manager.IntercomManager
                               backing /api/vortex/v1/intercom. If None, those
                               endpoints respond 503.
        lists_store:          Optional ListsStore backing
                               /api/vortex/v1/lists and
                               /api/vortex/v1/reminders. If None, those
                               endpoints respond 503.

    Returns:
        A fully configured FastAPI application.
    """
    app = FastAPI(
        title=SYSTEM_NAME,
        version=VERSION,
        description="River Vortex — Smart Home Hub API",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS — allow the React dev server and the local kiosk browser
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # First-run pairing API — unauthenticated, used by the River Song app
    # to discover and configure this unit (see core/setup_api.py).
    if restart_callback:
        setup_api.set_restart_callback(restart_callback)
    app.include_router(setup_api.router)

    # Timers/alarms and guided routines (cooking mode, etc.) — driven by
    # River Song's voice intent handlers (see core/timers_api.py,
    # core/routines_api.py).
    timers_api.set_timer_manager(timer_manager)
    app.include_router(timers_api.router)

    routines_api.set_routine_session(routine_session)
    app.include_router(routines_api.router)

    # Multi-room announcements ("Drop In" broadcasts) and room-to-room
    # intercom calls — see core/announce_api.py, core/intercom_api.py.
    announce_api.set_announcement_session(announcement_session)
    app.include_router(announce_api.router)

    intercom_api.set_intercom_manager(intercom_manager)
    app.include_router(intercom_api.router)

    # Shopping/to-do lists and upcoming reminders — thin local cache for
    # snapshots pushed by River Song (see core/lists_api.py).
    lists_api.set_lists_store(lists_store)
    app.include_router(lists_api.router)
    app.include_router(lists_api.reminders_router)

    # Real-time event stream to the frontend (display mode changes, timer
    # updates, guided routine steps, etc.) — see core/ws_hub.py.
    @app.websocket("/api/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await ws_hub.connect(websocket)
        try:
            while True:
                # The frontend doesn't send anything meaningful — just keep
                # the connection open until the client disconnects.
                await websocket.receive_text()
        except WebSocketDisconnect:
            await ws_hub.disconnect(websocket)

    # ── API health check ──────────────────────────────────────────────────────
    @app.get("/api/health", tags=["System"])
    async def health_check() -> dict:
        """
        Lightweight health check endpoint.

        Returns:
            JSON with system name, version, and current state.
        """
        return {
            "system": SYSTEM_NAME,
            "version": VERSION,
            "unit_id": config.get("unit_id"),
            "unit_name": config.get("unit_name"),
            "configured": bool(config.get("configured", False)),
            "status": "ok",
        }

    # Mount React frontend build if it exists. Registered last — it's a
    # catch-all at "/" and would otherwise shadow any API route defined
    # after it.
    frontend_path = Path(FRONTEND_BUILD_DIR)
    if frontend_path.exists() and frontend_path.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
        logger.info("Frontend build mounted from %s", frontend_path.resolve())
    else:
        logger.warning(
            "Frontend build directory '%s' not found. "
            "Run 'npm run build' inside frontend/ to generate it.",
            frontend_path.resolve(),
        )

    return app


# ─────────────────────────────────────────────────────────────────────────────
# RiverVortex — main orchestrator class
# ─────────────────────────────────────────────────────────────────────────────

class RiverVortex:
    """
    Top-level orchestrator for the River Vortex smart home hub.

    Responsibilities:
    - Load and validate configuration
    - Initialize all subsystem managers
    - Start the FastAPI backend server
    - Run the main async event loop
    - Handle OS signals for graceful shutdown
    - Restart failed subsystems via the watchdog

    Architecture note:
        River Vortex is the room interface layer only. All AI processing
        is delegated to River Song via the /api/vortex/ endpoints.
        Wake word detection is always local — no audio leaves the device
        until the wake word is confirmed.
    """

    def __init__(self) -> None:
        """Initialize the orchestrator. Does not start any subsystems yet."""
        self._state: VortexState = VortexState.INITIALIZING
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._app: Optional[FastAPI] = None

        # Subsystem manager references (populated in _init_subsystems)
        self._audio_manager = None
        self._screen_manager = None
        self._ha_client = None
        self._device_control = None
        self._intercom_manager = None
        self._connectivity_manager = None
        self._privacy_manager = None
        self._watchdog = None
        self._telemetry_collector = None
        self._discovery_service = None
        self._timer_manager = None
        self._routine_session = None
        self._announcement_session = None
        self._lists_store = None

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """
        Synchronous entry point. Sets up logging, loads config, then hands
        off to the async event loop.

        This is the method called by the __main__ block.
        """
        # Logging must be set up before anything else so all subsequent
        # log calls are captured correctly.
        setup_logging(
            log_level=os.getenv("VORTEX_LOG_LEVEL", "INFO"),
            log_dir=os.getenv("VORTEX_LOG_DIR", config.get("log_dir", "/var/log/river-vortex")),
        )

        logger.info("=" * 72)
        logger.info("  %s  v%s  — Starting up", SYSTEM_NAME, VERSION)
        logger.info("=" * 72)

        try:
            self._load_config()
        except ConfigError as exc:
            logger.critical("Configuration error — cannot start: %s", exc)
            sys.exit(1)

        try:
            asyncio.run(self._async_main())
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received — shutting down.")
        except Exception as exc:  # pylint: disable=broad-except
            logger.critical("Unhandled exception in main loop: %s", exc, exc_info=True)
            sys.exit(1)

    async def _async_main(self) -> None:
        """
        Async main coroutine. Initializes subsystems, starts the backend
        server, and runs until a shutdown signal is received.
        """
        # Register OS signal handlers inside the async context
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown_signal)

        try:
            await self._init_subsystems()
            await self._start_backend_server()

            if config.get("configured", False):
                self._set_state(VortexState.IDLE)
                logger.info("%s is ready. Unit: %s | Location: %s",
                            SYSTEM_NAME,
                            config.get("unit_name"),
                            config.get("location"))
            else:
                self._set_state(VortexState.SETUP)
                logger.info(
                    "%s is unpaired. Open the River Song app to set up this "
                    "unit using the pairing PIN shown on its display.",
                    SYSTEM_NAME,
                )

            # Block here until a shutdown signal sets the event
            await self._shutdown_event.wait()

        finally:
            await self._shutdown()

    # ─────────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """
        Load and validate configuration from all sources.

        Raises:
            ConfigError: If a required value (e.g., HA token) is absent.
        """
        config.load(profile_path=PROFILE_PATH)

        # Validate required fields — fail fast before any subsystem starts
        required_keys = [
            "unit_id",
            "unit_name",
        ]
        for key in required_keys:
            config.require(key)

        # Warn (don't fail) on missing optional-but-important keys
        if not config.get("ha_token"):
            logger.warning(
                "HA_TOKEN is not set. Home Assistant integration will be disabled."
            )
        if not config.get("porcupine_access_key"):
            logger.warning(
                "PORCUPINE_ACCESS_KEY is not set. Wake word detection will be disabled."
            )
        if not config.get("river_song_api_key"):
            logger.warning(
                "RIVER_SONG_API_KEY is not set. Voice command processing will be disabled."
            )

        logger.debug("Active configuration: %s", config.as_dict())

    # ─────────────────────────────────────────────────────────────────────────
    # Subsystem Initialization
    # ─────────────────────────────────────────────────────────────────────────

    async def _init_subsystems(self) -> None:
        """
        Initialize all subsystem managers in dependency order.

        Order matters:
          1. Telemetry — must be up before anything else logs
          2. Privacy manager — hardware mute state set before mic opens
          3. Discovery (mDNS) — so the unit is findable for setup ASAP
          4. Connectivity — network must be checked before HA/API clients
          5. Home Assistant client (+ DeviceControl)
          6. Audio (wake word + mic + speaker)
          7. Display (screen + ambient mode)
          8. Intercom
          9. Timers & guided routines (cooking mode, etc.)
          10. Watchdog — last, so it can monitor all other subsystems

        Each subsystem is imported lazily here to avoid circular imports
        and to allow individual modules to be tested in isolation.
        """
        logger.info("Initializing subsystems...")

        # ── Telemetry ─────────────────────────────────────────────────────────
        try:
            from telemetry.collector import TelemetryCollector
            self._telemetry_collector = TelemetryCollector()
            await self._telemetry_collector.start()
            logger.info("[OK] Telemetry collector started.")
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Telemetry collector failed to start: %s", exc)

        # ── Privacy Manager ───────────────────────────────────────────────────
        try:
            from safety.privacy_manager import PrivacyManager
            self._privacy_manager = PrivacyManager()
            await self._privacy_manager.start()
            logger.info("[OK] Privacy manager started.")
        except Exception as exc:
            logger.error("Privacy manager failed to start: %s", exc)

        # ── Discovery (mDNS) ──────────────────────────────────────────────────
        # Advertised whether configured or not — River Song uses this both to
        # find unpaired units during setup and to keep track of paired ones.
        try:
            from connectivity.discovery import DiscoveryService
            self._discovery_service = DiscoveryService()
            await self._discovery_service.start()
            logger.info("[OK] Discovery service started.")
        except Exception as exc:
            logger.error("Discovery service failed to start: %s", exc)

        # ── Connectivity ──────────────────────────────────────────────────────
        try:
            from connectivity.wifi_manager import WiFiManager
            self._connectivity_manager = WiFiManager()
            await self._connectivity_manager.start()
            logger.info("[OK] Connectivity manager started.")
        except Exception as exc:
            logger.error("Connectivity manager failed to start: %s", exc)

        # ── Home Assistant ────────────────────────────────────────────────────
        if config.get("ha_token") and config.get("cap_home_assistant", True):
            try:
                from home_assistant.device_control import DeviceControl
                from home_assistant.ha_client import HAClient
                self._ha_client = HAClient(
                    url=config.require("ha_url"),
                    token=config.require("ha_token"),
                )
                await self._ha_client.connect()
                self._device_control = DeviceControl(self._ha_client)
                logger.info("[OK] Home Assistant client connected.")
            except Exception as exc:
                logger.error("Home Assistant client failed to connect: %s", exc)
        else:
            logger.info("[SKIP] Home Assistant integration disabled (no token).")

        # ── Audio ─────────────────────────────────────────────────────────────
        if config.get("cap_audio", True) and config.get("mic_enabled", True):
            try:
                from audio.audio_manager import AudioManager
                self._audio_manager = AudioManager(ha_client=self._ha_client)
                await self._audio_manager.start()
                logger.info("[OK] Audio manager started.")
            except Exception as exc:
                logger.error("Audio manager failed to start: %s", exc)
        else:
            logger.info("[SKIP] Audio subsystem disabled.")

        # ── Display ───────────────────────────────────────────────────────────
        if config.get("cap_display", True):
            try:
                from display.screen_manager import ScreenManager
                self._screen_manager = ScreenManager()
                await self._screen_manager.start()
                logger.info("[OK] Screen manager started.")
            except Exception as exc:
                logger.error("Screen manager failed to start: %s", exc)
        else:
            logger.info("[SKIP] Display subsystem disabled.")

        # ── Intercom ──────────────────────────────────────────────────────────
        if config.get("cap_intercom", True) and config.get("intercom_enabled", True):
            try:
                from intercom.intercom_manager import IntercomManager
                self._intercom_manager = IntercomManager(
                    microphone=self._audio_manager.microphone if self._audio_manager else None,
                    speaker=self._audio_manager.speaker if self._audio_manager else None,
                )
                self._intercom_manager.on_incoming_call(self._on_intercom_incoming_call)
                self._intercom_manager.on_call_ended(self._on_intercom_call_ended)
                await self._intercom_manager.start()
                logger.info("[OK] Intercom manager started.")
            except Exception as exc:
                logger.error("Intercom manager failed to start: %s", exc)
        else:
            logger.info("[SKIP] Intercom subsystem disabled.")

        # ── Timers, Guided Routines & Announcements ─────────────────────────
        # Stateful helpers driven by River Song's voice intent handlers via
        # /api/vortex/v1/timers, /api/vortex/v1/routine, and
        # /api/vortex/v1/announce. Timers chime through the speaker when they
        # elapse; routines and announcements duck background media (if HA is
        # connected) — routines switch the display to "routine" mode, and
        # announcements show a transient on-screen banner.
        try:
            self._timer_manager = TimerManager(on_timer_done=self._on_timer_done)
            self._routine_session = RoutineSession(
                device_control=self._device_control,
                on_mode_change=(
                    self._screen_manager.set_mode if self._screen_manager else None
                ),
            )
            self._announcement_session = AnnouncementSession(
                device_control=self._device_control,
                audio_manager=self._audio_manager,
            )
            logger.info("[OK] Timers, guided routines, and announcements ready.")
        except Exception as exc:
            logger.error("Timers/routines/announcements failed to initialize: %s", exc)

        # ── Lists & Reminders ────────────────────────────────────────────────
        # Thin local cache for shopping/to-do lists and upcoming reminders —
        # River Song owns persistence and pushes snapshots via
        # /api/vortex/v1/lists and /api/vortex/v1/reminders; Vortex caches
        # them for instant display and broadcasts lists_update /
        # reminders_update so every connected display stays in sync.
        try:
            self._lists_store = ListsStore()
            logger.info("[OK] Lists & reminders cache ready.")
        except Exception as exc:
            logger.error("Lists & reminders cache failed to initialize: %s", exc)

        # ── Watchdog ──────────────────────────────────────────────────────────
        try:
            from safety.watchdog import Watchdog
            self._watchdog = Watchdog(
                subsystems={
                    "audio": self._audio_manager,
                    "screen": self._screen_manager,
                    "ha_client": self._ha_client,
                    "intercom": self._intercom_manager,
                    "connectivity": self._connectivity_manager,
                }
            )
            await self._watchdog.start()
            logger.info("[OK] Watchdog started.")
        except Exception as exc:
            logger.error("Watchdog failed to start: %s", exc)

        logger.info("All subsystems initialized.")

    def _on_timer_done(self, timer: Dict[str, Any]) -> None:
        """
        Callback invoked by TimerManager when a timer/alarm elapses.

        Plays a chime through the speaker so the user hears it even if
        they're not looking at the display. Runs synchronously on the
        asyncio event loop thread.

        Args:
            timer: The expired timer's dict (id, label, duration_seconds, ...).
        """
        if self._audio_manager:
            self._audio_manager.play_chime("done")
        logger.info("Timer '%s' finished.", timer.get("label", "Timer"))

    def _on_intercom_incoming_call(self, peer_unit_id: str) -> None:
        """
        Callback invoked by IntercomManager when another unit places a
        "Drop In" call to this one.

        Plays the intercom chime and brings the dashboard to the front so
        the incoming-call banner is visible. Runs synchronously on the
        asyncio event loop thread.

        Args:
            peer_unit_id: The unit ID of the calling Vortex unit.
        """
        if self._audio_manager:
            self._audio_manager.play_chime("intercom")
        if self._screen_manager:
            asyncio.create_task(self._screen_manager.go_dashboard())
        logger.info("Incoming intercom call from '%s'.", peer_unit_id)

    def _on_intercom_call_ended(self) -> None:
        """Callback invoked by IntercomManager when an intercom call ends."""
        logger.info("Intercom call ended.")

    # ─────────────────────────────────────────────────────────────────────────
    # Backend Server
    # ─────────────────────────────────────────────────────────────────────────

    async def _start_backend_server(self) -> None:
        """
        Build the FastAPI app and start the uvicorn server in a background thread.

        The server runs in a daemon thread so it does not block the async
        event loop. The loop continues to handle subsystem events and signals.
        """
        self._app = create_app(
            restart_callback=self._trigger_restart,
            timer_manager=self._timer_manager,
            routine_session=self._routine_session,
            announcement_session=self._announcement_session,
            intercom_manager=self._intercom_manager,
            lists_store=self._lists_store,
        )

        host = config.get("backend_host", BACKEND_HOST)
        port = int(config.get("backend_port", BACKEND_PORT))

        server_config = uvicorn.Config(
            app=self._app,
            host=host,
            port=port,
            log_level=config.get("log_level", "info").lower(),
            access_log=False,   # Handled by our telemetry logger
            reload=False,       # Never True in production
        )
        server = uvicorn.Server(config=server_config)

        # Run uvicorn in a background thread — it has its own event loop
        server_thread = threading.Thread(
            target=server.run,
            name="uvicorn-server",
            daemon=True,
        )
        server_thread.start()
        logger.info("Backend API server started on http://%s:%d", host, port)

    # ─────────────────────────────────────────────────────────────────────────
    # Restart (used after pairing/unpairing)
    # ─────────────────────────────────────────────────────────────────────────

    def _trigger_restart(self) -> None:
        """
        Schedule a full process restart.

        Called by the setup API after a successful pair/unpair so the new
        configuration (River Song credentials, unit identity, etc.) is
        picked up by every subsystem on a clean boot. The restart runs on a
        short delay so the HTTP response confirming pairing can be sent
        first, then replaces the current process image with a fresh one.
        """
        def _restart() -> None:
            logger.info("Restarting %s to apply new configuration...", SYSTEM_NAME)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        threading.Timer(RESTART_DELAY_SECONDS, _restart).start()

    # ─────────────────────────────────────────────────────────────────────────
    # Shutdown
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_shutdown_signal(self) -> None:
        """
        Signal handler for SIGINT and SIGTERM.

        Sets the shutdown event, which causes _async_main to exit its wait
        and proceed to the finally block for graceful teardown.
        """
        logger.info("Shutdown signal received.")
        self._set_state(VortexState.SHUTTING_DOWN)
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """
        Gracefully stop all subsystems in reverse initialization order.

        Each subsystem's stop() is awaited individually. Errors during
        shutdown are logged but do not prevent other subsystems from stopping.
        """
        logger.info("Shutting down %s...", SYSTEM_NAME)
        self._set_state(VortexState.SHUTTING_DOWN)

        shutdown_order = [
            ("Watchdog",      self._watchdog),
            ("Routine",       self._routine_session),
            ("Timers",        self._timer_manager),
            ("Intercom",      self._intercom_manager),
            ("Audio",         self._audio_manager),
            ("Screen",        self._screen_manager),
            ("HA Client",     self._ha_client),
            ("Connectivity",  self._connectivity_manager),
            ("Discovery",     self._discovery_service),
            ("Privacy",       self._privacy_manager),
            ("Telemetry",     self._telemetry_collector),
        ]

        for name, subsystem in shutdown_order:
            if subsystem is None:
                continue
            try:
                stop_fn = getattr(subsystem, "stop", None)
                if stop_fn:
                    if asyncio.iscoroutinefunction(stop_fn):
                        await stop_fn()
                    else:
                        stop_fn()
                logger.info("[STOPPED] %s", name)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error stopping %s: %s", name, exc)

        logger.info("%s shutdown complete. Goodbye.", SYSTEM_NAME)

    # ─────────────────────────────────────────────────────────────────────────
    # State Management
    # ─────────────────────────────────────────────────────────────────────────

    def _set_state(self, new_state: VortexState) -> None:
        """
        Transition the system to a new top-level state.

        Args:
            new_state: The VortexState to transition to.
        """
        if new_state != self._state:
            logger.debug("State: %s → %s", self._state.name, new_state.name)
            self._state = new_state

    @property
    def state(self) -> VortexState:
        """Return the current system state."""
        return self._state


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Module entry point. Instantiates RiverVortex and calls run().

    This function is referenced in pyproject.toml as the console_scripts
    entry point:
        river-vortex = core.main:main
    """
    vortex = RiverVortex()
    vortex.run()


if __name__ == "__main__":
    main()
