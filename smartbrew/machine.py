"""``SmartBrewMachine``: the facade that ties all services together.

The GUI talks only to this class, and the tests drive the same methods, so
every feature can be checked without opening a window.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from . import accounts, admin, catalog, events, inventory, payments, recipes, transactions
from .catalog import Customization, Drink
from .db import connect
from .mood import MoodDetector, MoodResult, SimulatedCamera
from .recommender import Recommendation, recommend
from .weather import ServiceUnavailable, Weather, WeatherService


@dataclass
class MenuItem:
    """One drink as shown on the menu: score, availability and defaults."""

    rec: Recommendation
    available: bool
    blockers: list[str]
    default_custom: Customization

    @property
    def drink(self) -> Drink:
        """Shortcut to the drink.

        Returns:
            Drink: the menu item's drink.
        """
        return self.rec.drink


@dataclass(frozen=True)
class OrderResult:
    """Outcome of an order attempt."""

    success: bool
    message: str
    transaction: transactions.Transaction | None = None
    payment: payments.PaymentResult | None = None


class SmartBrewMachine:
    """Application core of the SmartBrew AI coffee machine."""

    def __init__(self, db_path: str = "smartbrew.db", camera_seed: int | None = None) -> None:
        """Open the database and initialise all subsystems.

        Args:
            db_path: SQLite file, or ``":memory:"`` for a temporary machine.
            camera_seed: seed for the simulated camera noise (tests use a fixed one).

        Returns:
            None.
        """
        self.conn = connect(db_path)
        self.weather = WeatherService()
        self.user: accounts.User | None = None
        self.gate = admin.AdminGate(self.conn)
        self.admin_unlocked = False
        self.camera = SimulatedCamera(camera_seed)
        self.detector = MoodDetector()
        self.last_mood: MoodResult | None = None
        self.hour_override: int | None = None
        events.log(self.conn, events.INFO, "System", "Machine started")

    def close(self) -> None:
        """Close the database connection (call on application exit).

        Returns:
            None.
        """
        self.conn.close()

    # ------------------------------------------------------------ environment
    @property
    def online(self) -> bool:
        """Whether the network and external services are reachable.

        Returns:
            bool: network state.
        """
        return self.weather.online

    def set_online(self, online: bool) -> int:
        """Switch the simulated network on/off; uploads offline payments on reconnect.

        Args:
            online: new network state.

        Returns:
            int: number of offline transactions uploaded (0 if none or going offline).
        """
        was = self.weather.online
        self.weather.online = online
        if was and not online:
            events.log(self.conn, events.WARNING, "Network",
                       "Network lost - fallback to basic ordering and offline card payment")
        if online and not was:
            pending = transactions.unsynced(self.conn)
            transactions.mark_synced(self.conn, [t.id for t in pending])
            events.log(self.conn, events.INFO, "Network",
                       f"Network restored - uploaded {len(pending)} offline payment(s)")
            return len(pending)
        return 0

    def current_hour(self) -> int:
        """Return the hour used for recommendations (real clock or simulated).

        Returns:
            int: 0-23.
        """
        return self.hour_override if self.hour_override is not None else datetime.now().hour

    def weather_or_none(self) -> Weather | None:
        """Read the weather, swallowing outages (graceful fallback).

        Returns:
            Weather | None: reading, or None when the service is unavailable.
        """
        try:
            return self.weather.get()
        except ServiceUnavailable:
            return None

    # --------------------------------------------------------------- accounts
    def create_account(self, name: str, email: str, password: str,
                       card_id: str | None = None) -> accounts.User:
        """Register a user and log them in (F1).

        Args:
            name: display name.
            email: unique e-mail.
            password: at least 6 characters.
            card_id: optional NFC/employee card id.

        Returns:
            accounts.User: the new, logged-in user.

        Raises:
            accounts.AccountError: validation failure.
        """
        self.user = accounts.create_account(self.conn, name, email, password, card_id)
        events.log(self.conn, events.INFO, "Accounts", f"Account created for {self.user.email}")
        return self.user

    def login(self, email: str, password: str) -> accounts.User:
        """Log in with credentials (F1).

        Args:
            email: registered e-mail.
            password: password.

        Returns:
            accounts.User: logged-in user.

        Raises:
            accounts.AccountError: wrong credentials.
        """
        self.user = accounts.login_with_credentials(self.conn, email, password)
        return self.user

    def login_card(self, card_id: str) -> accounts.User:
        """Log in by NFC/card tap (F1).

        Args:
            card_id: card identifier.

        Returns:
            accounts.User: logged-in user.

        Raises:
            accounts.AccountError: unknown card.
        """
        self.user = accounts.login_with_card(self.conn, card_id)
        return self.user

    def logout(self) -> None:
        """Log out the current user and forget the detected mood.

        Returns:
            None.
        """
        self.user = None
        self.last_mood = None

    def refresh_user(self) -> None:
        """Reload the logged-in user from the database (e.g. new balance).

        Returns:
            None.
        """
        if self.user:
            self.user = accounts.get_user(self.conn, self.user.id)

    def update_preferences(self, milk: str, strength: int) -> accounts.User:
        """Save the logged-in user's preference profile (F1).

        Args:
            milk: preferred milk.
            strength: preferred strength 1-5.

        Returns:
            accounts.User: updated user.

        Raises:
            accounts.AccountError: not logged in or invalid values.
        """
        self._require_user()
        self.user = accounts.update_preferences(self.conn, self.user.id, milk, strength)
        return self.user

    def link_card(self, card_id: str) -> accounts.User:
        """Link an NFC/employee card to the logged-in user (F1).

        Args:
            card_id: card identifier.

        Returns:
            accounts.User: updated user.

        Raises:
            accounts.AccountError: not logged in or card taken.
        """
        self._require_user()
        self.user = accounts.link_card(self.conn, self.user.id, card_id)
        return self.user

    def _require_user(self) -> None:
        """Ensure someone is logged in.

        Returns:
            None.

        Raises:
            accounts.AccountError: when nobody is logged in.
        """
        if self.user is None:
            raise accounts.AccountError("Please log in first.")

    # ------------------------------------------------------------------- menu
    def default_custom(self, drink: Drink) -> Customization:
        """Starting customisation for a drink, using the user's profile and mood.

        Args:
            drink: selected drink.

        Returns:
            Customization: defaults (extra shot added if the user looks tired).
        """
        if self.user:
            custom = catalog.default_customization(drink, self.user.default_milk,
                                                   self.user.default_strength)
        else:
            custom = catalog.default_customization(drink)
        if self.last_mood and self.last_mood.mood == "Tired" and drink.has_coffee:
            custom = replace(custom, extra_shot=True)
        if drink.has_milk:
            milks = inventory.available_milks(self.conn, drink)
            if milks and custom.milk not in milks:
                custom = replace(custom, milk=milks[0])
        return custom

    def halt_reasons(self) -> list[str]:
        """Reasons the whole machine is out of service.

        Returns:
            list[str]: empty when the machine can serve drinks.
        """
        return [f"{b.name} bin is full" for b in inventory.get_bins(self.conn).values() if b.full]

    def fault_blockers(self, drink: Drink) -> list[str]:
        """Active hardware faults that prevent making this drink.

        Args:
            drink: candidate drink.

        Returns:
            list[str]: fault names that block it.
        """
        out = []
        for fault, scope in events.FAULTS.items():
            if not events.has_active(self.conn, fault):
                continue
            if (scope == "coffee" and drink.has_coffee) or (scope == "milk" and drink.has_milk) \
                    or (scope == "hot" and not drink.is_cold):
                out.append(fault)
        return out

    def blockers(self, drink: Drink, custom: Customization) -> list[str]:
        """Everything that prevents ordering this customised drink (F4 + faults).

        Args:
            drink: selected drink.
            custom: chosen customisation.

        Returns:
            list[str]: human-readable blockers; empty if it can be ordered.
        """
        out = self.halt_reasons() + self.fault_blockers(drink)
        out += [f"{name} depleted" for name in inventory.missing_for(self.conn, drink, custom)]
        return out

    def menu(self, category: str = "All") -> list[MenuItem]:
        """Build the menu: recommendation-ordered, with availability (F2/F4/F8).

        Args:
            category: category filter.

        Returns:
            list[MenuItem]: best-scored first; unavailable drinks are included
            (shown greyed out) but never highlighted.
        """
        drinks = catalog.list_drinks(self.conn, category)
        counts = transactions.drink_counts(self.conn, self.user.id) if self.user else None
        mood = self.last_mood.mood if self.last_mood else None
        recs = recommend(drinks, self.current_hour(), self.weather_or_none(), counts, mood)
        items = []
        for rec in recs:
            custom = self.default_custom(rec.drink)
            ok, missing = inventory.drink_availability(self.conn, rec.drink, custom)
            blockers = self.halt_reasons() + self.fault_blockers(rec.drink) + \
                [f"{m} depleted" for m in missing]
            items.append(MenuItem(rec, ok and not blockers, blockers, custom))
        unavailable = [i for i in items if not i.available]
        for i in unavailable:
            i.rec.highlighted = False
        # Re-highlight so the top-N *available* drinks carry the star.
        avail = [i for i in items if i.available]
        for i in avail:
            i.rec.highlighted = False
        for i in avail[:3]:
            i.rec.highlighted = i.rec.score > 0
        return avail + unavailable

    # ------------------------------------------------------------------- mood
    def scan_mood(self, expression: str) -> MoodResult:
        """Capture a frame, detect the mood in memory and discard the frame (F9).

        Args:
            expression: expression the simulated customer shows.

        Returns:
            MoodResult: mood, confidence and suggestion.
        """
        frame = self.camera.capture(expression)
        self.last_mood = self.detector.analyze(frame)
        del frame
        return self.last_mood

    def clear_mood(self) -> None:
        """Forget the detected mood.

        Returns:
            None.
        """
        self.last_mood = None

    # ------------------------------------------------------------------ order
    def order(self, drink: Drink, custom: Customization, method: str, card_number: str = "",
              card_id: str = "", token_ok: bool = True) -> OrderResult:
        """Validate, pay, dispense and record one drink (F3-F6).

        Args:
            drink: selected drink.
            custom: chosen customisation.
            method: payment method from :data:`payments.METHODS`.
            card_number: card number for card payments.
            card_id: employee card id for prepaid payments.
            token_ok: wallet authorisation result.

        Returns:
            OrderResult: success flag, message, stored transaction and payment result.
        """
        custom = catalog.normalize(drink, custom)
        blockers = self.blockers(drink, custom)
        if blockers:
            return OrderResult(False, "Cannot make this drink: " + "; ".join(blockers))
        if method == payments.CARD and events.has_active(self.conn, "Payment Terminal Offline"):
            return OrderResult(False, "Card terminal is out of order. Please use another method.")
        price = catalog.compute_price(drink, custom)
        result = payments.process(self.conn, method, price, self.online, card_number,
                                  card_id, token_ok)
        if not result.approved:
            events.log(self.conn, events.INFO, "Payments", f"{method} declined: {result.message}")
            return OrderResult(False, result.message, payment=result)
        inventory.consume(self.conn, drink, custom)
        tx = transactions.record(self.conn, self.user.id if self.user else None, drink, custom,
                                 price, method, result.reference, result.offline)
        self.refresh_user()
        return OrderResult(True, f"Enjoy your {drink.name}! {result.message}", tx, result)

    # ---------------------------------------------------------------- recipes
    def save_recipe(self, name: str, drink: Drink, custom: Customization) -> recipes.Recipe:
        """Save the current customisation as a named recipe (F7).

        Args:
            name: unique recipe name.
            drink: base drink.
            custom: customisation.

        Returns:
            recipes.Recipe: saved recipe.

        Raises:
            accounts.AccountError: not logged in.
            recipes.RecipeError: invalid name.
        """
        self._require_user()
        return recipes.save_recipe(self.conn, self.user.id, name, drink.id,
                                   catalog.normalize(drink, custom))

    def update_recipe(self, recipe_id: int, name: str, custom: Customization) -> recipes.Recipe:
        """Rename/modify a saved recipe owned by the current user (F7).

        Args:
            recipe_id: recipe id.
            name: new name.
            custom: new customisation.

        Returns:
            recipes.Recipe: updated recipe.

        Raises:
            accounts.AccountError: not logged in.
            recipes.RecipeError: not the owner or invalid name.
        """
        self._require_user()
        rec = recipes.get_recipe(self.conn, recipe_id)
        if rec.user_id != self.user.id:
            raise recipes.RecipeError("You can only edit your own recipes.")
        drink = catalog.get_drink(self.conn, rec.drink_id)
        return recipes.update_recipe(self.conn, recipe_id, name, catalog.normalize(drink, custom))

    def delete_recipe(self, recipe_id: int) -> None:
        """Delete a saved recipe owned by the current user (F7).

        Args:
            recipe_id: recipe id.

        Returns:
            None.

        Raises:
            accounts.AccountError: not logged in.
            recipes.RecipeError: not the owner.
        """
        self._require_user()
        if recipes.get_recipe(self.conn, recipe_id).user_id != self.user.id:
            raise recipes.RecipeError("You can only delete your own recipes.")
        recipes.delete_recipe(self.conn, recipe_id)

    def my_recipes(self) -> list[recipes.Recipe]:
        """List the current user's recipes.

        Returns:
            list[recipes.Recipe]: empty for guests.
        """
        return recipes.list_recipes(self.conn, self.user.id) if self.user else []

    def order_recipe(self, recipe_id: int, method: str, **pay_kwargs) -> OrderResult:
        """One-touch order of a saved recipe (F7).

        Args:
            recipe_id: recipe to order.
            method: payment method.
            **pay_kwargs: ``card_number``, ``card_id`` or ``token_ok`` for :meth:`order`.

        Returns:
            OrderResult: as :meth:`order`.
        """
        rec = recipes.get_recipe(self.conn, recipe_id)
        drink = catalog.get_drink(self.conn, rec.drink_id)
        return self.order(drink, rec.custom, method, **pay_kwargs)

    # ---------------------------------------------------------------- history
    def history(self, all_users: bool = False) -> list[transactions.Transaction]:
        """Transactions of the current user, or of the whole machine.

        Args:
            all_users: True for the machine-wide log (admin view).

        Returns:
            list[transactions.Transaction]: newest first.
        """
        if all_users:
            return transactions.history(self.conn)
        return transactions.history(self.conn, self.user.id) if self.user else []

    # ------------------------------------------------------------------ admin
    def admin_login(self, method: str, secret: str) -> tuple[bool, str]:
        """Enter admin mode by ``"PIN"``, ``"NFC"`` master card or physical ``"Key"`` (F10).

        Args:
            method: credential type.
            secret: PIN digits, card id or key id.

        Returns:
            tuple[bool, str]: (granted, message).
        """
        if method == "PIN":
            ok, msg = self.gate.try_pin(secret)
        elif method == "NFC":
            ok, msg = self.gate.try_master_card(secret)
        else:
            ok, msg = self.gate.try_physical_key(secret)
        self.admin_unlocked = self.admin_unlocked or ok
        return ok, msg

    def admin_logout(self) -> None:
        """Leave admin mode.

        Returns:
            None.
        """
        self.admin_unlocked = False
        events.log(self.conn, events.INFO, "Admin", "Admin mode closed")

    def _require_admin(self) -> None:
        """Ensure admin mode is unlocked.

        Returns:
            None.

        Raises:
            PermissionError: when admin mode is locked.
        """
        if not self.admin_unlocked:
            raise PermissionError("Admin mode required.")

    def refill(self, ingredient: str) -> None:
        """Register a refill and reset the counter to maximum (F10).

        Args:
            ingredient: ingredient name.

        Returns:
            None.

        Raises:
            PermissionError: admin mode locked.
        """
        self._require_admin()
        inventory.refill(self.conn, ingredient)

    def refill_all(self) -> None:
        """Refill every ingredient (F10).

        Returns:
            None.

        Raises:
            PermissionError: admin mode locked.
        """
        self._require_admin()
        for name in inventory.get_ingredients(self.conn):
            inventory.refill(self.conn, name)

    def empty_bin(self, name: str) -> None:
        """Record that a bin was emptied (F10).

        Args:
            name: bin name.

        Returns:
            None.

        Raises:
            PermissionError: admin mode locked.
        """
        self._require_admin()
        inventory.empty_bin(self.conn, name)

    def resolve_fault(self, event_id: int) -> None:
        """Mark an active fault as fixed (F10).

        Args:
            event_id: event log id.

        Returns:
            None.

        Raises:
            PermissionError: admin mode locked.
        """
        self._require_admin()
        events.resolve(self.conn, event_id)

    def inject_fault(self, fault: str) -> None:
        """Simulate a hardware fault signal (demo control).

        Args:
            fault: a key of :data:`events.FAULTS`.

        Returns:
            None.
        """
        if not events.has_active(self.conn, fault):
            events.log(self.conn, events.ERROR, fault.split()[0], fault, active=True)
