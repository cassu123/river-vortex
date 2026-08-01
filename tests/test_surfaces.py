"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_surfaces.py
Purpose:     Tests for core/surfaces.py — the store behind the context-aware
             ambient screen.

             What matters here is that the unit renders what it is told and
             nothing more: priority ordering it did not invent, lifetimes it
             honours, and a malformed descriptor that degrades to a harmless
             note rather than blanking a wall panel with no keyboard on it.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.surfaces import (DEFAULT_TTL_SECONDS, MAX_SURFACES, MAX_TTL_SECONDS,
                           SurfaceStore)


def run(coro):
    """
    Run a coroutine on the suite's shared event loop.

    Deliberately NOT asyncio.run(): that closes the loop and clears the
    thread's current loop on exit, which breaks every other test module here.
    """
    return asyncio.get_event_loop().run_until_complete(coro)


class SurfaceTestCase(unittest.TestCase):
    """Base — every push goes through the presenter, so stub it once."""

    def setUp(self):
        patcher = patch("core.surfaces.presenter.present", new_callable=AsyncMock)
        self.present = patcher.start()
        self.addCleanup(patcher.stop)
        self.store = SurfaceStore()


class TestNormalisation(SurfaceTestCase):
    """A malformed surface must degrade, never crash the panel."""

    def test_an_unknown_kind_falls_back_to_a_note(self):
        surface = SurfaceStore.normalise({"kind": "hologram", "title": "Hi"})
        self.assertEqual(surface["kind"], "note")
        self.assertEqual(surface["title"], "Hi")

    def test_an_unknown_priority_falls_back_to_normal(self):
        surface = SurfaceStore.normalise({"priority": "urgent!!!"})
        self.assertEqual(surface["priority"], "normal")
        self.assertEqual(surface["weight"], 1)

    def test_an_absent_ttl_gets_the_default_lifetime(self):
        surface = SurfaceStore.normalise({}, now=1000.0)
        self.assertEqual(surface["expires_at"], 1000.0 + DEFAULT_TTL_SECONDS)

    def test_a_junk_ttl_gets_the_default_lifetime(self):
        surface = SurfaceStore.normalise({"ttl_seconds": "soon"}, now=1000.0)
        self.assertEqual(surface["expires_at"], 1000.0 + DEFAULT_TTL_SECONDS)

    def test_nothing_can_pin_itself_to_the_screen_forever(self):
        surface = SurfaceStore.normalise({"ttl_seconds": 10 ** 9}, now=0.0)
        self.assertEqual(surface["expires_at"], float(MAX_TTL_SECONDS))

    def test_an_id_is_always_produced(self):
        """Without one, the surface could never be updated or withdrawn."""
        self.assertTrue(SurfaceStore.normalise({})["id"])

    def test_list_items_are_capped(self):
        surface = SurfaceStore.normalise({"items": [str(i) for i in range(50)]})
        self.assertEqual(len(surface["items"]), 8)

    def test_non_list_items_do_not_explode(self):
        self.assertEqual(SurfaceStore.normalise({"items": "milk"})["items"], [])

    def test_a_zero_value_survives(self):
        """0 is a real reading — falsy handling would blank the card."""
        self.assertEqual(SurfaceStore.normalise({"value": 0})["value"], "0")

    def test_actions_are_capped_and_must_be_objects(self):
        surface = SurfaceStore.normalise(
            {"actions": [{"label": "Yes"}, "no", {"label": "Maybe"}, {"label": "4th"}]}
        )
        self.assertEqual(surface["actions"], [{"label": "Yes"}, {"label": "Maybe"}])


class TestPriority(SurfaceTestCase):
    """The unit orders what it was given; it never decides what matters."""

    def test_the_highest_priority_surface_wins(self):
        run(self.store.push({"id": "a", "priority": "ambient"}))
        run(self.store.push({"id": "b", "priority": "critical"}))
        run(self.store.push({"id": "c", "priority": "normal"}))
        self.assertEqual(self.store.top()["id"], "b")

    def test_ties_go_to_the_most_recent(self):
        run(self.store.push({"id": "old", "priority": "normal"}))
        run(self.store.push({"id": "new", "priority": "normal"}))
        self.assertEqual(self.store.top()["id"], "new")

    def test_all_is_ordered_most_important_first(self):
        run(self.store.push({"id": "a", "priority": "normal"}))
        run(self.store.push({"id": "b", "priority": "high"}))
        run(self.store.push({"id": "c", "priority": "ambient"}))
        self.assertEqual([s["id"] for s in self.store.all()], ["b", "a", "c"])

    def test_an_empty_store_shows_nothing(self):
        """Nothing to say means the clock and photos, not a blank card."""
        self.assertIsNone(self.store.top())


class TestLifetime(SurfaceTestCase):
    """A card nobody withdraws still has to come down on its own."""

    def test_an_expired_surface_stops_being_returned(self):
        run(self.store.push({"id": "a", "ttl_seconds": 60}))
        self.assertIsNone(self.store.top(now=_later(self.store, "a", 1)))

    def test_a_live_surface_survives_the_sweep(self):
        run(self.store.push({"id": "a", "ttl_seconds": 600}))
        self.assertIsNotNone(self.store.top())

    def test_an_expired_surface_is_dropped_from_storage(self):
        """Not merely filtered — a hidden card would still occupy memory."""
        run(self.store.push({"id": "a", "ttl_seconds": 60}))
        self.store.all(now=_later(self.store, "a", 1))
        self.assertEqual(self.store._surfaces, {})

    def test_expiry_does_not_unmask_a_lower_priority_card_early(self):
        run(self.store.push({"id": "quiet", "priority": "ambient", "ttl_seconds": 600}))
        run(self.store.push({"id": "loud", "priority": "high", "ttl_seconds": 600}))
        self.assertEqual(self.store.top()["id"], "loud")


class TestUpsertAndWithdraw(SurfaceTestCase):
    """A surface that updates itself must replace, not stack."""

    def test_pushing_the_same_id_replaces_rather_than_appends(self):
        run(self.store.push({"id": "garage", "title": "Garage open"}))
        run(self.store.push({"id": "garage", "title": "Garage still open"}))
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(self.store.top()["title"], "Garage still open")

    def test_withdrawing_removes_the_surface(self):
        run(self.store.push({"id": "garage"}))
        self.assertTrue(run(self.store.withdraw("garage")))
        self.assertIsNone(self.store.top())

    def test_withdrawing_something_absent_reports_it(self):
        self.assertFalse(run(self.store.withdraw("never-existed")))

    def test_withdrawing_something_absent_sends_nothing(self):
        """Otherwise a retrying caller would spam every connected display."""
        run(self.store.withdraw("never-existed"))
        self.present.assert_not_called()

    def test_clear_empties_the_store(self):
        run(self.store.push({"id": "a"}))
        run(self.store.clear())
        self.assertEqual(self.store.all(), [])

    def test_the_store_is_bounded(self):
        for i in range(MAX_SURFACES + 10):
            run(self.store.push({"id": f"s{i}", "priority": "ambient"}))
        self.assertLessEqual(len(self.store._surfaces), MAX_SURFACES)

    def test_capacity_pressure_sheds_the_least_important_first(self):
        run(self.store.push({"id": "keep", "priority": "critical"}))
        for i in range(MAX_SURFACES + 10):
            run(self.store.push({"id": f"s{i}", "priority": "ambient"}))
        self.assertIn("keep", self.store._surfaces)


class TestDelivery(SurfaceTestCase):
    """One image runs on a 10" Hub and a screenless Mini alike."""

    def test_a_push_is_broadcast_to_the_screen(self):
        run(self.store.push({"id": "a", "title": "Bin day"}))
        message = self.present.call_args.args[0]
        self.assertEqual(message["type"], "surface")
        self.assertEqual(message["surface"]["id"], "a")

    def test_an_ordinary_card_is_not_spoken_on_a_screened_unit(self):
        """A Hub can just show it — narrating every card would be unbearable."""
        run(self.store.push({"id": "a", "priority": "normal"}, speech="Bin day."))
        self.assertFalse(self.present.call_args.kwargs["speak_on_screen"])

    def test_an_urgent_card_is_spoken_even_on_a_screened_unit(self):
        """You must notice a doorbell without happening to look at the panel."""
        run(self.store.push({"id": "a", "priority": "high"}, speech="Someone's here."))
        self.assertTrue(self.present.call_args.kwargs["speak_on_screen"])

    def test_a_critical_card_interrupts_whatever_is_playing(self):
        run(self.store.push({"id": "a", "priority": "critical"}, speech="Smoke alarm."))
        self.assertTrue(self.present.call_args.kwargs["interrupt"])

    def test_speech_is_passed_through_untouched(self):
        run(self.store.push({"id": "a"}, speech="Bin day tomorrow."))
        self.assertEqual(self.present.call_args.kwargs["speech"], "Bin day tomorrow.")

    def test_a_withdrawal_is_broadcast(self):
        run(self.store.push({"id": "a"}))
        self.present.reset_mock()
        run(self.store.withdraw("a"))
        self.assertEqual(self.present.call_args.args[0],
                         {"type": "surface_remove", "id": "a"})


class TestScreenWake(SurfaceTestCase):
    """An urgent card is no use painted behind a dark backlight."""

    def test_an_urgent_card_wakes_the_screen(self):
        wake = AsyncMock()
        self.store.set_interrupt_handler(wake)
        run(self.store.push({"id": "a", "priority": "high"}))
        wake.assert_awaited_once()

    def test_an_ordinary_card_does_not_wake_the_screen(self):
        """Otherwise every quiet update would light a bedroom at 3am."""
        wake = AsyncMock()
        self.store.set_interrupt_handler(wake)
        run(self.store.push({"id": "a", "priority": "normal"}))
        wake.assert_not_awaited()

    def test_a_broken_backlight_still_delivers_the_card(self):
        wake = AsyncMock(side_effect=OSError("no such file: bl_power"))
        self.store.set_interrupt_handler(wake)
        run(self.store.push({"id": "a", "priority": "critical"}))
        self.present.assert_awaited_once()

    def test_a_screenless_unit_needs_no_wake_handler(self):
        run(self.store.push({"id": "a", "priority": "critical"}))
        self.present.assert_awaited_once()


class TestSurfacesAPI(unittest.TestCase):
    """The REST seam River Song actually drives the ambient screen through."""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        patcher = patch("core.surfaces.presenter.present", new_callable=AsyncMock)
        self.present = patcher.start()
        self.addCleanup(patcher.stop)

        from core.surfaces_api import router, set_surface_store

        self.store = SurfaceStore()
        set_surface_store(self.store)
        self.addCleanup(set_surface_store, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_an_empty_unit_reports_no_surfaces(self):
        resp = self.client.get("/api/vortex/v1/surfaces")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"surfaces": []})

    def test_a_pushed_surface_comes_back_on_a_fresh_fetch(self):
        """The kiosk browser can restart hours after the card was pushed."""
        self.client.post("/api/vortex/v1/surfaces",
                         json={"id": "bins", "kind": "note", "title": "Bin day"})
        surfaces = self.client.get("/api/vortex/v1/surfaces").json()["surfaces"]
        self.assertEqual([s["id"] for s in surfaces], ["bins"])

    def test_an_unknown_kind_is_rejected_at_the_seam(self):
        resp = self.client.post("/api/vortex/v1/surfaces", json={"kind": "hologram"})
        self.assertEqual(resp.status_code, 422)

    def test_an_unknown_priority_is_rejected_at_the_seam(self):
        resp = self.client.post("/api/vortex/v1/surfaces", json={"priority": "urgent"})
        self.assertEqual(resp.status_code, 422)

    def test_withdrawing_an_unknown_surface_is_a_404(self):
        resp = self.client.delete("/api/vortex/v1/surfaces/nope")
        self.assertEqual(resp.status_code, 404)

    def test_clear_removes_everything(self):
        self.client.post("/api/vortex/v1/surfaces", json={"id": "a"})
        self.client.delete("/api/vortex/v1/surfaces")
        self.assertEqual(self.client.get("/api/vortex/v1/surfaces").json()["surfaces"], [])

    def test_an_action_is_relayed_to_river_song(self):
        with patch("core.surfaces_api.APIClient") as client_cls:
            client_cls.return_value.send_surface_action = AsyncMock(return_value={"ok": 1})
            self.client.post("/api/vortex/v1/surfaces", json={"id": "door"})
            resp = self.client.post("/api/vortex/v1/surfaces/door/action",
                                    json={"intent": "unlock.front"})
        self.assertEqual(resp.status_code, 202)
        client_cls.return_value.send_surface_action.assert_awaited_once_with(
            "door", "unlock.front")

    def test_the_card_stays_up_when_the_relay_fails(self):
        """A tap that never reached River Song must not look like one that did."""
        from connectivity.api_client import APIClientError

        self.client.post("/api/vortex/v1/surfaces", json={"id": "door"})
        with patch("core.surfaces_api.APIClient") as client_cls:
            client_cls.return_value.send_surface_action = AsyncMock(
                side_effect=APIClientError("offline"))
            resp = self.client.post("/api/vortex/v1/surfaces/door/action",
                                    json={"intent": "unlock.front"})

        self.assertEqual(resp.status_code, 502)
        self.assertEqual(self.store.top()["id"], "door")

    def test_the_unit_never_interprets_an_intent_itself(self):
        """
        The whole point of relaying: a confirm card on a wall panel is a
        prompt, not an authorisation. Vortex must not act on 'unlock' locally.
        """
        with patch("core.surfaces_api.APIClient") as client_cls:
            client_cls.return_value.send_surface_action = AsyncMock(return_value={})
            self.client.post("/api/vortex/v1/surfaces", json={"id": "door"})
            self.client.post("/api/vortex/v1/surfaces/door/action",
                             json={"intent": "unlock.front"})
        sent = client_cls.return_value.send_surface_action.call_args.args[1]
        self.assertEqual(sent, "unlock.front")


def _later(store, surface_id, seconds):
    """Return a timestamp `seconds` past a stored surface's expiry."""
    return store._surfaces[surface_id]["expires_at"] + seconds


if __name__ == "__main__":
    unittest.main()
