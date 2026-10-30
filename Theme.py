"""
The visual language of the game: palette, fonts, stylesheet and small painting
helpers.

Everything the UI draws should take its colour from here so that the whole
application can be re-skinned in one place.  The look is deliberately a "war
room" palette: deep desaturated blues for chrome, warm amber for emphasis,
blue and red reserved for the two superpowers.
"""

import os

from PyQt5.QtGui import (QBrush, QColor, QFont, QFontDatabase, QLinearGradient,
                         QPainter, QPen)


class Palette:
    """Named colours used across the interface."""

    # Chrome
    WINDOW = QColor("#0e131a")
    WINDOW_TOP = QColor("#131c27")
    WINDOW_BOTTOM = QColor("#090d13")
    PANEL = QColor("#161e29")
    PANEL_ALT = QColor("#1d2734")
    PANEL_HI = QColor("#22303f")
    BORDER = QColor("#2b3849")
    BORDER_LIGHT = QColor("#3d4f66")

    # Text.  Every one of these clears 4.5:1 against the lightest surface it is
    # drawn on (PANEL_HI); ``tools/colorcheck.py`` measures them.
    TEXT = QColor("#e2e9f2")
    TEXT_MUTED = QColor("#93a6bd")
    TEXT_DIM = QColor("#8c9aab")
    TEXT_ON_ACCENT = QColor("#0b1017")

    # Semantic
    ACCENT = QColor("#e0a33c")     # amber: the player's own emphasis
    ACCENT_DIM = QColor("#8a6a2c")
    NEUTRAL = QColor("#7c8b9c")

    #: Links in the manual.  Qt takes an anchor's colour from the widget
    #: palette, not from a stylesheet rule, so this has to exist as a palette
    #: entry to be usable at all.
    LINK = QColor("#6fb0e8")

    OK = QColor("#4fb783")
    WARN = QColor("#e0a33c")
    DANGER = QColor("#e87d72")
    CRITICAL = QColor("#ff3b30")

    # The two blocs.  ``USA``/``USSR`` are *area* colours: map fills, swatches
    # and legend chips, where the muted red reads well against the pale map.
    # As small text or a hairline border on a dark panel the same red falls to
    # 3.1:1 and all but disappears, so the interface uses the ``_TEXT`` pair
    # through :func:`superpower_color`.
    USA = QColor("#4a90d9")
    USSR = QColor("#cf4f45")
    USA_TEXT = QColor("#6aa9e6")
    USSR_TEXT = QColor("#e2857e")

    # Map
    SEA = QColor("#12202e")
    #: Country outlines, the hover pen and the selection pen.  They are drawn by
    #: ``MapCountryPolygon``; the hover and selection pens fall back to
    #: :data:`MAP_OUTLINE` on a pale country, where white would vanish.
    MAP_OUTLINE = QColor("#2a3442")
    MAP_HOVER = QColor("#ffffff")
    MAP_SELECTED = QColor("#ffd166")
    # The sea and the land are painted rather than blitted from the backing
    # bitmap, so their colours now live here with the rest of the palette.  The
    # two sea stops stay in the family of the original flat #addfff: the map is
    # the one bright surface in a dark interface and should remain readable.
    MAP_SEA_TOP = QColor("#b7ddf7")
    MAP_SEA_BOTTOM = QColor("#8bbde6")
    MAP_LAND_TOP = QColor("#a9b48d")
    MAP_LAND_MID = QColor("#b7c28d")
    MAP_LAND_BOTTOM = QColor("#a6b884")
    #: Veil for the endgame: near-black, so the map goes out without turning a
    #: colour that is not already in the room.
    MAP_DIM = QColor("#05070a")

    # Charts
    CHART_BG = QColor("#111925")
    CHART_GRID = QColor("#243244")
    CHART_AXIS = QColor("#54677e")
    SERIES = (QColor("#4a90d9"), QColor("#cf4f45"), QColor("#e0a33c"),
              QColor("#4fb783"), QColor("#a774d6"), QColor("#31b0b0"))


# --- Motion -----------------------------------------------------------------

#: Durations, in milliseconds.  Every animation goes through :func:`duration`
#: so that one switch turns them all off.
MOTION = {
    "map_fade": 260,
    "pulse": 900,
    "chart_draw": 420,
    "year_card": 1100,
    "endgame": 2600,
}

_MOTION_OVERRIDE = None


def set_motion_enabled(enabled):
    """Turn animation on or off at runtime (the Settings menu calls this)."""
    global _MOTION_OVERRIDE
    _MOTION_OVERRIDE = bool(enabled)


def motion_enabled():
    """False when the user, the environment or a policy asked for calm.

    ``BOP_REDUCE_MOTION=1`` is honoured because corporate builds sometimes need
    to switch animation off centrally, and because it is the accessible default
    on a remote desktop.
    """
    if _MOTION_OVERRIDE is not None:
        return _MOTION_OVERRIDE
    return os.environ.get("BOP_REDUCE_MOTION", "").strip() not in ("1", "true", "yes")


def duration(name):
    """Milliseconds for a named animation, or 0 when motion is disabled."""
    return MOTION.get(name, 200) if motion_enabled() else 0


# --- Typography -------------------------------------------------------------

_PREFERRED_FAMILIES = (
    "Inter", "Segoe UI", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Sans Serif",
)
_MONO_FAMILIES = ("JetBrains Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono", "Monospace")

_UI_FAMILY = None
_MONO_FAMILY = None


def _pick_family(candidates):
    available = set(QFontDatabase().families())
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


def ui_family():
    global _UI_FAMILY
    if _UI_FAMILY is None:
        _UI_FAMILY = _pick_family(_PREFERRED_FAMILIES)
    return _UI_FAMILY


def mono_family():
    global _MONO_FAMILY
    if _MONO_FAMILY is None:
        _MONO_FAMILY = _pick_family(_MONO_FAMILIES)
    return _MONO_FAMILY


def font(size=10, bold=False, mono=False, italic=False):
    """Build an application font with sensible defaults."""
    f = QFont(mono_family() if mono else ui_family(), size)
    f.setBold(bold)
    f.setItalic(italic)
    if not mono:
        f.setStyleStrategy(QFont.PreferAntialias)
    return f


# --- Stylesheet -------------------------------------------------------------

def stylesheet():
    """Return the application-wide Qt style sheet."""
    p = Palette
    return f"""
    QWidget {{
        background-color: {p.WINDOW.name()};
        color: {p.TEXT.name()};
        font-family: "{ui_family()}";
        font-size: 12px;
        selection-background-color: {p.ACCENT.name()};
        selection-color: {p.TEXT_ON_ACCENT.name()};
    }}

    QMainWindow, QDialog {{ background-color: {p.WINDOW.name()}; }}

    /* A shallow top-to-bottom gradient gives the chrome some depth; a flat
       fill makes the panels above it look pasted on. */
    QMainWindow {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {p.WINDOW_TOP.name()},
                                    stop:0.45 {p.WINDOW.name()},
                                    stop:1 {p.WINDOW_BOTTOM.name()});
    }}
    QDialog {{ background-color: {p.WINDOW.name()}; }}

    QMenuBar {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {p.PANEL_ALT.name()},
                                    stop:1 {p.PANEL.name()});
        border-bottom: 1px solid {p.BORDER_LIGHT.name()};
        padding: 2px 4px;
    }}
    QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: 3px; }}
    QMenuBar::item:selected {{ background-color: {p.PANEL_ALT.name()}; color: {p.ACCENT.name()}; }}

    QMenu {{
        background-color: {p.PANEL_ALT.name()};
        border: 1px solid {p.BORDER_LIGHT.name()};
        padding: 4px;
    }}
    QMenu::item {{ padding: 5px 24px 5px 26px; border-radius: 3px; }}
    QMenu::item:selected {{ background-color: {p.ACCENT_DIM.name()}; color: {p.TEXT.name()}; }}
    QMenu::item:disabled {{ color: {p.TEXT_DIM.name()}; }}
    QMenu::separator {{ height: 1px; background: {p.BORDER.name()}; margin: 4px 8px; }}

    QDockWidget {{
        background-color: {p.PANEL.name()};
        border: 1px solid {p.BORDER.name()};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{ background-color: {p.PANEL.name()}; padding: 2px; }}

    QLabel {{ background: transparent; }}

    QPushButton {{
        background-color: {p.PANEL_ALT.name()};
        border: 1px solid {p.BORDER_LIGHT.name()};
        border-radius: 4px;
        padding: 4px 10px;
        color: {p.TEXT.name()};
    }}
    QPushButton:hover {{ background-color: {p.PANEL_HI.name()}; border-color: {p.ACCENT_DIM.name()}; }}
    QPushButton:pressed {{ background-color: {p.ACCENT_DIM.name()}; }}
    QPushButton:checked {{
        background-color: {p.ACCENT_DIM.name()};
        border-color: {p.ACCENT.name()};
    }}
    QPushButton:disabled {{ color: {p.TEXT_DIM.name()}; border-color: {p.BORDER.name()}; background-color: {p.PANEL.name()}; }}
    QPushButton:focus {{ outline: none; }}

    QPushButton#primary {{
        background-color: {p.ACCENT.name()};
        color: {p.TEXT_ON_ACCENT.name()};
        border: 1px solid {p.ACCENT.name()};
        font-weight: bold;
    }}
    QPushButton#primary:hover {{ background-color: {p.ACCENT.lighter(115).name()}; }}
    QPushButton#primary:disabled {{ background-color: {p.PANEL_ALT.name()}; color: {p.TEXT_DIM.name()}; border-color: {p.BORDER.name()}; }}

    QPushButton#danger {{
        background-color: {p.DANGER.name()};
        color: #ffffff;
        border: 1px solid {p.DANGER.name()};
        font-weight: bold;
    }}
    QPushButton#danger:hover {{ background-color: {p.DANGER.lighter(115).name()}; }}

    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background-color: {p.CHART_BG.name()};
        border: 1px solid {p.BORDER_LIGHT.name()};
        border-radius: 4px;
        padding: 4px 6px;
        color: {p.TEXT.name()};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {p.ACCENT.name()}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background-color: {p.PANEL_ALT.name()};
        border: 1px solid {p.BORDER_LIGHT.name()};
    }}

    QGroupBox {{
        border: 1px solid {p.BORDER.name()};
        border-radius: 6px;
        margin-top: 14px;
        padding: 10px 8px 8px 8px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
        color: {p.ACCENT.name()};
    }}

    QTabWidget::pane {{ border: 1px solid {p.BORDER.name()}; border-radius: 6px; top: -1px; }}
    QTabBar::tab {{
        background: {p.PANEL.name()};
        border: 1px solid {p.BORDER.name()};
        border-bottom: none;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
        padding: 6px 14px;
        margin-right: 2px;
        color: {p.TEXT_MUTED.name()};
    }}
    QTabBar::tab:selected {{ background: {p.PANEL_ALT.name()}; color: {p.ACCENT.name()}; }}
    QTabBar::tab:hover {{ color: {p.TEXT.name()}; }}

    QRadioButton, QCheckBox {{ spacing: 6px; padding: 2px; }}
    QRadioButton::indicator, QCheckBox::indicator {{ width: 13px; height: 13px; }}
    QRadioButton::indicator {{
        border: 1px solid {p.BORDER_LIGHT.name()};
        border-radius: 7px;
        background: {p.CHART_BG.name()};
    }}
    QRadioButton::indicator:checked {{
        background: {p.ACCENT.name()};
        border: 3px solid {p.CHART_BG.name()};
        outline: 1px solid {p.ACCENT.name()};
    }}
    QCheckBox::indicator {{
        border: 1px solid {p.BORDER_LIGHT.name()};
        border-radius: 3px;
        background: {p.CHART_BG.name()};
    }}
    QCheckBox::indicator:checked {{ background: {p.ACCENT.name()}; }}
    QRadioButton:disabled, QCheckBox:disabled {{ color: {p.TEXT_DIM.name()}; }}

    QTableWidget, QTableView, QListWidget {{
        background-color: {p.CHART_BG.name()};
        alternate-background-color: {p.PANEL.name()};
        border: 1px solid {p.BORDER.name()};
        gridline-color: {p.BORDER.name()};
        border-radius: 4px;
    }}
    QTableWidget::item:selected, QListWidget::item:selected {{
        background-color: {p.ACCENT_DIM.name()};
        color: {p.TEXT.name()};
    }}
    QHeaderView::section {{
        background-color: {p.PANEL_ALT.name()};
        color: {p.TEXT_MUTED.name()};
        border: none;
        border-right: 1px solid {p.BORDER.name()};
        border-bottom: 1px solid {p.BORDER.name()};
        padding: 4px 6px;
        font-weight: bold;
    }}
    QTableCornerButton::section {{ background-color: {p.PANEL_ALT.name()}; border: none; }}

    QScrollBar:vertical {{ background: {p.WINDOW.name()}; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {p.BORDER_LIGHT.name()};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.ACCENT_DIM.name()}; }}
    QScrollBar:horizontal {{ background: {p.WINDOW.name()}; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {p.BORDER_LIGHT.name()};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QToolTip {{
        background-color: {p.PANEL_ALT.name()};
        color: {p.TEXT.name()};
        border: 1px solid {p.ACCENT_DIM.name()};
        padding: 4px 6px;
    }}

    QStatusBar {{ background: {p.PANEL.name()}; }}
    QSplitter::handle {{ background: {p.BORDER.name()}; }}
    """


# --- Painting helpers -------------------------------------------------------

def panel_gradient(rect, top=None, bottom=None):
    """Vertical gradient used to fill panels and headers."""
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, top or Palette.PANEL_ALT)
    grad.setColorAt(1.0, bottom or Palette.PANEL)
    return grad


def draw_panel(painter, rect, radius=6, fill=None, border=None):
    """Fill a rounded rectangle with an optional border."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(border or Palette.BORDER, 1))
    painter.setBrush(QBrush(fill if fill is not None else panel_gradient(rect)))
    painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), radius, radius)
    painter.restore()


#: Deutan- and protan-safe stand-ins for the two blocs.  Red against green is
#: the single worst pair for the most common forms of colour blindness, and the
#: map depends on telling the two blocs apart at a glance; blue against orange
#: (Okabe-Ito) survives every common form.
BLOC_SAFE = (QColor("#0072b2"), QColor("#d55e00"))
#: The same pair as text: Okabe-Ito is drawn for large areas on white paper, and
#: both of its colours sit too close to a dark panel to be read as a label.
BLOC_SAFE_TEXT = (QColor("#2ea8f0"), QColor("#f96e00"))
#: The original pair, kept so the switch is reversible at runtime.
BLOC_DEFAULT = (QColor("#4a90d9"), QColor("#cf4f45"))
BLOC_DEFAULT_TEXT = (QColor("#6aa9e6"), QColor("#e2857e"))

#: None until somebody chooses; then True or False.
_COLOUR_BLIND = None


def set_colour_blind(enabled):
    """Swap the bloc colours for a colour-safe pair, at runtime.

    The interface reads ``Palette.USA`` / ``Palette.USSR`` in several places and
    ``superpower_color`` in others, so the palette entries themselves are
    rewritten rather than introducing a second accessor that half the code would
    forget to use.  Fills and text move together: a map painted blue next to a
    label painted blue at a different lightness looks like a bug.
    """
    global _COLOUR_BLIND
    _COLOUR_BLIND = bool(enabled)
    usa, ussr = BLOC_SAFE if _COLOUR_BLIND else BLOC_DEFAULT
    usa_text, ussr_text = (BLOC_SAFE_TEXT if _COLOUR_BLIND else BLOC_DEFAULT_TEXT)
    Palette.USA = QColor(usa)
    Palette.USSR = QColor(ussr)
    Palette.USA_TEXT = QColor(usa_text)
    Palette.USSR_TEXT = QColor(ussr_text)


def colour_blind():
    """Whether the colour-safe palette is in use."""
    return bool(_COLOUR_BLIND)


def superpower_color(country_id):
    """Blue for the USA (id 0), red for the USSR (id 1), grey otherwise.

    This is the *text and border* colour, not the map fill: the callers put it
    on a dark panel, where the muted fill red cannot be read.
    """
    if country_id == 0:
        return QColor(Palette.USA_TEXT)
    if country_id == 1:
        return QColor(Palette.USSR_TEXT)
    return QColor(Palette.TEXT_MUTED)


#: WCAG thresholds used to choose pens for the map.
LIGHT_FILL = 0.45
#: The contrast a highlight has to reach before it is worth drawing.
HIGHLIGHT_CONTRAST = 3.0


def relative_luminance(color):
    """WCAG relative luminance, 0 for black and 1 for white."""
    color = QColor(color)

    def channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return (0.2126 * channel(color.red()) + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def contrast_ratio(a, b):
    """WCAG 2.1 contrast ratio between two colours, 1.0 to 21.0."""
    la, lb = relative_luminance(a), relative_luminance(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def is_light(color):
    """True for a fill that white text or a white line would disappear into."""
    return relative_luminance(color) > LIGHT_FILL


def outline_highlight(fill, highlight=None):
    """A pen that will actually show on ``fill``.

    The country fills run from near-white to near-black, so a fixed white hover
    outline vanishes on the pale end of every ramp -- which is where a player is
    most likely to be looking for it.  ``highlight`` is used when it has enough
    contrast; otherwise the better of the map's white and dark outlines is, and
    one of those two always reaches 3.5:1 whatever the fill.
    """
    fill = QColor(fill)
    if highlight is not None and contrast_ratio(highlight, fill) >= HIGHLIGHT_CONTRAST:
        return QColor(highlight)
    light = contrast_ratio(Palette.MAP_HOVER, fill)
    dark = contrast_ratio(Palette.MAP_OUTLINE, fill)
    return QColor(Palette.MAP_HOVER if light >= dark else Palette.MAP_OUTLINE)


def lerp_color(a, b, t):
    """Linear interpolation between two colours; ``t`` in [0, 1]."""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def pressure_color(value, lo, hi):
    """Map a numeric value to a green -> amber -> red ramp."""
    span = (hi - lo) or 1
    t = (value - lo) / span
    if t < 0.5:
        return lerp_color(Palette.OK, Palette.WARN, t * 2)
    return lerp_color(Palette.WARN, Palette.CRITICAL, (t - 0.5) * 2)
