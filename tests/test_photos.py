"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_photos.py
Purpose:     Tests for the ambient photo layer — display/photo_library.py and
             core/photos_api.py.

             Covers the scan/shuffle behaviour, graceful handling of a missing
             directory (the common case on a fresh unit), and the traversal
             guard on the file endpoint.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import photos_api
from display.photo_library import PhotoLibrary


def make_photos(directory, names):
    """Create placeholder files so the library has something to find."""
    for name in names:
        (Path(directory) / name).write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")


class TestPhotoLibrary(unittest.TestCase):
    """Scanning a directory of images."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_finds_supported_image_formats(self):
        make_photos(self.dir, ["a.jpg", "b.PNG", "c.webp", "d.jpeg"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        self.assertEqual(lib.count(), 4)

    def test_ignores_unsupported_files(self):
        make_photos(self.dir, ["keep.jpg", "notes.txt", "clip.mp4", "raw.heic"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        self.assertEqual(lib.names(), ["keep.jpg"])

    def test_ignores_dotfiles(self):
        """Photo tools leave sidecars around; they would render as broken."""
        make_photos(self.dir, ["real.jpg", "._real.jpg", ".hidden.png"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        self.assertEqual(lib.names(), ["real.jpg"])

    def test_missing_directory_is_not_an_error(self):
        """A fresh unit has no photo directory yet. That must not crash."""
        lib = PhotoLibrary("/nonexistent/river/photos", shuffle=False)
        self.assertEqual(lib.count(), 0)
        self.assertEqual(lib.names(), [])

    def test_unshuffled_order_is_stable_and_sorted(self):
        make_photos(self.dir, ["c.jpg", "a.jpg", "b.jpg"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        self.assertEqual(lib.names(), ["a.jpg", "b.jpg", "c.jpg"])

    def test_resolve_maps_a_name_back_to_its_path(self):
        make_photos(self.dir, ["photo.jpg"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        resolved = lib.resolve("photo.jpg")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "photo.jpg")

    def test_resolve_rejects_names_outside_the_library(self):
        make_photos(self.dir, ["photo.jpg"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        for attempt in ("../../etc/passwd", "/etc/passwd", "missing.jpg",
                        "..%2f..%2fetc%2fpasswd"):
            self.assertIsNone(lib.resolve(attempt), attempt)

    def test_rescan_picks_up_new_files(self):
        make_photos(self.dir, ["one.jpg"])
        lib = PhotoLibrary(self.dir, shuffle=False)
        self.assertEqual(lib.count(), 1)
        make_photos(self.dir, ["two.jpg"])
        self.assertEqual(lib.rescan(), 2)


class TestPhotosAPI(unittest.TestCase):
    """The endpoints the kiosk actually calls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        make_photos(self.tmp.name, ["one.jpg", "two.jpg"])

        self.library = PhotoLibrary(self.tmp.name, shuffle=False)
        photos_api.set_photo_library(self.library)
        self.addCleanup(photos_api.set_photo_library, None)

        app = FastAPI()
        app.include_router(photos_api.router)
        self.client = TestClient(app)

    def test_playlist_lists_every_photo_with_a_url(self):
        res = self.client.get("/api/vortex/v1/photos")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 2)
        self.assertTrue(all(p["url"].endswith(p["name"]) for p in body["photos"]))

    def test_playlist_includes_the_hold_interval(self):
        body = self.client.get("/api/vortex/v1/photos").json()
        self.assertGreater(body["interval_seconds"], 0)

    def test_file_endpoint_serves_a_known_photo(self):
        res = self.client.get("/api/vortex/v1/photos/file/one.jpg")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "image/jpeg")

    def test_file_endpoint_never_serves_anything_outside_the_library(self):
        """
        The name is matched against the scanned set, never joined onto the
        photo directory, so traversal attempts cannot reach a real file.

        Asserted as "no file content comes back" rather than "returns 404":
        some of these normalise to a different route entirely before they
        reach the handler, and that is fine — what matters is that no file
        from outside the library is ever served.
        """
        for attempt in ("..%2F..%2Fetc%2Fpasswd", "nope.jpg", "..",
                        "%2Fetc%2Fpasswd", "....//etc/passwd"):
            res = self.client.get(f"/api/vortex/v1/photos/file/{attempt}")
            content_type = res.headers.get("content-type", "")
            self.assertFalse(
                content_type.startswith("image/") or content_type == "application/octet-stream",
                f"{attempt} served file content: {content_type}",
            )
            self.assertNotIn(b"root:", res.content, attempt)

    def test_rescan_endpoint_reports_the_new_count(self):
        make_photos(self.tmp.name, ["three.jpg"])
        res = self.client.post("/api/vortex/v1/photos/rescan")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 3)

    def test_endpoints_report_unavailable_without_a_library(self):
        """A unit with photos disabled should 503, not 500."""
        photos_api.set_photo_library(None)
        self.assertEqual(self.client.get("/api/vortex/v1/photos").status_code, 503)


class TestEmptyLibrary(unittest.TestCase):
    """A unit with no photos is a normal state, not a failure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        photos_api.set_photo_library(PhotoLibrary(self.tmp.name))
        self.addCleanup(photos_api.set_photo_library, None)
        app = FastAPI()
        app.include_router(photos_api.router)
        self.client = TestClient(app)

    def test_empty_playlist_is_a_success_not_an_error(self):
        res = self.client.get("/api/vortex/v1/photos")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["photos"], [])


if __name__ == "__main__":
    unittest.main()
