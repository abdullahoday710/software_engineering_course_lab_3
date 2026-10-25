"""Unit tests for the 10 selected features (run: ``python -m unittest -v``).

Each test class maps to one feature F1-F10 from docs/task_b_features.md.
Only the standard library and NumPy are needed; no window is opened.
"""

import os
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smartbrew import catalog, events, inventory, payments  # noqa: E402
from smartbrew.accounts import AccountError  # noqa: E402
from smartbrew.machine import SmartBrewMachine  # noqa: E402
from smartbrew.mood import MoodDetector, SimulatedCamera  # noqa: E402
from smartbrew.recipes import RecipeError  # noqa: E402
from smartbrew.recommender import recommend  # noqa: E402
from smartbrew.weather import Weather  # noqa: E402

VISA = "4242 4242 4242 4242"
_OPEN: list = []


def new_machine() -> SmartBrewMachine:
    """Create a fresh in-memory machine (closed automatically after the tests).

    Returns:
        SmartBrewMachine: machine with seeded demo data.
    """
    m = SmartBrewMachine(":memory:", camera_seed=7)
    _OPEN.append(m)
    return m


def tearDownModule():
    """Close every machine opened by the tests.

    Returns:
        None.
    """
    for m in _OPEN:
        m.close()


def drink(m: SmartBrewMachine, name: str) -> catalog.Drink:
    """Find a drink by name.

    Args:
        m: machine.
        name: drink name.

    Returns:
        catalog.Drink: the drink.
    """
    return next(d for d in catalog.list_drinks(m.conn) if d.name == name)


class F1Accounts(unittest.TestCase):
    """F1 - account creation, credential/NFC login, preference profile."""

    def test_create_login_and_card(self):
        """Check that create login and card.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        u = m.create_account("Sara", "sara@example.com", "secret1", "NFC-77")
        self.assertEqual(m.user.id, u.id)
        m.logout()
        self.assertEqual(m.login("SARA@example.com", "secret1").name, "Sara")
        m.logout()
        self.assertEqual(m.login_card("NFC-77").email, "sara@example.com")

    def test_rejections(self):
        """Check that rejections.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        with self.assertRaises(AccountError):
            m.create_account("X", "demo@smartbrew.local", "abcdef")  # duplicate e-mail
        with self.assertRaises(AccountError):
            m.create_account("X", "not-an-email", "abcdef")
        with self.assertRaises(AccountError):
            m.create_account("X", "x@y.se", "123")  # short password
        with self.assertRaises(AccountError):
            m.login("demo@smartbrew.local", "wrong")
        with self.assertRaises(AccountError):
            m.login_card("UNKNOWN")

    def test_password_not_stored_in_plain_text(self):
        """Check that password not stored in plain text.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.create_account("P", "p@x.se", "plainpass")
        row = m.conn.execute("SELECT pw_hash FROM users WHERE email='p@x.se'").fetchone()
        self.assertNotIn("plainpass", row["pw_hash"])

    def test_preferences_drive_defaults(self):
        """Check that preferences drive defaults.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.login("demo@smartbrew.local", "demo1234")
        m.update_preferences("Almond milk", 5)
        c = m.default_custom(drink(m, "Latte"))
        self.assertEqual((c.milk, c.strength), ("Almond milk", 5))


class F2BrowseAndNutrition(unittest.TestCase):
    """F2 - categories and nutrition information."""

    def test_categories(self):
        """Check that categories.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        self.assertEqual(len(catalog.list_drinks(m.conn)), 12)
        iced = catalog.list_drinks(m.conn, "Iced")
        self.assertTrue(iced and all(d.category == "Iced" for d in iced))

    def test_nutrition_present(self):
        """Check that nutrition present.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        d = drink(m, "Mocha")
        n = catalog.compute_nutrition(d, catalog.default_customization(d))
        self.assertGreater(n.calories, 0)
        self.assertGreater(n.caffeine_mg, 0)


class F3Customization(unittest.TestCase):
    """F3 - live price and nutrition updates."""

    def test_price_and_calories_update(self):
        """Check that price and calories update.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        d = drink(m, "Latte")
        base = catalog.Customization(milk="Whole milk")
        custom = replace(base, milk="Oat milk", syrup_shots=2, extra_shot=True)
        self.assertEqual(catalog.compute_price(d, base), 40.0)
        self.assertEqual(catalog.compute_price(d, custom), 40 + 5 + 8 + 7)
        self.assertLess(catalog.compute_nutrition(d, replace(base, milk="Almond milk")).calories,
                        catalog.compute_nutrition(d, base).calories)
        self.assertGreater(catalog.compute_nutrition(d, custom).sugar_g,
                           catalog.compute_nutrition(d, base).sugar_g)

    def test_normalize_clamps(self):
        """Check that normalize clamps.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        c = catalog.normalize(drink(m, "Espresso"),
                              catalog.Customization(milk="Oat milk", strength=9, syrup_shots=-2))
        self.assertEqual((c.milk, c.strength, c.syrup_shots), ("No milk", 5, 0))
        iced = catalog.normalize(drink(m, "Iced Latte"), catalog.Customization())
        self.assertEqual(iced.temperature, catalog.COLD_TEMPERATURE)


class F4DepletedIngredients(unittest.TestCase):
    """F4 - drinks with depleted ingredients cannot be selected."""

    def test_all_milk_low_greys_out_milk_drinks(self):
        """Check that all milk low greys out milk drinks.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        for milk in catalog.MILK_OPTIONS[1:]:
            inventory.set_level(m.conn, milk, 100)  # below 250 ml threshold
        items = {i.drink.name: i for i in m.menu()}
        self.assertFalse(items["Latte"].available)
        self.assertTrue(items["Espresso"].available)
        res = m.order(drink(m, "Latte"), catalog.Customization(), payments.CARD, VISA)
        self.assertFalse(res.success)

    def test_single_milk_low_switches_option(self):
        """Check that single milk low switches option.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        inventory.set_level(m.conn, "Whole milk", 0)
        items = {i.drink.name: i for i in m.menu()}
        self.assertTrue(items["Latte"].available)
        self.assertNotIn("Whole milk", inventory.available_milks(m.conn, drink(m, "Latte")))
        self.assertNotEqual(items["Latte"].default_custom.milk, "Whole milk")

    def test_beans_depleted_blocks_coffee(self):
        """Check that beans depleted blocks coffee.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        inventory.set_level(m.conn, "Coffee beans", 10)
        items = {i.drink.name: i for i in m.menu()}
        self.assertFalse(items["Espresso"].available)
        self.assertTrue(items["Hot Chocolate"].available)


class F5Payments(unittest.TestCase):
    """F5 - card, Apple Pay, Google Pay, prepaid employee card."""

    def test_luhn(self):
        """Check that luhn.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        self.assertTrue(payments.luhn_valid(VISA))
        self.assertFalse(payments.luhn_valid("4242 4242 4242 4241"))
        self.assertFalse(payments.luhn_valid("abcd"))

    def test_all_methods(self):
        """Check that all methods.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        esp = drink(m, "Espresso")
        c = catalog.default_customization(esp)
        self.assertTrue(m.order(esp, c, payments.CARD, card_number=VISA).success)
        self.assertFalse(m.order(esp, c, payments.CARD, card_number=payments.DECLINED_CARD).success)
        self.assertTrue(m.order(esp, c, payments.APPLE_PAY).success)
        self.assertTrue(m.order(esp, c, payments.GOOGLE_PAY).success)
        self.assertFalse(m.order(esp, c, payments.GOOGLE_PAY, token_ok=False).success)
        self.assertTrue(m.order(esp, c, payments.PREPAID, card_id="NFC-EMP-1001").success)
        bal = m.conn.execute("SELECT prepaid_balance FROM users WHERE card_id='NFC-EMP-1001'").fetchone()[0]
        self.assertEqual(bal, 150 - 25)

    def test_prepaid_insufficient(self):
        """Check that prepaid insufficient.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.conn.execute("UPDATE users SET prepaid_balance = 5")
        esp = drink(m, "Espresso")
        res = m.order(esp, catalog.default_customization(esp), payments.PREPAID,
                      card_id="NFC-EMP-1001")
        self.assertFalse(res.success)

    def test_offline_fallback(self):
        """Check that offline fallback.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.set_online(False)
        esp = drink(m, "Espresso")
        c = catalog.default_customization(esp)
        self.assertFalse(m.order(esp, c, payments.APPLE_PAY).success)
        res = m.order(esp, c, payments.CARD, card_number=VISA)
        self.assertTrue(res.success and res.transaction.offline)
        self.assertEqual(m.set_online(True), 1)
        self.assertTrue(m.history(all_users=True)[0].synced)


class F6TransactionRecording(unittest.TestCase):
    """F6 - every completed transaction is stored with its customisation."""

    def test_recorded_with_parameters(self):
        """Check that recorded with parameters.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.login("demo@smartbrew.local", "demo1234")
        lat = drink(m, "Latte")
        c = catalog.Customization(milk="Oat milk", strength=4, syrup="Caramel", syrup_shots=2)
        res = m.order(lat, c, payments.CARD, card_number=VISA)
        tx = m.history()[0]
        self.assertEqual(tx.id, res.transaction.id)
        self.assertEqual((tx.custom.milk, tx.custom.syrup_shots, tx.custom.syrup),
                         ("Oat milk", 2, "Caramel"))
        self.assertEqual(tx.user_id, m.user.id)

    def test_declined_not_recorded_and_anonymous_recorded(self):
        """Check that declined not recorded and anonymous recorded.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        esp = drink(m, "Espresso")
        c = catalog.default_customization(esp)
        m.order(esp, c, payments.CARD, card_number=payments.DECLINED_CARD)
        self.assertEqual(m.history(all_users=True), [])
        m.order(esp, c, payments.CARD, card_number=VISA)
        self.assertIsNone(m.history(all_users=True)[0].user_id)

    def test_stock_consumed(self):
        """Check that stock consumed.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        before = inventory.get_ingredients(m.conn)["Cups"].level
        esp = drink(m, "Espresso")
        m.order(esp, catalog.default_customization(esp), payments.CARD, card_number=VISA)
        self.assertEqual(inventory.get_ingredients(m.conn)["Cups"].level, before - 1)


class F7SavedRecipes(unittest.TestCase):
    """F7 - save, rename, edit, delete and one-touch order recipes."""

    def test_recipe_lifecycle(self):
        """Check that recipe lifecycle.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.login("demo@smartbrew.local", "demo1234")
        lat = drink(m, "Latte")
        r = m.save_recipe("Morning boost", lat, catalog.Customization(milk="Oat milk", extra_shot=True))
        with self.assertRaises(RecipeError):
            m.save_recipe("morning BOOST", lat, catalog.Customization())
        r2 = m.update_recipe(r.id, "Big boost", replace(r.custom, syrup_shots=1))
        self.assertEqual((r2.name, r2.custom.syrup_shots), ("Big boost", 1))
        res = m.order_recipe(r.id, payments.CARD, card_number=VISA)
        self.assertTrue(res.success)
        self.assertTrue(res.transaction.custom.extra_shot)
        m.delete_recipe(r.id)
        self.assertEqual(m.my_recipes(), [])

    def test_requires_login_and_ownership(self):
        """Check that requires login and ownership.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        with self.assertRaises(AccountError):
            m.save_recipe("x", drink(m, "Latte"), catalog.Customization())
        m.login("demo@smartbrew.local", "demo1234")
        r = m.save_recipe("Mine", drink(m, "Latte"), catalog.Customization())
        m.create_account("Other", "o@x.se", "secret1")
        with self.assertRaises(RecipeError):
            m.delete_recipe(r.id)


class F8Recommendations(unittest.TestCase):
    """F8 - scores from time, weather and history; menu reordered and highlighted."""

    def test_cold_morning_with_history(self):
        """Check that cold morning with history.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        drinks = catalog.list_drinks(m.conn)
        capp = drink(m, "Cappuccino")
        recs = recommend(drinks, 8, Weather(2, "Snowy"), Counter({capp.id: 10}))
        self.assertEqual(recs[0].drink.name, "Cappuccino")
        self.assertTrue(recs[0].highlighted)
        self.assertTrue(any("ordered" in r for r in recs[0].reasons))

    def test_hot_afternoon_prefers_iced(self):
        """Check that hot afternoon prefers iced.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        recs = recommend(catalog.list_drinks(m.conn), 14, Weather(28, "Sunny"))
        self.assertTrue(recs[0].drink.is_cold)

    def test_evening_low_caffeine_and_weather_outage(self):
        """Check that evening low caffeine and weather outage.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        recs = recommend(catalog.list_drinks(m.conn), 21, None)
        self.assertEqual(recs[0].drink.name, "Hot Chocolate")

    def test_menu_uses_history(self):
        """Check that menu uses history.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.hour_override = 14
        m.login("demo@smartbrew.local", "demo1234")
        fw = drink(m, "Flat White")
        for _ in range(5):
            m.order(fw, m.default_custom(fw), payments.CARD, card_number=VISA)
        self.assertEqual(m.menu()[0].drink.name, "Flat White")


class F9MoodDetection(unittest.TestCase):
    """F9 - mood from the camera, processed only in memory."""

    def test_moods_detected(self):
        """Check that moods detected.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        cam, det = SimulatedCamera(1), MoodDetector()
        for mood in ["Tired", "Happy", "Stressed", "Neutral"]:
            self.assertEqual(det.analyze(cam.capture(mood)).mood, mood)

    def test_frame_wiped_and_nothing_stored(self):
        """Check that frame wiped and nothing stored.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        cam, det = SimulatedCamera(2), MoodDetector()
        frame = cam.capture("Tired")
        det.analyze(frame)
        self.assertFalse(frame.any())          # pixel buffer zeroed
        self.assertTrue(det.last_buffer_cleared)
        self.assertEqual(det.frames_stored, 0)

    def test_no_files_written(self):
        """Check that no files written.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                m = SmartBrewMachine(":memory:", camera_seed=3)
                m.scan_mood("Happy")
                self.assertEqual(os.listdir(tmp), [])
                m.close()
            finally:
                os.chdir(old)

    def test_tired_adds_extra_shot_and_ranks_caffeine(self):
        """Check that tired adds extra shot and ranks caffeine.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.hour_override = 21
        m.scan_mood("Tired")
        self.assertTrue(m.default_custom(drink(m, "Latte")).extra_shot)
        top = m.menu()[0].drink
        self.assertGreaterEqual(top.caffeine_mg, 95)


class F10AdminMode(unittest.TestCase):
    """F10 - secure admin access, refills, bins and error log."""

    def test_access_methods_and_lockout(self):
        """Check that access methods and lockout.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        self.assertFalse(m.admin_login("PIN", "0000")[0])
        self.assertFalse(m.admin_login("PIN", "1111")[0])
        ok, msg = m.admin_login("PIN", "2222")
        self.assertIn("Locked", msg)
        self.assertFalse(m.admin_login("PIN", "1234")[0])   # still locked
        self.assertTrue(m.admin_login("NFC", "NFC-MASTER-0001")[0] is False)  # also locked
        m2 = new_machine()
        self.assertTrue(m2.admin_login("PIN", "1234")[0])
        m3 = new_machine()
        self.assertTrue(m3.admin_login("Key", "KEY-SB-SERVICE")[0])

    def test_refill_requires_admin(self):
        """Check that refill requires admin.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        inventory.set_level(m.conn, "Whole milk", 10)
        with self.assertRaises(PermissionError):
            m.refill("Whole milk")
        m.admin_login("NFC", "NFC-MASTER-0001")
        m.refill("Whole milk")
        self.assertEqual(inventory.get_ingredients(m.conn)["Whole milk"].ratio, 1.0)

    def test_bins_alert_and_halt(self):
        """Check that bins alert and halt.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        inventory.set_bin_level(m.conn, "Coffee grounds", 500)
        self.assertTrue(any("needs emptying" in e.message for e in events.recent(m.conn)))
        inventory.set_bin_level(m.conn, "Coffee grounds", 600)
        self.assertTrue(m.halt_reasons())
        esp = drink(m, "Espresso")
        self.assertFalse(m.order(esp, catalog.default_customization(esp), payments.CARD,
                                 card_number=VISA).success)
        m.admin_login("PIN", "1234")
        m.empty_bin("Coffee grounds")
        self.assertEqual(m.halt_reasons(), [])

    def test_faults_logged_and_resolved(self):
        """Check that faults logged and resolved.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        m.inject_fault("Grinder Jammed")
        self.assertEqual(len(events.active_errors(m.conn)), 1)
        items = {i.drink.name: i for i in m.menu()}
        self.assertFalse(items["Espresso"].available)
        self.assertTrue(items["Hot Chocolate"].available)
        m.admin_login("PIN", "1234")
        m.resolve_fault(events.active_errors(m.conn)[0].id)
        self.assertEqual(events.active_errors(m.conn), [])

    def test_low_threshold_event(self):
        """Check that low threshold event.

        Returns:
            None. Fails the test if the behaviour is wrong.
        """
        m = new_machine()
        inventory.set_level(m.conn, "Cups", 6)
        esp = drink(m, "Espresso")
        m.order(esp, catalog.default_customization(esp), payments.CARD, card_number=VISA)
        self.assertTrue(any("Low Ingredient Threshold: Cups" in e.message
                            for e in events.recent(m.conn)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
