"""SmartBrew AI touchscreen built with Dear ImGui (immediate mode, via imgui-bundle).

Immediate mode means the whole screen is redrawn every frame from the current
state: :meth:`SmartBrewApp.gui` is called ~60 times per second and simply
asks the :class:`~smartbrew.machine.SmartBrewMachine` what to show. Widgets
return their new values directly (``changed, value = imgui.slider_int(...)``),
so there are no callbacks or widget objects to keep in sync.

Tabs:
    Menu        - browse, recommendations, mood scan, customise, pay (F2-F6, F8, F9)
    My account  - login / register / NFC tap, preferences, saved recipes (F1, F7)
    History     - recorded transactions (F6)
    Admin       - technician mode: refills, bins, errors, event log (F10)
    Simulator   - hardware/environment controls for the demo (clock, weather,
                  network, sensors, faults)
"""

from __future__ import annotations

import time
from dataclasses import replace

from imgui_bundle import imgui

from .. import catalog, events, inventory, payments
from ..accounts import AccountError
from ..admin import PHYSICAL_KEY_ID
from ..catalog import CURRENCY, Customization, Drink
from ..db import DEMO_MASTER_CARD
from ..machine import MenuItem, OrderResult, SmartBrewMachine
from ..mood import MOODS
from ..recipes import RecipeError
from ..weather import CONDITIONS
from . import theme as T
from .theme import ImVec2

TABS = ["Menu", "My account", "History", "Admin", "Simulator"]
CARD_W, CARD_H = 190.0, 104.0
MENU_REFRESH_S = 1.0
ERROR_LOG = "smartbrew_error.log"


class SmartBrewApp:
    """Holds UI state and draws one frame per :meth:`gui` call."""

    def __init__(self, machine: SmartBrewMachine) -> None:
        """Create the UI around a machine.

        Args:
            machine: application core to display and control.

        Returns:
            None.
        """
        self.m = machine
        self.theme_applied = False
        self.jump_tab: str | None = None
        self.toast_text, self.toast_color, self.toast_until = "", T.CREAM, 0.0
        # menu / order flow
        self.category = "All"
        self.menu_cache: list[MenuItem] = []
        self.menu_time = 0.0
        self.selected: Drink | None = None
        self.custom = Customization()
        self.stage = "customize"            # customize -> pay -> done
        self.pay_method = 0
        self.card_number = "4242 4242 4242 4242"
        self.prepaid_id = ""
        self.wallet_ok = True
        self.result: OrderResult | None = None
        self.recipe_name = ""
        self.mood_face = 1
        # account forms
        self.login_email, self.login_pw, self.tap_id = "demo@smartbrew.local", "", "NFC-EMP-1001"
        self.reg_name = self.reg_email = self.reg_pw = self.reg_card = ""
        self.form_error = ""
        self.link_card_id = ""
        self.edit_recipe_id: int | None = None
        self.edit_name = ""
        self.edit_custom = Customization()
        # admin
        self.admin_pin = ""
        self.admin_card = ""
        self.admin_msg = ""
        self.log_filter = 0
        self.history_all = False
        # simulator
        self.sim_clock = False
        self.sim_hour = 8

    # ================================================================ helpers
    def toast(self, text: str, color=T.GREEN, seconds: float = 4.0) -> None:
        """Show a short status message in the top bar.

        Args:
            text: message.
            color: text colour.
            seconds: how long to show it.

        Returns:
            None.
        """
        self.toast_text, self.toast_color = text, color
        self.toast_until = time.monotonic() + seconds

    def dirty(self) -> None:
        """Force the menu to be recomputed on the next frame (after any change).

        Returns:
            None.
        """
        self.menu_time = 0.0

    def menu_items(self) -> list[MenuItem]:
        """Return the cached menu, refreshing it at most once per second.

        Returns:
            list[MenuItem]: recommendation-ordered menu.
        """
        now = time.monotonic()
        if now - self.menu_time > MENU_REFRESH_S:
            self.menu_cache = self.m.menu(self.category)
            self.menu_time = now
        return self.menu_cache

    def select_drink(self, drink: Drink, custom: Customization | None = None) -> None:
        """Open a drink in the detail panel.

        Args:
            drink: drink to show.
            custom: starting customisation; profile/mood defaults if None.

        Returns:
            None.
        """
        self.selected = drink
        self.custom = custom or self.m.default_custom(drink)
        self.stage = "customize"
        self.result = None

    def begin_tab(self, label: str) -> bool:
        """Begin a tab item, selecting it if a jump to it was requested.

        Args:
            label: tab label.

        Returns:
            bool: True if the tab is open and its content should be drawn.
        """
        flag = 0
        if self.jump_tab == label:
            flag = int(T.enum_member(imgui.TabItemFlags_, "set_selected"))
            self.jump_tab = None
        opened, _ = imgui.begin_tab_item(label, None, flag)
        return opened

    # ============================================================ main frame
    def gui(self) -> None:
        """Draw one full frame. Called by the imgui-bundle runner every frame.

        Returns:
            None.
        """
        if not self.theme_applied:
            T.apply_theme()
            self.theme_applied = True
        viewport = imgui.get_main_viewport()
        imgui.set_next_window_pos(viewport.work_pos)
        imgui.set_next_window_size(viewport.work_size)
        # NOTE: no "no_bring_to_front_on_focus" flag here - Dear ImGui creates such a
        # window at the BACK of the z-order, which hides the whole UI.
        win_flags = T.flags(imgui.WindowFlags_.no_decoration, imgui.WindowFlags_.no_move,
                            imgui.WindowFlags_.no_saved_settings)
        imgui.begin("SmartBrew AI", None, win_flags)
        self.draw_top_bar()
        if imgui.begin_tab_bar("tabs"):
            if self.begin_tab("Menu"):
                self.draw_menu_tab()
                imgui.end_tab_item()
            if self.begin_tab("My account"):
                self.draw_account_tab()
                imgui.end_tab_item()
            if self.begin_tab("History"):
                self.draw_history_tab()
                imgui.end_tab_item()
            if self.begin_tab("Admin"):
                self.draw_admin_tab()
                imgui.end_tab_item()
            if self.begin_tab("Simulator"):
                self.draw_simulator_tab()
                imgui.end_tab_item()
            imgui.end_tab_bar()
        imgui.end()

    def draw_top_bar(self) -> None:
        """Draw the title, status chips (user, network, machine, admin) and toast.

        Returns:
            None.
        """
        imgui.text_colored(T.GOLD, "SmartBrew AI")
        imgui.same_line()
        imgui.text_colored(T.MUTED, "|  smart coffee machine")
        imgui.same_line(0, 30)
        u = self.m.user
        T.chip(f"Hello, {u.name}" if u else "Guest", T.GREEN if u else T.MUTED)
        T.chip("ONLINE" if self.m.online else "OFFLINE - basic mode",
               T.GREEN if self.m.online else T.AMBER)
        halts = self.m.halt_reasons()
        T.chip("OUT OF SERVICE" if halts else "READY", T.RED if halts else T.GREEN)
        if events.active_errors(self.m.conn):
            T.chip(f"{len(events.active_errors(self.m.conn))} FAULT(S)", T.RED)
        if self.m.admin_unlocked:
            T.chip("ADMIN MODE", T.PURPLE)
        if u:
            if T.colored_button("Log out", T.GREY):
                self.m.logout()
                self.edit_recipe_id = None
                self.dirty()
                self.toast("Logged out.", T.MUTED)
            imgui.same_line()
        imgui.new_line()
        if time.monotonic() < self.toast_until:
            imgui.text_colored(self.toast_color, self.toast_text)
        else:
            imgui.text_colored(T.MUTED, "Tap a drink to start. Recommended drinks carry a gold star.")

    # ================================================================== MENU
    def draw_menu_tab(self) -> None:
        """Three-column menu: categories+mood | drink grid | detail/checkout.

        Returns:
            None.
        """
        avail = imgui.get_content_region_avail()
        left_w, right_w = 260.0, 430.0
        mid_w = max(220.0, avail.x - left_w - right_w - 20)
        imgui.begin_child("left", ImVec2(left_w, 0), T.child_border())
        self.draw_category_and_mood()
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("grid", ImVec2(mid_w, 0), T.child_border())
        self.draw_drink_grid()
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("detail", ImVec2(0, 0), T.child_border())
        self.draw_detail_panel()
        imgui.end_child()

    def draw_category_and_mood(self) -> None:
        """Category buttons, camera mood scan and the recommendation context.

        Returns:
            None.
        """
        T.section("Categories")
        for cat in catalog.CATEGORIES:
            color = T.CATEGORY_COLORS[cat]
            label = f"> {cat}" if cat == self.category else cat
            if T.colored_button(f"{label}##cat", color if cat == self.category else T.shade(color, 0.6),
                                ImVec2(-1, 34)):
                self.category = cat
                self.dirty()

        T.section("Mood scan (camera)")
        imgui.text_wrapped("Simulated camera: choose the face the customer shows.")
        imgui.set_next_item_width(-1)
        _, self.mood_face = imgui.combo("##face", self.mood_face, MOODS)
        if T.colored_button("Scan my mood", T.PURPLE, ImVec2(-1, 36)):
            res = self.m.scan_mood(MOODS[self.mood_face])
            self.dirty()
            if self.selected:
                self.custom = self.m.default_custom(self.selected)
            self.toast(f"Mood: {res.mood} ({res.confidence:.0%}). {res.suggestion}",
                       T.MOOD_COLORS[res.mood], 6)
        mood = self.m.last_mood
        if mood:
            imgui.text("Detected:")
            imgui.same_line()
            imgui.text_colored(T.MOOD_COLORS[mood.mood], f"{mood.mood}  {mood.confidence:.0%}")
            imgui.text_wrapped(mood.suggestion)
            if imgui.button("Clear mood", ImVec2(-1, 0)):
                self.m.clear_mood()
                self.dirty()
        det = self.m.detector
        imgui.text_colored(T.GREEN, "Privacy: in-memory only")
        imgui.text_colored(T.MUTED, f"Frames analysed: {det.frames_processed}")
        imgui.text_colored(T.MUTED, f"Images stored/sent: {det.frames_stored}")
        if det.frames_processed:
            imgui.text_colored(T.MUTED, "Last frame wiped: " + ("yes" if det.last_buffer_cleared else "NO"))

        T.section("Why this order?")
        hour = self.m.current_hour()
        imgui.text(f"Time: {hour:02d}:00")
        w = self.m.weather_or_none()
        if w:
            imgui.text(f"Weather: {w.condition}, {w.temperature_c:.0f} C")
        else:
            imgui.text_colored(T.AMBER, "Weather API offline")
            imgui.text_wrapped("Ranking uses time of day and history only.")
        imgui.text("History: " + ("your orders" if self.m.user else "log in to personalise"))

    def draw_drink_grid(self) -> None:
        """Grid of drink cards, ordered by recommendation score (F2/F4/F8).

        Returns:
            None.
        """
        T.section(f"{self.category} drinks - best match first")
        items = self.menu_items()
        if self.m.halt_reasons():
            imgui.text_colored(T.RED, "Out of service: " + "; ".join(self.m.halt_reasons()))
            imgui.text_wrapped("A technician must empty the bin before drinks can be ordered.")
        if not self.m.online:
            imgui.text_colored(T.AMBER, "Offline: basic ordering. Wallets unavailable, cards stored offline.")
        avail_w = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        cols = max(1, int((avail_w + spacing) // (CARD_W + spacing)))
        for idx, item in enumerate(items):
            d = item.drink
            price = catalog.compute_price(d, item.default_custom)
            kcal = catalog.compute_nutrition(d, item.default_custom).calories
            if not item.available:
                tag = "UNAVAILABLE"
            elif item.rec.highlighted:
                tag = "* TOP PICK *"
            else:
                tag = d.category
            label = f"{d.name}\n{price:.0f} {CURRENCY}  |  {kcal} kcal\n{tag}##card{d.id}"
            color = T.CATEGORY_COLORS.get(d.category, T.COFFEE)
            if item.rec.highlighted:
                color = T.shade(color, 1.35)
            if not item.available:
                color = T.GREY
            imgui.begin_disabled(not item.available)
            if T.colored_button(label, color, ImVec2(CARD_W, CARD_H)):
                self.select_drink(d)
            imgui.end_disabled()
            if not item.available:
                if imgui.is_item_hovered(int(T.enum_member(imgui.HoveredFlags_, "allow_when_disabled"))):
                    imgui.set_tooltip("Unavailable: " + ", ".join(item.blockers))
            else:
                reasons = ", ".join(item.rec.reasons) or "No special match"
                T.tooltip(f"Score {item.rec.score:.0f}: {reasons}")
            if (idx + 1) % cols != 0 and idx + 1 < len(items):
                imgui.same_line()
        if any(not i.available for i in items):
            imgui.spacing()
            imgui.text_colored(T.MUTED, "Greyed-out drinks have a depleted ingredient or a fault. Hover for details.")

    # ------------------------------------------------------------ detail panel
    def draw_detail_panel(self) -> None:
        """Right column: customise -> pay -> done for the selected drink.

        Returns:
            None.
        """
        if self.selected is None:
            T.section("Your drink")
            imgui.text_wrapped("Select a drink from the menu to see nutrition, customise it and pay.")
            if self.m.user and self.m.my_recipes():
                T.section("Your saved recipes")
                for r in self.m.my_recipes():
                    d = catalog.get_drink(self.m.conn, r.drink_id)
                    if T.colored_button(f"{r.name}  ({d.name})##qr{r.id}", T.CARAMEL, ImVec2(-1, 34)):
                        self.select_drink(d, r.custom)
            return
        if self.stage == "customize":
            self.draw_customize()
        elif self.stage == "pay":
            self.draw_payment()
        else:
            self.draw_done()

    def draw_custom_widgets(self, drink: Drink, custom: Customization, uid: str) -> Customization:
        """Customisation controls; returns the edited customisation (F3).

        Args:
            drink: drink being customised.
            custom: current values.
            uid: unique id suffix so the widgets can appear in several places.

        Returns:
            Customization: new values (normalised for the drink).
        """
        c = custom
        if drink.has_milk:
            milks = inventory.available_milks(self.m.conn, drink) or [c.milk]
            if c.milk not in milks:
                milks = milks + [c.milk]
            idx = milks.index(c.milk)
            changed, idx = imgui.combo(f"Milk##{uid}", idx, milks)
            if changed:
                c = replace(c, milk=milks[idx])
            low = [m for m in catalog.MILK_OPTIONS[1:] if m not in milks]
            if low:
                imgui.text_colored(T.AMBER, "Out of stock: " + ", ".join(low))
        if drink.has_coffee:
            _, strength = imgui.slider_int(f"Strength##{uid}", c.strength, 1, 5,
                                           catalog.STRENGTH_LABELS.get(c.strength, "%d"))
            c = replace(c, strength=strength)
        if drink.is_cold:
            imgui.text(f"Temperature: {catalog.COLD_TEMPERATURE}")
        else:
            t_idx = catalog.TEMPERATURES.index(c.temperature) if c.temperature in catalog.TEMPERATURES else 1
            changed, t_idx = imgui.combo(f"Temperature##{uid}", t_idx, catalog.TEMPERATURES)
            if changed:
                c = replace(c, temperature=catalog.TEMPERATURES[t_idx])
        s_idx = catalog.SYRUPS.index(c.syrup) if c.syrup in catalog.SYRUPS else 0
        changed, s_idx = imgui.combo(f"Syrup##{uid}", s_idx, catalog.SYRUPS)
        if changed:
            c = replace(c, syrup=catalog.SYRUPS[s_idx])
        _, shots = imgui.slider_int(f"Syrup shots##{uid}", c.syrup_shots, 0, 4)
        c = replace(c, syrup_shots=shots)
        if drink.has_coffee:
            _, extra = imgui.checkbox(f"Extra espresso shot (+{catalog.EXTRA_SHOT_PRICE:.0f} {CURRENCY})##{uid}",
                                      c.extra_shot)
            c = replace(c, extra_shot=extra)
        return catalog.normalize(drink, c)

    def draw_nutrition(self, drink: Drink, custom: Customization) -> None:
        """Nutrition facts table for the customised drink (F2).

        Args:
            drink: drink.
            custom: customisation.

        Returns:
            None.
        """
        n = catalog.compute_nutrition(drink, custom)
        tflags = T.flags(imgui.TableFlags_.borders, imgui.TableFlags_.row_bg)
        if imgui.begin_table("nutrition", 4, tflags):
            for head in ("Calories", "Sugar", "Fat", "Caffeine"):
                imgui.table_setup_column(head)
            imgui.table_headers_row()
            imgui.table_next_row()
            for val in (f"{n.calories} kcal", f"{n.sugar_g} g", f"{n.fat_g} g", f"{n.caffeine_mg} mg"):
                imgui.table_next_column()
                imgui.text(val)
            imgui.end_table()

    def draw_customize(self) -> None:
        """Drink details, nutrition, customisation, live price, save recipe, order.

        Returns:
            None.
        """
        d = self.selected
        T.section(d.name)
        imgui.text_colored(T.CATEGORY_COLORS.get(d.category, T.CREAM), d.category)
        imgui.text_wrapped(d.description)
        item = next((i for i in self.menu_items() if i.drink.id == d.id), None)
        if item and item.rec.reasons:
            imgui.text_colored(T.GOLD, "Recommended because: " + ", ".join(item.rec.reasons))
        T.section("Customise")
        self.custom = self.draw_custom_widgets(d, self.custom, "main")
        T.section("Nutrition (live)")
        self.draw_nutrition(d, self.custom)
        price = catalog.compute_price(d, self.custom)
        imgui.spacing()
        imgui.text_colored(T.GOLD, f"Price: {price:.2f} {CURRENCY}")
        imgui.text_colored(T.MUTED, catalog.describe(self.custom))
        blockers = self.m.blockers(d, self.custom)
        for b in blockers:
            imgui.text_colored(T.RED, "Blocked: " + b)
        imgui.begin_disabled(bool(blockers))
        if T.colored_button(f"Order & pay {price:.0f} {CURRENCY}", T.GREEN, ImVec2(-1, 44)):
            self.stage = "pay"
            if self.m.user and self.m.user.card_id and not self.prepaid_id:
                self.prepaid_id = self.m.user.card_id
        imgui.end_disabled()
        if self.m.user:
            T.section("Save as recipe")
            imgui.set_next_item_width(-110)
            _, self.recipe_name = imgui.input_text_with_hint("##rname", "e.g. Morning boost",
                                                             self.recipe_name)
            imgui.same_line()
            if T.colored_button("Save##recipe", T.CARAMEL, ImVec2(-1, 0)):
                try:
                    r = self.m.save_recipe(self.recipe_name, d, self.custom)
                    self.toast(f"Saved recipe '{r.name}'. Find it under My account.")
                    self.recipe_name = ""
                except (RecipeError, AccountError) as exc:
                    self.toast(str(exc), T.RED)
        else:
            imgui.text_colored(T.MUTED, "Log in to save this as a one-touch recipe.")
        if imgui.button("Close", ImVec2(-1, 0)):
            self.selected = None

    def draw_payment(self) -> None:
        """Payment method selection and the simulated card/wallet reader (F5).

        Returns:
            None.
        """
        d = self.selected
        price = catalog.compute_price(d, self.custom)
        T.section("Checkout")
        imgui.text(f"{d.name}: {catalog.describe(self.custom)}")
        imgui.text_colored(T.GOLD, f"Total: {price:.2f} {CURRENCY}")
        if not self.m.online:
            imgui.text_colored(T.AMBER, "Offline: cards up to 100 SEK are stored and settled later.")
        T.section("Payment method")
        method_colors = [T.BLUE, T.GREY, T.GREEN, T.CARAMEL]
        for i, method in enumerate(payments.METHODS):
            color = method_colors[i] if i == self.pay_method else T.shade(method_colors[i], 0.5)
            if T.colored_button(f"{method}##pm", color, ImVec2(92, 40)):
                self.pay_method = i
            if i < len(payments.METHODS) - 1:
                imgui.same_line()
        method = payments.METHODS[self.pay_method]
        imgui.spacing()
        if method == payments.CARD:
            imgui.text("Tap or insert card (simulated reader):")
            imgui.set_next_item_width(-1)
            _, self.card_number = imgui.input_text("##card", self.card_number)
            imgui.text_colored(T.MUTED, "Test cards:")
            for number, desc in payments.TEST_CARDS.items():
                if imgui.small_button(f"{desc}##{number}"):
                    self.card_number = number
        elif method in (payments.APPLE_PAY, payments.GOOGLE_PAY):
            imgui.text_wrapped(f"Hold your phone near the reader to pay with {method}.")
            _, self.wallet_ok = imgui.checkbox("Customer approves on phone", self.wallet_ok)
        else:
            imgui.text("Tap your prepaid employee card:")
            imgui.set_next_item_width(-1)
            _, self.prepaid_id = imgui.input_text_with_hint("##prepaid", "card id, e.g. NFC-EMP-1001",
                                                            self.prepaid_id)
            if self.m.user:
                imgui.text_colored(T.MUTED, f"Your balance: {self.m.user.prepaid_balance:.2f} {CURRENCY}")
        imgui.spacing()
        if T.colored_button(f"Pay {price:.2f} {CURRENCY}", T.GREEN, ImVec2(-1, 46)):
            self.result = self.m.order(d, self.custom, method, card_number=self.card_number,
                                       card_id=self.prepaid_id, token_ok=self.wallet_ok)
            self.stage = "done"
            self.dirty()
            self.toast(self.result.message, T.GREEN if self.result.success else T.RED, 6)
        if imgui.button("Back", ImVec2(-1, 0)):
            self.stage = "customize"

    def draw_done(self) -> None:
        """Order result: success + receipt summary, or the decline reason.

        Returns:
            None.
        """
        res = self.result
        if res is None:
            self.stage = "customize"
            return
        if res.success:
            T.section("Dispensing complete")
            imgui.text_colored(T.GREEN, res.message)
            tx = res.transaction
            T.section("Transaction recorded")
            for k, v in (("Transaction", f"#{tx.id}"), ("Time", tx.timestamp),
                         ("Drink", tx.drink_name), ("Options", catalog.describe(tx.custom)),
                         ("Paid", f"{tx.price:.2f} {CURRENCY} by {tx.payment_method}"),
                         ("Reference", tx.payment_ref),
                         ("Status", "Stored offline" if tx.offline else "Settled")):
                imgui.text_colored(T.MUTED, f"{k}:")
                imgui.same_line(110)
                imgui.text(v)
            if T.colored_button("Order another drink", T.COFFEE, ImVec2(-1, 40)):
                self.selected = None
                self.stage = "customize"
        else:
            T.section("Payment not completed")
            imgui.text_colored(T.RED, res.message)
            if T.colored_button("Try another method", T.AMBER, ImVec2(-1, 40)):
                self.stage = "pay"
            if imgui.button("Cancel", ImVec2(-1, 0)):
                self.selected = None
                self.stage = "customize"

    # ============================================================== ACCOUNT
    def draw_account_tab(self) -> None:
        """Login/register when logged out, profile and recipes when logged in.

        Returns:
            None.
        """
        if self.m.user is None:
            self.draw_login_forms()
        else:
            self.draw_profile()

    def draw_login_forms(self) -> None:
        """Credential login, NFC/card tap login and account creation (F1).

        Returns:
            None.
        """
        half = imgui.get_content_region_avail().x / 2 - 8
        imgui.begin_child("login", ImVec2(half, 0), T.child_border())
        T.section("Log in")
        _, self.login_email = imgui.input_text("E-mail##login", self.login_email)
        _, self.login_pw = imgui.input_text("Password##login", self.login_pw,
                                            int(imgui.InputTextFlags_.password))
        if T.colored_button("Log in", T.GREEN, ImVec2(-1, 40)):
            try:
                u = self.m.login(self.login_email, self.login_pw)
                self.after_login(f"Welcome back, {u.name}!")
            except AccountError as exc:
                self.form_error = str(exc)
        imgui.text_colored(T.MUTED, "Demo: demo@smartbrew.local / demo1234")
        T.section("Or tap your NFC / employee card")
        _, self.tap_id = imgui.input_text("Card ID##tap", self.tap_id)
        if T.colored_button("Tap card on reader", T.BLUE, ImVec2(-1, 40)):
            try:
                u = self.m.login_card(self.tap_id)
                self.after_login(f"Card recognised - hello {u.name}!")
            except AccountError as exc:
                self.form_error = str(exc)
        if self.form_error:
            imgui.text_colored(T.RED, self.form_error)
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("register", ImVec2(0, 0), T.child_border())
        T.section("Create an account")
        _, self.reg_name = imgui.input_text("Name##reg", self.reg_name)
        _, self.reg_email = imgui.input_text("E-mail##reg", self.reg_email)
        _, self.reg_pw = imgui.input_text("Password##reg", self.reg_pw,
                                          int(imgui.InputTextFlags_.password))
        _, self.reg_card = imgui.input_text_with_hint("NFC card (optional)##reg",
                                                      "e.g. NFC-EMP-2002", self.reg_card)
        if T.colored_button("Create account", T.CARAMEL, ImVec2(-1, 40)):
            try:
                u = self.m.create_account(self.reg_name, self.reg_email, self.reg_pw,
                                          self.reg_card or None)
                self.reg_name = self.reg_email = self.reg_pw = self.reg_card = ""
                self.after_login(f"Account created. Welcome, {u.name}!")
            except AccountError as exc:
                self.form_error = str(exc)
        imgui.text_wrapped("Your preferences and order history are kept in your profile and "
                           "used for recommendations. Passwords are stored only as salted hashes.")
        imgui.end_child()

    def after_login(self, message: str) -> None:
        """Common steps after a successful login or registration.

        Args:
            message: toast text.

        Returns:
            None.
        """
        self.form_error = ""
        self.login_pw = ""
        self.prepaid_id = self.m.user.card_id or ""
        self.dirty()
        if self.selected:
            self.custom = self.m.default_custom(self.selected)
        self.toast(message)

    def draw_profile(self) -> None:
        """Profile, preferences, card linking and the saved-recipe manager (F1/F7).

        Returns:
            None.
        """
        u = self.m.user
        imgui.begin_child("profile", ImVec2(380, 0), T.child_border())
        T.section("Profile")
        imgui.text(f"Name:  {u.name}")
        imgui.text(f"E-mail: {u.email}")
        imgui.text(f"Card:  {u.card_id or '- none linked -'}")
        imgui.text_colored(T.GOLD, f"Prepaid balance: {u.prepaid_balance:.2f} {CURRENCY}")
        T.section("Preferences")
        milks = catalog.MILK_OPTIONS[1:]
        m_idx = milks.index(u.default_milk) if u.default_milk in milks else 0
        changed_m, m_idx = imgui.combo("Default milk", m_idx, milks)
        changed_s, strength = imgui.slider_int("Default strength", u.default_strength, 1, 5,
                                               catalog.STRENGTH_LABELS.get(u.default_strength, "%d"))
        if changed_m or changed_s:
            self.m.update_preferences(milks[m_idx], strength)
            self.dirty()
        T.section("Link NFC / employee card")
        _, self.link_card_id = imgui.input_text("Card ID##link", self.link_card_id)
        if imgui.button("Link card", ImVec2(-1, 0)):
            try:
                self.m.link_card(self.link_card_id)
                self.toast("Card linked.")
            except AccountError as exc:
                self.toast(str(exc), T.RED)
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("recipes", ImVec2(0, 0), T.child_border())
        T.section("My recipes - one-touch ordering")
        recs = self.m.my_recipes()
        if not recs:
            imgui.text_wrapped("No recipes yet. Customise a drink on the Menu tab and press 'Save'.")
        tflags = T.flags(imgui.TableFlags_.borders, imgui.TableFlags_.row_bg)
        if recs and imgui.begin_table("recipes_tbl", 5, tflags):
            for head in ("Name", "Drink", "Options", "Price", "Actions"):
                imgui.table_setup_column(head)
            imgui.table_headers_row()
            for r in recs:
                d = catalog.get_drink(self.m.conn, r.drink_id)
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text_colored(T.GOLD, r.name)
                imgui.table_next_column()
                imgui.text(d.name)
                imgui.table_next_column()
                imgui.text(catalog.describe(r.custom))
                imgui.table_next_column()
                imgui.text(f"{catalog.compute_price(d, r.custom):.0f} {CURRENCY}")
                imgui.table_next_column()
                self.draw_recipe_actions(r, d)
            imgui.end_table()
        if self.edit_recipe_id is not None:
            self.draw_recipe_editor()
        imgui.end_child()

    def draw_recipe_actions(self, r, d: Drink) -> None:
        """Buttons for one recipe row: one-touch order, open, edit, delete.

        Args:
            r: the :class:`~smartbrew.recipes.Recipe`.
            d: its base drink.

        Returns:
            None.
        """
        u = self.m.user
        if u.card_id:
            if T.colored_button(f"1-Touch##{r.id}", T.GREEN):
                res = self.m.order_recipe(r.id, payments.PREPAID, card_id=u.card_id)
                self.dirty()
                self.toast(res.message, T.GREEN if res.success else T.RED, 6)
            T.tooltip("Order now and pay with your linked prepaid card")
            imgui.same_line()
        if imgui.small_button(f"Open##{r.id}"):
            self.select_drink(d, r.custom)
            self.jump_tab = "Menu"
        imgui.same_line()
        if imgui.small_button(f"Edit##{r.id}"):
            self.edit_recipe_id, self.edit_name, self.edit_custom = r.id, r.name, r.custom
        imgui.same_line()
        if T.colored_button(f"Delete##{r.id}", T.RED):
            self.m.delete_recipe(r.id)
            if self.edit_recipe_id == r.id:
                self.edit_recipe_id = None
            self.toast(f"Deleted '{r.name}'.", T.MUTED)

    def draw_recipe_editor(self) -> None:
        """Form to rename and modify the recipe being edited (F7).

        Returns:
            None.
        """
        from ..recipes import get_recipe

        try:
            r = get_recipe(self.m.conn, self.edit_recipe_id)
        except RecipeError:
            self.edit_recipe_id = None
            return
        d = catalog.get_drink(self.m.conn, r.drink_id)
        T.section(f"Edit recipe ({d.name})")
        _, self.edit_name = imgui.input_text("Name##edit", self.edit_name)
        self.edit_custom = self.draw_custom_widgets(d, self.edit_custom, "edit")
        imgui.text_colored(T.GOLD, f"Price: {catalog.compute_price(d, self.edit_custom):.2f} {CURRENCY}")
        if T.colored_button("Save changes", T.GREEN):
            try:
                self.m.update_recipe(r.id, self.edit_name, self.edit_custom)
                self.edit_recipe_id = None
                self.toast("Recipe updated.")
            except RecipeError as exc:
                self.toast(str(exc), T.RED)
        imgui.same_line()
        if imgui.button("Cancel##edit"):
            self.edit_recipe_id = None

    # ============================================================== HISTORY
    def draw_history_tab(self) -> None:
        """Table of recorded transactions with all customisation parameters (F6).

        Returns:
            None.
        """
        if self.m.admin_unlocked:
            _, self.history_all = imgui.checkbox("Show all machine transactions (admin)", self.history_all)
        else:
            self.history_all = False
        if not self.history_all and self.m.user is None:
            imgui.text_wrapped("Log in to see your personal history. Anonymous purchases are still "
                               "recorded and visible to technicians in admin mode.")
            return
        txs = self.m.history(all_users=self.history_all)
        T.section(f"{len(txs)} transaction(s)")
        tflags = T.flags(imgui.TableFlags_.borders, imgui.TableFlags_.row_bg,
                         imgui.TableFlags_.resizable)
        if imgui.begin_table("history", 9, tflags):
            for head in ("#", "Time", "User", "Drink", "Milk", "Strength / temp",
                         "Syrup", "Paid", "Payment"):
                imgui.table_setup_column(head)
            imgui.table_headers_row()
            for tx in txs:
                c = tx.custom
                cells = [str(tx.id), tx.timestamp.replace("T", " "),
                         str(tx.user_id) if tx.user_id else "guest", tx.drink_name, c.milk,
                         f"{catalog.STRENGTH_LABELS.get(c.strength)} / {c.temperature}"
                         + (" +shot" if c.extra_shot else ""),
                         f"{c.syrup_shots}x {c.syrup}" if c.syrup_shots else "-",
                         f"{tx.price:.2f}", tx.payment_method]
                imgui.table_next_row()
                for i, cell in enumerate(cells):
                    imgui.table_next_column()
                    if i == 8 and tx.offline:
                        imgui.text_colored(T.AMBER if not tx.synced else T.GREEN,
                                           f"{cell} ({'offline' if not tx.synced else 'synced'})")
                    else:
                        imgui.text(cell)
            imgui.end_table()

    # ================================================================ ADMIN
    def draw_admin_tab(self) -> None:
        """Technician login, or the admin dashboard when unlocked (F10).

        Returns:
            None.
        """
        if not self.m.admin_unlocked:
            self.draw_admin_login()
        else:
            self.draw_admin_dashboard()

    def draw_admin_login(self) -> None:
        """Three ways into admin mode: PIN keypad, NFC master card, physical key.

        Returns:
            None.
        """
        imgui.begin_child("adminlogin", ImVec2(420, 0), T.child_border())
        T.section("Technician access")
        lock = self.m.gate.lock_remaining()
        if lock:
            imgui.text_colored(T.RED, f"Locked after failed attempts. Wait {lock} s.")
        imgui.text("Technician PIN:")
        imgui.set_next_item_width(-1)
        _, self.admin_pin = imgui.input_text("##pin", self.admin_pin,
                                             int(imgui.InputTextFlags_.password))
        for row in ("123", "456", "789", "C0<"):
            for i, key in enumerate(row):
                if imgui.button(f"{key}##key{key}", ImVec2(60, 44)):
                    if key == "C":
                        self.admin_pin = ""
                    elif key == "<":
                        self.admin_pin = self.admin_pin[:-1]
                    else:
                        self.admin_pin += key
                if i < 2:
                    imgui.same_line()
        if T.colored_button("Enter PIN", T.PURPLE, ImVec2(-1, 40)):
            ok, self.admin_msg = self.m.admin_login("PIN", self.admin_pin)
            self.admin_pin = ""
        T.section("NFC master card")
        imgui.set_next_item_width(-1)
        _, self.admin_card = imgui.input_text_with_hint("##mcard", "master card id", self.admin_card)
        if imgui.button("Tap card", ImVec2(-1, 0)):
            ok, self.admin_msg = self.m.admin_login("NFC", self.admin_card)
        if imgui.small_button("Use demo master card"):
            self.admin_card = DEMO_MASTER_CARD
        T.section("Physical service key")
        if T.colored_button("Turn service key", T.GREY, ImVec2(-1, 36)):
            ok, self.admin_msg = self.m.admin_login("Key", PHYSICAL_KEY_ID)
        if self.admin_msg:
            imgui.text_colored(T.GREEN if self.m.admin_unlocked else T.RED, self.admin_msg)
        imgui.text_colored(T.MUTED, "Demo PIN: 1234")
        imgui.end_child()

    def draw_admin_dashboard(self) -> None:
        """Faults, ingredient levels with refills, bins and the event log.

        Returns:
            None.
        """
        conn = self.m.conn
        imgui.begin_child("dash_left", ImVec2(520, 0), T.child_border())
        if T.colored_button("Exit admin mode", T.GREY):
            self.m.admin_logout()
            self.admin_msg = ""
            return_after = True
        else:
            return_after = False
        T.section("Active faults")
        errs = events.active_errors(conn)
        if not errs:
            imgui.text_colored(T.GREEN, "No active faults.")
        for e in errs:
            imgui.text_colored(T.RED, f"{e.timestamp[11:]}  {e.message}")
            imgui.same_line()
            if imgui.small_button(f"Resolve##{e.id}"):
                self.m.resolve_fault(e.id)
                self.dirty()
        T.section("Ingredients")
        for ing in inventory.get_ingredients(conn).values():
            imgui.text(f"{ing.name:<13}")
            imgui.same_line(130)
            T.level_bar(ing.ratio, f"{ing.level:.0f}/{ing.capacity:.0f} {ing.unit}",
                        warn=ing.ratio < 0.35, danger=ing.below_threshold, width=250)
            imgui.same_line()
            if imgui.small_button(f"Refill##{ing.name}"):
                self.m.refill(ing.name)
                self.dirty()
        if T.colored_button("Refill all", T.GREEN, ImVec2(-1, 0)):
            self.m.refill_all()
            self.dirty()
        T.section("Waste bins")
        for b in inventory.get_bins(conn).values():
            imgui.text(b.name)
            imgui.same_line(130)
            T.level_bar(b.ratio, f"{b.ratio:.0%}", warn=b.needs_emptying, danger=b.full, width=250)
            imgui.same_line()
            if imgui.small_button(f"Empty##{b.name}"):
                self.m.empty_bin(b.name)
                self.dirty()
            if b.full:
                imgui.text_colored(T.RED, "  Overflow - ordering halted")
            elif b.needs_emptying:
                imgui.text_colored(T.AMBER, "  Please empty soon")
        imgui.end_child()
        if return_after:
            return
        imgui.same_line()
        imgui.begin_child("dash_log", ImVec2(0, 0), T.child_border())
        T.section("Event log (remote diagnostics)")
        levels = ["All", events.INFO, events.WARNING, events.ERROR]
        imgui.set_next_item_width(160)
        _, self.log_filter = imgui.combo("Level", self.log_filter, levels)
        entries = events.recent(conn, 300, None if self.log_filter == 0 else levels[self.log_filter])
        tflags = T.flags(imgui.TableFlags_.borders, imgui.TableFlags_.row_bg,
                         imgui.TableFlags_.resizable)
        if imgui.begin_table("log", 4, tflags):
            for head in ("Time", "Level", "Source", "Message"):
                imgui.table_setup_column(head)
            imgui.table_headers_row()
            for e in entries:
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text(e.timestamp.replace("T", " "))
                imgui.table_next_column()
                imgui.text_colored(T.LEVEL_COLORS.get(e.level, T.CREAM), e.level)
                imgui.table_next_column()
                imgui.text(e.source)
                imgui.table_next_column()
                imgui.text(e.message + ("  (active)" if e.active else ""))
            imgui.end_table()
        imgui.end_child()

    # ============================================================ SIMULATOR
    def draw_simulator_tab(self) -> None:
        """Demo controls that stand in for real hardware and external services.

        Returns:
            None.
        """
        imgui.begin_child("sim_env", ImVec2(440, 0), T.child_border())
        T.section("Clock")
        changed, self.sim_clock = imgui.checkbox("Override time of day", self.sim_clock)
        imgui.begin_disabled(not self.sim_clock)
        changed2, self.sim_hour = imgui.slider_int("Hour", self.sim_hour, 0, 23, "%02d:00")
        imgui.end_disabled()
        if changed or changed2:
            self.m.hour_override = self.sim_hour if self.sim_clock else None
            self.dirty()
        T.section("Weather API (simulated)")
        w = self.m.weather.current
        c1, temp = imgui.slider_float("Temperature C", w.temperature_c, -15.0, 35.0, "%.0f")
        cond_idx = CONDITIONS.index(w.condition)
        c2, cond_idx = imgui.combo("Condition", cond_idx, CONDITIONS)
        if c1 or c2:
            self.m.weather.set(temp, CONDITIONS[cond_idx])
            self.dirty()
        T.section("Network")
        changed, online = imgui.checkbox("Network / external services online", self.m.online)
        if changed:
            uploaded = self.m.set_online(online)
            self.dirty()
            if online:
                self.toast(f"Network restored. Uploaded {uploaded} offline payment(s).")
            else:
                self.toast("Network lost: basic ordering and offline card payments.", T.AMBER)
        T.section("Hardware faults")
        for fault in events.FAULTS:
            active = events.has_active(self.m.conn, fault)
            if T.colored_button(f"{'ACTIVE: ' if active else 'Trigger: '}{fault}##f",
                                T.RED if active else T.shade(T.RED, 0.6), ImVec2(-1, 32)):
                self.m.inject_fault(fault)
                self.dirty()
        imgui.text_colored(T.MUTED, "Resolve faults in the Admin tab.")
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("sim_sensors", ImVec2(0, 0), T.child_border())
        T.section("Ingredient sensors")
        for ing in inventory.get_ingredients(self.m.conn).values():
            changed, level = imgui.slider_float(f"{ing.name} ({ing.unit})", ing.level, 0.0,
                                                ing.capacity, "%.0f")
            if changed:
                inventory.set_level(self.m.conn, ing.name, level)
                self.dirty()
        if imgui.button("Drain all milks below threshold"):
            for milk in catalog.MILK_OPTIONS[1:]:
                inventory.set_level(self.m.conn, milk, 100)
            self.dirty()
        T.section("Bin sensors")
        for b in inventory.get_bins(self.m.conn).values():
            changed, level = imgui.slider_float(f"{b.name} ({b.unit})", b.level, 0.0,
                                                b.capacity, "%.0f")
            if changed:
                inventory.set_bin_level(self.m.conn, b.name, level)
                self.dirty()
        imgui.end_child()


def run(db_path: str = "smartbrew.db") -> None:
    """Open the SmartBrew AI window and run until it is closed.

    Args:
        db_path: SQLite database file to use (created and seeded if missing).

    Returns:
        None.
    """
    import faulthandler
    import traceback

    import imgui_bundle
    from imgui_bundle import immapp

    log = open(ERROR_LOG, "a", encoding="utf-8")
    log.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} | imgui-bundle "
              f"{getattr(imgui_bundle, '__version__', '?')} ===\n")
    log.flush()
    faulthandler.enable(file=log)          # also catches hard crashes in C++ code
    machine = SmartBrewMachine(db_path)
    app = SmartBrewApp(machine)

    def safe_gui() -> None:
        """Draw a frame; write any exception with its traceback to the error log.

        Returns:
            None. Re-raises the exception after logging it.
        """
        try:
            app.gui()
        except Exception:
            log.write(traceback.format_exc())
            log.flush()
            raise

    from imgui_bundle import hello_imgui

    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = "SmartBrew AI"
    params.app_window_params.window_geometry.size = (1480, 900)
    # Our gui() draws its own full-screen window, so switch off HelloImGui's default one
    # (otherwise it covers our window and only its empty background is visible).
    params.imgui_window_params.default_imgui_window_type = \
        hello_imgui.DefaultImGuiWindowType.no_default_window
    params.callbacks.show_gui = safe_gui
    params.fps_idling.enable_idling = False
    try:
        immapp.run(params)
    except Exception:
        log.write(traceback.format_exc())
        raise
    finally:
        machine.close()
        log.close()
