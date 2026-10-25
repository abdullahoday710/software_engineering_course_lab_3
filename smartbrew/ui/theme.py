"""Colours, style and small reusable immediate-mode widgets.

All Dear ImGui calls that differ between imgui-bundle releases (renamed enum
members, style fields) go through the defensive helpers in this module, so the
rest of the UI stays version-independent.
"""

from __future__ import annotations

from imgui_bundle import imgui

ImVec2, ImVec4 = imgui.ImVec2, imgui.ImVec4

# Palette -------------------------------------------------------------------
BG = ImVec4(0.11, 0.09, 0.08, 1.0)
PANEL = ImVec4(0.16, 0.13, 0.11, 1.0)
FRAME = ImVec4(0.24, 0.19, 0.16, 1.0)
CREAM = ImVec4(0.98, 0.92, 0.82, 1.0)
MUTED = ImVec4(0.70, 0.64, 0.58, 1.0)
COFFEE = ImVec4(0.55, 0.33, 0.20, 1.0)
CARAMEL = ImVec4(0.85, 0.55, 0.22, 1.0)
GOLD = ImVec4(1.00, 0.80, 0.25, 1.0)
GREEN = ImVec4(0.25, 0.70, 0.42, 1.0)
RED = ImVec4(0.88, 0.30, 0.30, 1.0)
AMBER = ImVec4(0.96, 0.66, 0.18, 1.0)
BLUE = ImVec4(0.30, 0.56, 0.92, 1.0)
PURPLE = ImVec4(0.62, 0.42, 0.88, 1.0)
PINK = ImVec4(0.90, 0.42, 0.62, 1.0)
GREY = ImVec4(0.33, 0.31, 0.30, 1.0)

CATEGORY_COLORS = {
    "All": PURPLE,
    "Espresso": COFFEE,
    "Milk coffee": CARAMEL,
    "Chocolate": PINK,
    "Iced": BLUE,
}
MOOD_COLORS = {"Tired": BLUE, "Happy": GOLD, "Stressed": RED, "Neutral": MUTED}
LEVEL_COLORS = {"INFO": BLUE, "WARNING": AMBER, "ERROR": RED}


def shade(color: ImVec4, factor: float) -> ImVec4:
    """Lighten (>1) or darken (<1) a colour.

    Args:
        color: base colour.
        factor: multiplier applied to R, G and B.

    Returns:
        ImVec4: new colour, alpha unchanged.
    """
    return ImVec4(min(1.0, color.x * factor), min(1.0, color.y * factor),
                  min(1.0, color.z * factor), color.w)


def enum_member(enum_cls, *names):
    """Return the first existing member of an ImGui enum (handles renames).

    Args:
        enum_cls: e.g. ``imgui.ChildFlags_``.
        *names: candidate member names, newest first.

    Returns:
        The enum member, or 0 if none exist.
    """
    for name in names:
        if hasattr(enum_cls, name):
            return getattr(enum_cls, name)
    return 0


def flags(*values) -> int:
    """Combine ImGui flag values into one integer.

    Args:
        *values: enum members or ints.

    Returns:
        int: bitwise OR of all values.
    """
    out = 0
    for v in values:
        out |= int(v)
    return out


def child_border() -> int:
    """Child-window flag that draws a border (``borders`` in new ImGui, ``border`` in old).

    Returns:
        int: flag value.
    """
    return int(enum_member(imgui.ChildFlags_, "borders", "border"))


def apply_theme() -> None:
    """Apply the warm coffee-house colour theme and rounded style once.

    Returns:
        None.
    """
    imgui.style_colors_dark()
    style = imgui.get_style()
    for attr, value in (("window_rounding", 0.0), ("child_rounding", 12.0),
                        ("frame_rounding", 8.0), ("grab_rounding", 8.0),
                        ("tab_rounding", 8.0), ("popup_rounding", 8.0),
                        ("scrollbar_rounding", 8.0)):
        try:
            setattr(style, attr, value)
        except (AttributeError, TypeError):
            pass
    try:
        style.frame_padding = ImVec2(10, 7)
        style.item_spacing = ImVec2(10, 8)
        style.window_padding = ImVec2(14, 12)
    except (AttributeError, TypeError):
        pass
    col = imgui.Col_
    palette = {
        "window_bg": BG, "child_bg": PANEL, "frame_bg": FRAME,
        "frame_bg_hovered": shade(FRAME, 1.3), "frame_bg_active": shade(FRAME, 1.5),
        "button": COFFEE, "button_hovered": shade(COFFEE, 1.25),
        "button_active": shade(COFFEE, 0.8), "header": COFFEE,
        "header_hovered": shade(COFFEE, 1.25), "header_active": shade(COFFEE, 0.8),
        "tab": FRAME, "tab_hovered": CARAMEL, "text": CREAM,
        "slider_grab": CARAMEL, "slider_grab_active": GOLD, "check_mark": GOLD,
        "plot_histogram": GREEN, "separator": GREY, "table_header_bg": FRAME,
        "title_bg": PANEL, "title_bg_active": PANEL,
    }
    for name, value in palette.items():
        member = getattr(col, name, None)
        if member is None:
            continue
        try:
            style.set_color_(member, value)
        except (AttributeError, TypeError):
            pass
    for name in ("tab_active", "tab_selected"):
        member = getattr(col, name, None)
        if member is not None:
            try:
                style.set_color_(member, CARAMEL)
            except (AttributeError, TypeError):
                pass
    try:
        style.font_scale_main = 1.15          # Dear ImGui >= 1.92
    except (AttributeError, TypeError):
        try:
            imgui.get_io().font_global_scale = 1.15
        except (AttributeError, TypeError):
            pass


def colored_button(label: str, color: ImVec4, size: ImVec2 | None = None) -> bool:
    """Draw a button in a custom colour.

    Args:
        label: button text (use ``##id`` for unique ids).
        color: base colour; hover/active shades are derived.
        size: button size, or None for automatic.

    Returns:
        bool: True on the frame the button is clicked.
    """
    imgui.push_style_color(imgui.Col_.button, color)
    imgui.push_style_color(imgui.Col_.button_hovered, shade(color, 1.25))
    imgui.push_style_color(imgui.Col_.button_active, shade(color, 0.8))
    clicked = imgui.button(label, size if size is not None else ImVec2(0, 0))
    imgui.pop_style_color(3)
    return clicked


def section(title: str) -> None:
    """Draw a section header with a separator line.

    Args:
        title: header text.

    Returns:
        None.
    """
    if hasattr(imgui, "separator_text"):
        imgui.separator_text(title)
    else:
        imgui.spacing()
        imgui.text_colored(GOLD, title)
        imgui.separator()


def tooltip(text: str) -> None:
    """Show a tooltip for the previous item while it is hovered.

    Args:
        text: tooltip text.

    Returns:
        None.
    """
    if text and imgui.is_item_hovered():
        imgui.set_tooltip(text)


def level_bar(ratio: float, overlay: str, warn: bool, danger: bool, width: float = -1.0) -> None:
    """Draw a coloured progress bar (green, amber when warn, red when danger).

    Args:
        ratio: fill 0..1.
        overlay: text drawn on the bar.
        warn: use amber.
        danger: use red (takes precedence).
        width: bar width, -1 = fill the available width.

    Returns:
        None.
    """
    color = RED if danger else AMBER if warn else GREEN
    imgui.push_style_color(imgui.Col_.plot_histogram, color)
    imgui.progress_bar(max(0.0, min(1.0, ratio)), ImVec2(width, 0), overlay)
    imgui.pop_style_color()


def chip(text: str, color: ImVec4) -> None:
    """Draw a small coloured status label followed by same-line spacing.

    Args:
        text: label text.
        color: text colour.

    Returns:
        None.
    """
    imgui.text_colored(color, f"[ {text} ]")
    imgui.same_line()
