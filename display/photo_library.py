"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        display/photo_library.py
Purpose:     The ambient photo library. Scans a directory on the unit for
             images and hands them to the ambient screen in a shuffled order.

             Deliberately local-first: photos live on the unit's own storage,
             so the ambient screen keeps working when River Song is down or
             WiFi has dropped. River Song can drop new files into the same
             directory to curate what a given room shows.

             A changing backdrop also helps the burn-in problem the idle
             staircase addresses — a photo that swaps every few minutes is the
             opposite of a static layout baked into the panel.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import random
import threading
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Formats Chromium renders without help. HEIC is deliberately excluded —
# it needs a decode step the Pi should not be doing on the display path.
SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"})

# How long a directory scan is trusted before being redone, so photos added
# to the unit appear without a restart.
RESCAN_INTERVAL_SECONDS = 300


class PhotoLibrary:
    """
    A shuffled, periodically-rescanned view of a directory of images.

    Thread-safe: the rescan can be triggered from the API thread while the
    ambient loop is reading.

    Args:
        directory: Where the photos live.
        shuffle:   Present them in random order. False walks them in sorted
                   filename order, which is what you want for a numbered set.
    """

    def __init__(self, directory: str, shuffle: bool = True) -> None:
        """Initialize the library. Does not scan until first use."""
        self._directory = Path(directory).expanduser()
        self._shuffle = shuffle
        self._photos: List[Path] = []
        self._last_scan: float = 0.0
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def directory(self) -> Path:
        """The directory being served."""
        return self._directory

    def count(self) -> int:
        """Number of usable photos currently known."""
        self._maybe_rescan()
        with self._lock:
            return len(self._photos)

    def names(self) -> List[str]:
        """
        Filenames in presentation order.

        Returns names only, never paths. The frontend asks for a photo by
        name and resolve() maps it back — so a caller can never reach a file
        outside the configured directory.
        """
        self._maybe_rescan()
        with self._lock:
            return [p.name for p in self._photos]

    def resolve(self, name: str) -> Optional[Path]:
        """
        Map a filename from names() back to a path on disk.

        Args:
            name: A filename previously returned by names().

        Returns:
            The path, or None if the name is not in the library.

        Security: the lookup is an exact match against the scanned set, so
        "../../etc/passwd" simply is not in the list. Never join user input
        onto the directory.
        """
        self._maybe_rescan()
        with self._lock:
            for path in self._photos:
                if path.name == name:
                    return path
        return None

    def rescan(self) -> int:
        """
        Force a rescan of the directory.

        Returns:
            The number of photos found.
        """
        photos: List[Path] = []

        if not self._directory.is_dir():
            logger.info(
                "Ambient photo directory '%s' does not exist — ambient photos "
                "are disabled until it does.",
                self._directory,
            )
        else:
            try:
                for entry in self._directory.iterdir():
                    if not entry.is_file():
                        continue
                    if entry.suffix.lower() not in SUPPORTED_SUFFIXES:
                        continue
                    # Skip the dotfiles and sidecars that photo tools leave
                    # behind, which would otherwise show as broken images.
                    if entry.name.startswith("."):
                        continue
                    photos.append(entry)
            except OSError as exc:
                logger.error("Could not read photo directory '%s': %s",
                             self._directory, exc)

        photos.sort(key=lambda p: p.name.lower())
        if self._shuffle:
            random.shuffle(photos)

        with self._lock:
            self._photos = photos
            self._last_scan = time.monotonic()

        logger.info("Ambient photo library: %d photo(s) in %s",
                    len(photos), self._directory)
        return len(photos)

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _maybe_rescan(self) -> None:
        """Rescan if the cached listing has gone stale, or was never built."""
        with self._lock:
            age = time.monotonic() - self._last_scan
            fresh = self._last_scan > 0 and age < RESCAN_INTERVAL_SECONDS
        if not fresh:
            self.rescan()
