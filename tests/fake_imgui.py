"""A minimal stand-in for ``imgui_bundle`` used by the headless UI smoke test.

It records every widget label and lets a test "click" buttons by label, so the
real GUI code in ``smartbrew/ui`` runs frame by frame without a window or GPU.
"""

from __future__ import annotations

import sys
import types


class ImVec2:
    """2-D vector compatible with imgui.ImVec2."""

    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        """Store the components.

        Args:
            x: x component.
            y: y component.

        Returns:
            None.
        """
        self.x, self.y = x, y


class ImVec4:
    """RGBA colour compatible with imgui.ImVec4."""

    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0) -> None:
        """Store the components.

        Args:
            x: red.
            y: green.
            z: blue.
            w: alpha.

        Returns:
            None.
        """
        self.x, self.y, self.z, self.w = x, y, z, w


class _Enum:
    """Any attribute is a distinct power-of-two flag value."""

    def __init__(self) -> None:
        """Create the enum namespace.

        Returns:
            None.
        """
        self._values: dict[str, int] = {}

    def __getattr__(self, name: str) -> int:
        """Return a stable flag value for any member name.

        Args:
            name: member name.

        Returns:
            int: flag value.
        """
        if name.startswith("__"):
            raise AttributeError(name)
        return self._values.setdefault(name, 1 << len(self._values))


class FakeImgui(types.ModuleType):
    """Fake ``imgui`` module: widgets return defaults, chosen buttons return True."""

    ImVec2, ImVec4 = ImVec2, ImVec4

    def __init__(self) -> None:
        """Initialise recording state.

        Returns:
            None.
        """
        super().__init__("imgui")
        self.clicks: set[str] = set()       # substrings of labels to click this frame
        self.inputs: dict[str, object] = {}  # label substring -> value to return
        self.labels: list[str] = []
        self.texts: list[str] = []
        self.stack = 0
        for enum in ("WindowFlags_", "ChildFlags_", "TableFlags_", "InputTextFlags_",
                     "TabItemFlags_", "HoveredFlags_", "Col_"):
            setattr(self, enum, _Enum())

    def _match(self, label: str, table: dict | set):
        """Find the first key that is a substring of the label.

        Args:
            label: widget label.
            table: click set or input dict.

        Returns:
            The matching key, or None.
        """
        for key in table:
            if key in label:
                return key
        return None

    def _value(self, label: str, current):
        """Return (changed, value) for value widgets, applying a scripted input.

        Args:
            label: widget label.
            current: value passed in by the UI.

        Returns:
            tuple: (changed, new value).
        """
        self.labels.append(label)
        key = self._match(label, self.inputs)
        if key is not None:
            return True, self.inputs.pop(key)
        return False, current

    # windows / layout ------------------------------------------------------
    def begin(self, name, p_open=None, flags=0):
        """Fake imgui.begin.

        Args:
            Same parameters as the real imgui.begin; the label and current value are used, the rest is ignored.

        Returns:
            (expanded, open).
        """
        self.stack += 1
        return True, None

    def end(self):
        """Fake imgui.end.

        Args:
            Same parameters as the real imgui.end; the label and current value are used, the rest is ignored.

        Returns:
            None.
        """
        self.stack -= 1

    def begin_child(self, *a, **k):
        """Fake imgui.begin_child.

        Args:
            Same parameters as the real imgui.begin_child; the label and current value are used, the rest is ignored.

        Returns:
            True.
        """
        self.stack += 1
        return True

    def end_child(self):
        """Fake imgui.end_child.

        Args:
            Same parameters as the real imgui.end_child; the label and current value are used, the rest is ignored.

        Returns:
            None.
        """
        self.stack -= 1

    def begin_tab_bar(self, *a):
        """Fake imgui.begin_tab_bar.

        Args:
            Same parameters as the real imgui.begin_tab_bar; the label and current value are used, the rest is ignored.

        Returns:
            True.
        """
        return True

    def begin_tab_item(self, label, p_open=None, flags=0):
        """Fake imgui.begin_tab_item.

        Args:
            Same parameters as the real imgui.begin_tab_item; the label and current value are used, the rest is ignored.

        Returns:
            (True, None) so every tab is drawn.
        """
        return True, None

    def begin_table(self, *a, **k):
        """Fake imgui.begin_table.

        Args:
            Same parameters as the real imgui.begin_table; the label and current value are used, the rest is ignored.

        Returns:
            True.
        """
        return True

    def table_next_column(self):
        """Fake imgui.table_next_column.

        Args:
            Same parameters as the real imgui.table_next_column; the label and current value are used, the rest is ignored.

        Returns:
            True.
        """
        return True

    def get_content_region_avail(self):
        """Fake imgui.get_content_region_avail.

        Args:
            Same parameters as the real imgui.get_content_region_avail; the label and current value are used, the rest is ignored.

        Returns:
            ImVec2.
        """
        return ImVec2(900, 700)

    def get_main_viewport(self):
        """Fake imgui.get_main_viewport.

        Args:
            Same parameters as the real imgui.get_main_viewport; the label and current value are used, the rest is ignored.

        Returns:
            object with work_pos/work_size.
        """
        return types.SimpleNamespace(work_pos=ImVec2(0, 0), work_size=ImVec2(1480, 900))

    def get_style(self):
        """Fake imgui.get_style.

        Args:
            Same parameters as the real imgui.get_style; the label and current value are used, the rest is ignored.

        Returns:
            namespace with item_spacing and set_color_.
        """
        return types.SimpleNamespace(item_spacing=ImVec2(10, 8), set_color_=lambda *a: None)

    def get_io(self):
        """Fake imgui.get_io.

        Args:
            Same parameters as the real imgui.get_io; the label and current value are used, the rest is ignored.

        Returns:
            namespace.
        """
        return types.SimpleNamespace()

    # widgets ---------------------------------------------------------------
    def button(self, label, size=None):
        """Fake imgui.button.

        Args:
            Same parameters as the real imgui.button; the label and current value are used, the rest is ignored.

        Returns:
            True if a scripted click matches the label.
        """
        self.labels.append(label)
        key = self._match(label, self.clicks)
        if key is not None:
            self.clicks.discard(key)
            return True
        return False

    small_button = button

    def input_text(self, label, value, flags=0):
        """Fake imgui.input_text.

        Args:
            Same parameters as the real imgui.input_text; the label and current value are used, the rest is ignored.

        Returns:
            (changed, value).
        """
        assert isinstance(value, str), label
        return self._value(label, value)

    def input_text_with_hint(self, label, hint, value, flags=0):
        """Fake imgui.input_text_with_hint.

        Args:
            Same parameters as the real imgui.input_text_with_hint; the label and current value are used, the rest is ignored.

        Returns:
            (changed, value).
        """
        assert isinstance(value, str), label
        return self._value(label, value)

    def combo(self, label, current, items, *a):
        """Fake imgui.combo.

        Args:
            Same parameters as the real imgui.combo; the label and current value are used, the rest is ignored.

        Returns:
            (changed, index).
        """
        assert isinstance(current, int) and 0 <= current < len(items), (label, current, items)
        return self._value(label, current)

    def slider_int(self, label, v, lo, hi, *a):
        """Fake imgui.slider_int.

        Args:
            Same parameters as the real imgui.slider_int; the label and current value are used, the rest is ignored.

        Returns:
            (changed, value).
        """
        assert isinstance(v, int) and lo <= v <= hi, (label, v)
        return self._value(label, v)

    def slider_float(self, label, v, lo, hi, *a):
        """Fake imgui.slider_float.

        Args:
            Same parameters as the real imgui.slider_float; the label and current value are used, the rest is ignored.

        Returns:
            (changed, value).
        """
        return self._value(label, float(v))

    def checkbox(self, label, v):
        """Fake imgui.checkbox.

        Args:
            Same parameters as the real imgui.checkbox; the label and current value are used, the rest is ignored.

        Returns:
            (changed, value).
        """
        assert isinstance(v, bool), label
        return self._value(label, v)

    def text(self, s):
        """Fake imgui.text.

        Args:
            Same parameters as the real imgui.text; the label and current value are used, the rest is ignored.

        Returns:
            None.
        """
        self.texts.append(str(s))

    def text_colored(self, col, s):
        """Fake imgui.text_colored.

        Args:
            Same parameters as the real imgui.text_colored; the label and current value are used, the rest is ignored.

        Returns:
            None.
        """
        assert isinstance(col, ImVec4)
        self.texts.append(str(s))

    text_wrapped = text
    text_disabled = text
    separator_text = text

    def is_item_hovered(self, *a):
        """Fake imgui.is_item_hovered.

        Args:
            Same parameters as the real imgui.is_item_hovered; the label and current value are used, the rest is ignored.

        Returns:
            False.
        """
        return False

    def __getattr__(self, name):
        """Any other ImGui function is a no-op.

        Args:
            name: function name.

        Returns:
            callable: function returning None.
        """
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def install() -> FakeImgui:
    """Register the fake as ``imgui_bundle`` in ``sys.modules``.

    Returns:
        FakeImgui: the fake ``imgui`` module, for scripting clicks and inputs.
    """
    fake = FakeImgui()
    bundle = types.ModuleType("imgui_bundle")
    bundle.imgui = fake
    bundle.immapp = types.SimpleNamespace(run=lambda **k: None)
    bundle.hello_imgui = types.SimpleNamespace()
    sys.modules["imgui_bundle"] = bundle
    return fake
