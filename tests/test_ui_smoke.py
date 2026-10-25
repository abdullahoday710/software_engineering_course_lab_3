"""Headless smoke test of the immediate-mode GUI.

The real ``SmartBrewApp.gui`` is executed frame by frame against a fake
``imgui`` module (tests/fake_imgui.py). Scripted clicks drive complete user
journeys, proving the UI code paths work end to end without a display.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_imgui  # noqa: E402

FAKE = fake_imgui.install()

from smartbrew.machine import SmartBrewMachine  # noqa: E402
from smartbrew.ui.app import SmartBrewApp  # noqa: E402


class UISmoke(unittest.TestCase):
    """End-to-end journeys through the GUI."""

    def setUp(self):
        """Create a fresh in-memory machine and UI before each test.

        Returns:
            None.
        """
        self.m = SmartBrewMachine(":memory:", camera_seed=5)
        self.app = SmartBrewApp(self.m)
        FAKE.clicks.clear()
        FAKE.inputs.clear()

    def tearDown(self):
        """Close the machine's database after each test.

        Returns:
            None.
        """
        self.m.close()

    def frame(self, clicks=(), inputs=None):
        """Draw one frame with scripted clicks/inputs.

        Args:
            clicks: label substrings to click.
            inputs: label substring -> value for value widgets.

        Returns:
            None.
        """
        FAKE.clicks = set(clicks)
        FAKE.inputs = dict(inputs or {})
        FAKE.labels.clear()
        FAKE.texts.clear()
        self.app.dirty()
        self.app.gui()
        self.assertEqual(FAKE.stack, 0, "begin/end calls are unbalanced")

    def test_idle_frames(self):
        """Check that idle frames.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        for _ in range(3):
            self.frame()
        self.assertTrue(any("Latte" in label for label in FAKE.labels))

    def test_guest_orders_and_pays_by_card(self):
        """Check that guest orders and pays by card.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        self.frame()
        latte_id = next(i.drink.id for i in self.m.menu() if i.drink.name == "Latte")
        self.frame(clicks={f"##card{latte_id}"})
        self.assertEqual(self.app.selected.name, "Latte")
        self.frame(inputs={"Syrup shots##main": 2})
        self.assertEqual(self.app.custom.syrup_shots, 2)
        self.frame(clicks={"Order & pay"})
        self.assertEqual(self.app.stage, "pay")
        self.frame(clicks={"Pay "})
        self.assertEqual(self.app.stage, "done")
        self.assertTrue(self.app.result.success, self.app.result.message)
        self.frame()
        self.assertEqual(self.m.history(all_users=True)[0].custom.syrup_shots, 2)

    def test_login_save_recipe_one_touch(self):
        """Check that login save recipe one touch.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        self.frame(inputs={"Password##login": "demo1234"})
        self.frame(clicks={"Log in"})
        self.assertIsNotNone(self.m.user)
        mocha_id = next(i.drink.id for i in self.m.menu() if i.drink.name == "Mocha")
        self.frame(clicks={f"##card{mocha_id}"})
        self.frame(inputs={"##rname": "Choc fix"})
        self.frame(clicks={"Save##recipe"})
        self.assertEqual([r.name for r in self.m.my_recipes()], ["Choc fix"])
        rid = self.m.my_recipes()[0].id
        self.frame(clicks={f"1-Touch##{rid}"})
        self.assertEqual(self.m.history()[0].drink_name, "Mocha")
        self.frame(clicks={f"Edit##{rid}"})
        self.frame(inputs={"Name##edit": "Choc fix XL"})
        self.frame(clicks={"Save changes"})
        self.assertEqual(self.m.my_recipes()[0].name, "Choc fix XL")

    def test_register_and_card_tap(self):
        """Check that register and card tap.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        self.frame(inputs={"Name##reg": "Ali", "E-mail##reg": "ali@x.se",
                           "Password##reg": "secret1", "NFC card (optional)##reg": "NFC-9"})
        self.frame(clicks={"Create account"})
        self.assertEqual(self.m.user.name, "Ali")
        self.frame(clicks={"Log out"})
        self.frame(inputs={"Card ID##tap": "NFC-9"})
        self.frame(clicks={"Tap card on reader"})
        self.assertEqual(self.m.user.email, "ali@x.se")

    def test_mood_scan_and_simulator(self):
        """Check that mood scan and simulator.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        self.frame(inputs={"##face": 1})        # Tired
        self.frame(clicks={"Scan my mood"})
        self.assertEqual(self.m.last_mood.mood, "Tired")
        self.frame(clicks={"Trigger: Grinder Jammed"})
        self.frame(inputs={"Network / external services online": False})
        self.assertFalse(self.m.online)
        self.frame(clicks={"Drain all milks"})
        latte = next(i for i in self.m.menu() if i.drink.name == "Latte")
        self.assertFalse(latte.available)

    def test_admin_keypad_refill_and_resolve(self):
        """Check that admin keypad refill and resolve.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        self.m.inject_fault("Water Heater Fault")
        for key in "1234":
            self.frame(clicks={f"##key{key}"})
        self.frame(clicks={"Enter PIN"})
        self.assertTrue(self.m.admin_unlocked)
        self.frame(clicks={"Refill all", "Resolve##"})
        from smartbrew import events
        self.assertEqual(events.active_errors(self.m.conn), [])
        self.frame(inputs={"Show all machine transactions": True})
        self.frame(clicks={"Exit admin mode"})
        self.assertFalse(self.m.admin_unlocked)


if __name__ == "__main__":
    unittest.main(verbosity=2)
