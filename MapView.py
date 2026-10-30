"""
The map: a QGraphicsView showing the world, plus its legend.

The scene is built from ``data/map_data.json``, which stores each country's
outline as a run-length "compass" string.  Country fills are produced by
:class:`MapPainter.MapPainter`; this module owns interaction — hover
highlighting, selection, the right-click policy menu, double-click close-up and
mouse-wheel zoom.

Four presentation rules are worth knowing before touching the painting code.

* **The sea and the land are painted, the bitmap is not blitted.**  The 948x483
  backing raster went soft the moment the view was zoomed, so the sea is now a
  gradient and the land a vector path filled with a generated texture tile
  (F2 in ``docs/RECOMMENDATIONS.md``).  The bitmap survives only as data: see
  :mod:`GraphicsLoader`.
* **The political fill is multiplied by a relief mask**, so hills and coastlines
  read through the country colours without changing their hue — the two blocs
  have to stay apart at a glance (F1).  It can be switched off.
* **The legend follows the cursor.**  The step a hovered country sits on is
  highlighted in the legend, which is what ties the two panels together (F8).
* **Nothing animates when *Reduce motion* is on.**  The year card, the chart
  reveal and the endgame all ask :mod:`Theme` first, exactly as the map
  cross-fade already did.
"""

from functools import partial
import json
import math

from PyQt5.QtCore import (QEvent, QPoint, QPointF, QRectF, Qt, QTimeLine, QTimer,
                          QVariantAnimation)
from PyQt5.QtGui import (QBrush, QColor, QCursor, QIcon, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPolygonF, QTransform)
from PyQt5.QtWidgets import (QAction, QFrame, QGraphicsPolygonItem, QGraphicsScene,
                             QGraphicsView, QHBoxLayout, QLabel, QMenu, QPushButton,
                             QVBoxLayout, QWidget)

import Local
import Paths
import Sound
import Theme
from MapCountryPolygon import MapCountryPolygon
from MapPainter import MapPainter
from Theme import Palette, lerp_color
from Widgets import YearCard
from constants import (AVL_ACTIONS, INAVL_MAP_MODES, M_DESTAB, M_ECONAID,
                       M_EVENTS, M_PRESS, M_TREATY)

#: Captions and tooltips for the controls this module adds.  Everything else on
#: screen comes from ``data/local/*.json`` through :mod:`Local`, and these four
#: lines belong there too; the exact patch is written up in
#: ``docs/PATCH-REQUESTS-graphics.md``.  A localisation file that does provide
#: the group wins, so dropping a translated table in is all a translator has to
#: do — no Python changes.
_EXTRA_KEYS = ("year_card", "relief", "relief_hint", "sound", "sound_hint", "legend")
_EXTRA_EN = ("a new year begins",
             "Relief shading",
             "Shade the country colours with the terrain",
             "Sound",
             "Signals on the turn change, a crisis and the endgame",
             "Legend")

#: This module's own settings file.  Relief and sound are not part of
#: ``options.dat``: MainWindow owns that format and its writer.
_PREFS_NAME = "graphics.json"


def _caption(key):
    """Localised caption for a control this module adds."""
    index = _EXTRA_KEYS.index(key)
    group = getattr(Local, "GRAPHICS_EXTRA", None)
    if group is not None and group < len(Local.strings):
        table = Local.strings[group]
        if isinstance(table, list) and index < len(table):
            return table[index]
    return _EXTRA_EN[index]


def _load_preferences():
    """Relief and sound switches, with the defaults this feature wants on."""
    preferences = {"relief": True, "sound": True}
    try:
        with open(Paths.user_file(_PREFS_NAME), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return preferences
    if isinstance(stored, dict):
        for key in preferences:
            if key in stored:
                preferences[key] = bool(stored[key])
    return preferences


def _save_preferences(preferences):
    try:
        with open(Paths.user_file(_PREFS_NAME), "w", encoding="utf-8") as handle:
            json.dump(preferences, handle)
    except OSError:
        pass


def _vertical_brush(height, stops):
    """A top-to-bottom brush anchored on the map rectangle.

    Resolution independent, which is the whole point: a bitmap had to be
    resampled both when the view panned and when it zoomed.
    """
    gradient = QLinearGradient(0.0, 0.0, 0.0, float(height))
    for position, color in stops:
        gradient.setColorAt(position, color)
    return QBrush(gradient)


class MapScene(QGraphicsScene):
    """The scene holding the sea, the terrain and every country outline."""

    def __init__(self, parent, world):
        super(MapScene, self).__init__()
        self.parent = parent
        self.graphics = parent.graphics
        self.mapPainter = MapPainter(parent, world)
        width, height = self.graphics.mapSize
        # Pin the scene to the size of the source map: the view centres and
        # scrolls against this rectangle, and it must not shrink to the country
        # outlines now that no pixmap item defines it any more.
        self.setSceneRect(0.0, 0.0, float(width), float(height))
        #: Every country outline in one path.  It is the land mask the painted
        #: sea is worked around; the outlines are parsed once at startup, so
        #: keeping it costs nothing at paint time.
        self.landPath = QPainterPath()
        #: F1.  On by default — the flat fill is the bug this fixes.
        self.reliefEnabled = True
        # Brushes are built once: the map repaints far too often to allocate
        # three gradients and a texture brush on every frame.
        self._chromeBrush = QBrush(Palette.SEA)
        self._seaBrush = _vertical_brush(height, (
            (0.0, QColor(Palette.MAP_SEA_TOP)), (1.0, QColor(Palette.MAP_SEA_BOTTOM))))
        self._landBrush = _vertical_brush(height, (
            (0.0, QColor(Palette.MAP_LAND_TOP)), (0.55, QColor(Palette.MAP_LAND_MID)),
            (1.0, QColor(Palette.MAP_LAND_BOTTOM))))
        self._tileBrush = None
        self._tileScale = None
        self.initCountryPolygons(world)
        self.update()

    def initCountryPolygons(self, world):
        with open(Paths.data("map_data.json"), "r", encoding="utf-8") as f:
            polygons = json.load(f)
        for poly in polygons:
            id, x, y, compass = poly["country_id"] - 1, poly["x"], poly["y"] - 32, poly["compass"]
            c = world.country[id]
            pts = [QPointF(x, y)]
            k = 0
            while k < len(compass):
                if 48 <= ord(compass[k]) <= 57:
                    delta, k = int(compass[k]), k + 1
                else:
                    delta = 1
                if k >= len(compass):
                    break
                if compass[k] == 'n':
                    y -= delta
                elif compass[k] == 's':
                    y += delta
                elif compass[k] == 'e':
                    x += delta
                elif compass[k] == 'w':
                    x -= delta
                pts.append(QPointF(x, y))
                k += 1
            # The graphics items live inside a MapCountryPolygon, which is in
            # turn referenced by the Country object.
            outline = QPolygonF(pts)
            self.landPath.addPolygon(outline)
            if c.mapPolyObject is None:
                c.mapPolyObject = MapCountryPolygon(self, c.id, outline)
            else:
                c.mapPolyObject.addPolygon(c.id, outline)

    # -- the painted base layer (F2) ----------------------------------------

    def _terrain_brush(self, painter):
        """The tiled relief, held at a constant size on screen.

        Compensating the brush transform by the view scale *is* the point of
        "relief as a tile": at 4x zoom the grain is drawn 1:1 again instead of
        being stretched into mush.  The cache is keyed on the scale because the
        zoom animation asks for a new brush on every step.
        """
        scale = painter.transform().m11() or 1.0
        if self._tileBrush is None or self._tileScale != scale:
            brush = QBrush(self.graphics.terrainTile)
            brush.setTransform(QTransform.fromScale(1.0 / scale, 1.0 / scale))
            self._tileBrush = brush
            self._tileScale = scale
        return self._tileBrush

    def drawBackground(self, painter, rect):
        """Sea gradient, land, terrain texture — all painted, none stretched."""
        width, height = self.graphics.mapSize
        horizon = QRectF(0.0, 0.0, float(width), float(height))
        painter.save()
        # The land is a ninety-subpath path and antialiasing it costs more than
        # everything else in the frame put together.  Its edge is covered by the
        # country outlines, which are drawn antialiased as items on top, so the
        # background fills do not need it.
        painter.setRenderHint(QPainter.Antialiasing, False)
        # Outside the map the dark chrome shows through, exactly as it did
        # around the original bitmap.
        painter.fillRect(rect, self._chromeBrush)
        painter.setPen(Qt.NoPen)
        painter.fillRect(horizon.intersected(rect), self._seaBrush)
        if not self.landPath.isEmpty():
            painter.setBrush(self._landBrush)
            painter.drawPath(self.landPath)
            # The texture *modulates* the land rather than covering it:
            # multiplied in, it darkens without washing the olive base out to
            # grey, and a generated tile can be drawn at the resolution it is
            # shown at instead of being stretched from the raster — the other
            # half of F2.
            painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            painter.setBrush(self._terrain_brush(painter))
            painter.drawPath(self.landPath)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.restore()

    def drawForeground(self, painter, rect):
        """Multiply the finished map by the relief mask (F1).

        Doing it here, under the painter's composition mode, is what lets a
        raster landform and flat vector politics meet: the fill keeps its hue
        and picks up the terrain, so mountains read through without the two
        blocs ever being confused for one another.  The sun, the cursor and the
        legend are drawn by the widget afterwards and are not shaded.
        """
        if not self.reliefEnabled:
            return
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        painter.drawImage(0, 0, self.graphics.relief)
        painter.restore()

    def setReliefEnabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self.reliefEnabled:
            return
        self.reliefEnabled = enabled
        self.update()


class LegendPanel(QFrame):
    """A floating legend for the active map mode."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("legendPanel")
        self.setStyleSheet(
            "#legendPanel { background-color: rgba(18, 25, 34, 235);"
            " border: 1px solid %s; border-radius: 6px; }" % Palette.BORDER_LIGHT.name())
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        self.title = QLabel()
        self.title.setFont(Theme.font(9, bold=True))
        self.title.setStyleSheet("color: %s; border: none;" % Palette.ACCENT.name())
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setSpacing(2)
        layout.addLayout(self.rowsLayout)
        self.setLayout(layout)
        self.setVisible(False)
        self._rows = []
        #: Row the country under the cursor sits on, or None (F8).
        self._highlight = None

    def setLegend(self, title, entries):
        self.title.setText((title or "").replace("\n", "<br>"))
        if len(entries) != len(self._rows):
            while self.rowsLayout.count():
                item = self.rowsLayout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._rows = []
            self._highlight = None
            for _ in entries:
                row = QWidget()
                row.setObjectName("legendRow")
                rowLayout = QHBoxLayout()
                rowLayout.setContentsMargins(0, 0, 0, 0)
                rowLayout.setSpacing(6)
                swatch = QLabel()
                swatch.setFixedSize(14, 12)
                caption = QLabel()
                caption.setStyleSheet("color: %s; border: none;" % Palette.TEXT_MUTED.name())
                rowLayout.addWidget(swatch)
                rowLayout.addWidget(caption)
                rowLayout.addStretch(1)
                row.setLayout(rowLayout)
                self.rowsLayout.addWidget(row)
                self._rows.append((row, swatch, caption))
        for (row, swatch, caption), (color, text) in zip(self._rows, entries):
            swatch.setStyleSheet(
                "background-color: %s; border: 1px solid %s; border-radius: 2px;"
                % (color.name(), Palette.BORDER.name()))
            caption.setText(text)
        self._apply_highlight()
        self.refresh_size()

    def refresh_size(self):
        """Re-measure the panel after its rows changed.

        Qt posts layout invalidation as an event, so ``adjustSize`` called
        straight after rebuilding the rows still measures the old height: the
        panel came up as a title with no room for its entries whenever the new
        mode had a different number of steps.  The second pass is deferred, so
        it lands after Qt has processed those invalidation events.
        """
        self.rowsLayout.invalidate()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()
        QTimer.singleShot(0, self.adjustSize)

    def highlight(self, index):
        """Mark the legend step a country occupies, or clear it (F8).

        The caller passes an index rather than a colour: the legend is the only
        place that knows how the ramp was divided, and both sides of the link
        must agree on the step the country is on.
        """
        if index == self._highlight:
            return
        self._highlight = index
        self._apply_highlight()

    def _apply_highlight(self):
        for position, (row, swatch, caption) in enumerate(self._rows):
            if position == self._highlight:
                row.setStyleSheet("#legendRow { background-color: rgba(224, 163, 60, 46);"
                                  " border-radius: 3px; }")
                caption.setStyleSheet("color: %s; border: none;" % Palette.TEXT.name())
                caption.setFont(Theme.font(9, bold=True))
                swatch.setFixedSize(16, 14)
            else:
                row.setStyleSheet("")
                caption.setStyleSheet("color: %s; border: none;" % Palette.TEXT_MUTED.name())
                caption.setFont(Theme.font(9))
                swatch.setFixedSize(14, 12)


class YearBanner(YearCard):
    """The year card, with a caption that comes from the string table.

    ``Widgets.YearCard`` prints a hardcoded English line; the card is otherwise
    exactly what this screen wants, so only the painting is overridden.  See
    the patch request in ``docs/PATCH-REQUESTS-graphics.md`` for folding the
    caption back into the base class.
    """

    def paintEvent(self, event):
        if self._opacity <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect())
        painter.setOpacity(min(1.0, self._opacity))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(9, 13, 19, 170)))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QPen(Palette.ACCENT))
        painter.setFont(Theme.font(48, bold=True))
        # The year sits above centre and the caption below it: the base class
        # drew both around the middle, and long captions met the digits.
        painter.drawText(rect.adjusted(0, -24, 0, -24), Qt.AlignCenter, str(self._year))
        painter.setPen(QPen(Palette.TEXT_MUTED))
        painter.setFont(Theme.font(10))
        painter.drawText(QRectF(rect.left(), rect.top() + rect.height() * 0.58,
                                rect.width(), rect.height() * 0.2),
                         Qt.AlignHCenter | Qt.AlignTop, _caption("year_card"))
        painter.end()


class EndgameOverlay(QWidget):
    """The endgame: the map dims and the DEFCON ladder gutters out (F7).

    Deliberately **no mushroom cloud**.  The original refuses to turn failure
    into a spectacle, and that refusal is part of what the game is arguing, so
    the ending is the light going out and nine rungs dying one after another.

    One ``QVariantAnimation`` drives the whole sequence: nothing polls, nothing
    blocks the event loop, and with *Reduce motion* switched on the final frame
    is shown at once, without flicker.
    """

    _RUNGS = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._fade = 0.0     # the veil over the map
        self._burn = 1.0     # fraction of the ladder still lit
        self._gutter = 0.0   # flicker of the last lit rung
        self._animation = None
        self.hide()

    def start(self):
        self._stop_animation()
        self.setVisible(True)
        self.raise_()
        duration = Theme.duration("endgame")
        if duration <= 0:
            self._settle()
            return
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.valueChanged.connect(self._step)
        animation.finished.connect(self._animation_finished)
        self._animation = animation
        animation.start()

    def stop(self):
        """Take the overlay down again, e.g. when a new game is started."""
        self._stop_animation()
        self._fade = 0.0
        self._burn = 1.0
        self._gutter = 0.0
        self.setVisible(False)

    def _stop_animation(self):
        if self._animation is not None:
            self._animation.stop()
            self._animation = None

    def _step(self, value):
        progress = float(value)
        # The light goes first...
        self._fade = min(1.0, progress / 0.30)
        # ...then the ladder, rung by rung, from the brink outwards.
        burnt = max(0.0, (progress - 0.30) / 0.70)
        self._burn = max(0.0, 1.0 - burnt)
        # The last rung gutters instead of switching off cleanly.  The flicker
        # is a function of the animation's own clock, so it costs no timer.
        if 0.0 < self._burn < 0.34:
            self._gutter = abs(math.sin(progress * 47.0))
        else:
            self._gutter = 0.0
        self.update()

    def _animation_finished(self):
        self._animation = None
        self._settle()

    def _settle(self):
        """The still final frame: dark, and every rung out."""
        self._fade = 1.0
        self._burn = 0.0
        self._gutter = 0.0
        self.update()

    def paintEvent(self, event):
        if self._fade <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect())

        veil = QColor(Palette.MAP_DIM)
        veil.setAlphaF(min(1.0, self._fade))
        painter.fillRect(rect, veil)

        ladder_opacity = max(0.0, (self._fade - 0.4) / 0.6)
        if ladder_opacity <= 0.0:
            painter.end()
            return
        painter.setOpacity(ladder_opacity)
        width = min(rect.width() * 0.68, 460.0)
        height = 18.0
        gap = 5.0
        left = rect.center().x() - width / 2.0
        top = rect.center().y() - height / 2.0 + 12.0
        segment = (width - gap * (self._RUNGS - 1)) / self._RUNGS
        lit = int(round(self._burn * self._RUNGS))
        for i in range(self._RUNGS):
            x = left + i * (segment + gap)
            hot = lerp_color(Palette.OK, Palette.CRITICAL, i / float(self._RUNGS - 1))
            if i < lit:
                colour = hot
                if i == lit - 1 and self._gutter > 0.0:
                    colour = lerp_color(hot, Palette.MAP_DIM, self._gutter * 0.8)
            else:
                # An unlit rung keeps a trace of its own colour, so the ladder
                # still reads as a scale after it has gone out.
                colour = lerp_color(Palette.MAP_DIM, hot, 0.14)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(colour))
            painter.drawRoundedRect(QRectF(x, top, segment, height), 3, 3)

        painter.setPen(QPen(Palette.ACCENT))
        painter.setFont(Theme.font(13, bold=True))
        painter.drawText(QRectF(rect.left(), top - 58, rect.width(), 26),
                         Qt.AlignHCenter | Qt.AlignVCenter,
                         "%s 1" % Local.strings[Local.TENSION][0])
        painter.setPen(QPen(Palette.TEXT_MUTED))
        painter.setFont(Theme.font(11))
        painter.drawText(QRectF(rect.left(), top + 34, rect.width(), 26),
                         Qt.AlignHCenter | Qt.AlignVCenter,
                         Local.strings[Local.MAIN_PANEL][28])
        painter.end()


class MapView(QGraphicsView):
    """Central widget: the world map."""

    def __init__(self, parent, world):
        super(MapView, self).__init__()
        self.parent = parent
        self.setScene(MapScene(parent, world))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        # Keyboard navigation needs the view to be able to hold focus; without
        # this the arrow keys never arrive at keyPressEvent.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background-color: %s;" % Palette.SEA.name())
        self.oldHover, self.hover = None, None
        self.oldSelection, self.selection = None, None
        self.rightSelection = None
        self.mapMode = M_EVENTS
        self._numScheduledScalings = 0
        self.__prevMousePos = QPoint()
        #: Graphics switches.  They live in this module's own file rather than
        #: in ``options.dat``; see docs/PATCH-REQUESTS-graphics.md.
        self.reliefAction = None
        self.soundAction = None
        self._hooksInstalled = False
        self._preferences = _load_preferences()

        # Right-click menu: the first two entries are the country header and the
        # close-up shortcut, then one entry per policy verb.
        self.contextMenu = QMenu()
        self.menuOption = [QAction() for i in range(11)]
        self.menuOption[1].setIcon(parent.graphics.icon[20])
        for i in range(11):
            self.contextMenu.addAction(self.menuOption[i])
            if i < 2:
                self.contextMenu.addSeparator()
            else:
                self.menuOption[i].triggered.connect(partial(parent.policyWindow.setMode, i - 2))

        # Legend toggle button, pinned to the bottom-right corner.
        self.legendButton = QPushButton("\u25a4", self)
        self.legendButton.setCheckable(True)
        self.legendButton.setToolTip(_caption("legend"))
        self.legendButton.setFixedSize(28, 24)
        self.legendButton.clicked.connect(self.hideOrShowLegend)
        self.legendPanel = LegendPanel(self)
        #: The year card, centred over the map, shown when a turn completes.
        self.yearCard = YearBanner(self)
        self.yearCard.resize(280, 160)
        self.yearCard.hide()
        #: The endgame veil.  Hidden until the war ends.
        self.endgameOverlay = EndgameOverlay(self)
        self.setStrings()

        scene = self.scene()
        scene.setReliefEnabled(self._preferences["relief"])
        Sound.set_enabled(self._preferences["sound"])
        # The windows this module listens to (a crisis opening, the game ending)
        # are built after the map, so the wiring waits for the event loop.
        QTimer.singleShot(0, self._installHooks)

    def flashYear(self, year):
        """Mark the new year, and signal it.

        Called by MainWindow when a turn completes.  The signal belongs to this
        beat rather than to the turn loop: the card and the tone are the same
        mark of the game's rhythm (F6).
        """
        Sound.play("turn")
        self.yearCard.resize(280, 160)
        self.yearCard.move(QPoint(max(0, (self.width() - 280) // 2),
                                  max(0, (self.height() - 160) // 2)))
        self.yearCard.flash(year)

    # -- late wiring --------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        self._installHooks()

    def _installHooks(self):
        """Connect to the windows that appear later than this one.

        MainWindow builds the map first, so the crisis and endgame windows do
        not exist in ``__init__``.  An event filter on those windows is enough:
        the map is where the sound and the veil belong, and neither needs the
        turn loop to know that this module exists.
        """
        if self._hooksInstalled:
            return
        self._hooksInstalled = True
        for name in ("crisisWindow", "lostGameWindow"):
            window = getattr(self.parent, name, None)
            if window is not None:
                window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show:
            if watched is getattr(self.parent, "lostGameWindow", None):
                self.showEndgame()
            elif watched is getattr(self.parent, "crisisWindow", None):
                Sound.play("crisis")
        return super().eventFilter(watched, event)

    # -- the graphics switches ----------------------------------------------

    def setColourBlind(self, enabled):
        """Use the colour-safe bloc palette, and rebuild what depends on it (C6).

        The legend tables bake the ramp colours in when they are built, so a
        change of colour-vision mode has to rebuild them rather than just
        repaint the map.
        """
        Theme.set_colour_blind(enabled)
        painter = self.scene().mapPainter
        painter.rebuildLegends()
        if self.selection is not None:
            self.selection.setSelected(True)
        # Repaint in the mode the player is looking at; resetting the view here
        # used to throw them back to Major Events (and drop the selection).
        painter.doMapRedraw(self.selection, self.mapMode, animate=False)
        self.updateLegend()
        # The year card and the legend draw their own labels, so make sure they
        # are rebuilt with the new colours as well.
        if hasattr(self, "setStrings"):
            self.setStrings()
        self._preferences["colour_blind"] = bool(enabled)
        _save_preferences(self._preferences)

    # -- keyboard navigation (C6) -------------------------------------------

    def stepSelection(self, delta):
        """Move the selection to the next or previous country.

        Arrow keys and Tab walk the map, so the whole interface is reachable
        without a mouse: the country panel, the close-up and the policy verbs
        all follow the selection, which makes one keystroke here worth a lot.
        """
        world = getattr(self.parent, "world", None)
        if world is None:
            return False
        # ``selection`` is the map polygon, not the Country: the polygon is what
        # carries setSelected() and what every other part of the view expects.
        order = [c.mapPolyObject for c in world.country
                 if getattr(c, "mapPolyObject", None) is not None]
        if len(order) < 3:
            return False
        current = self.selection
        if current in order:
            index = (order.index(current) + delta) % len(order)
        else:
            index = 0 if delta >= 0 else len(order) - 1
        self.selectCountry(order[index])
        return True

    def selectCountry(self, polygon):
        """Select a country the way a click does, panel and all."""
        if polygon is None:
            return
        if self.selection is not None and self.selection is not polygon:
            self.selection.setSelected(False)
        self.selection = polygon
        self.oldSelection = polygon
        polygon.setSelected(True)
        if polygon.id > 1:
            self.scene().mapPainter.doMapRedraw(polygon, self.mapMode)
        parent = getattr(self, "parent", None)
        if parent is not None and hasattr(parent, "controlPanel"):
            parent.controlPanel.updateSelection()
        self.centerOnSelection()

    def centerOnSelection(self):
        """Keep the selected country in view when it is walked to by keyboard."""
        poly = getattr(self.selection, "mapPolyObject", None)
        if poly is None:
            return
        try:
            self.ensureVisible(poly, 60, 60)
        except (AttributeError, TypeError):
            pass

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Tab):
            if self.stepSelection(1):
                event.accept()
                return
        elif key in (Qt.Key_Left, Qt.Key_Up, Qt.Key_Backtab):
            if self.stepSelection(-1):
                event.accept()
                return
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            parent = getattr(self, "parent", None)
            if self.selection is not None and parent is not None \
                    and hasattr(parent, "showCloseUpForSelection"):
                parent.showCloseUpForSelection()
                event.accept()
                return
        super().keyPressEvent(event)

    def setReliefEnabled(self, enabled):
        """Turn the relief multiply on or off (F1), and remember it."""
        enabled = bool(enabled)
        self.scene().setReliefEnabled(enabled)
        if self.reliefAction is not None:
            self.reliefAction.setChecked(enabled)
        self._preferences["relief"] = enabled
        _save_preferences(self._preferences)

    def setSoundEnabled(self, enabled):
        enabled = Sound.set_enabled(enabled)
        if self.soundAction is not None:
            self.soundAction.setChecked(enabled)
        self._preferences["sound"] = enabled
        _save_preferences(self._preferences)

    # -- the endgame (F7) ---------------------------------------------------

    def showEndgame(self):
        """Dim the map and gutter the ladder.  No mushroom cloud, by design."""
        Sound.play("endgame")
        self.endgameOverlay.resize(self.size())
        self.endgameOverlay.start()

    # -- layout -------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.legendButton.move(self.width() - 38, self.height() - 32)
        self.legendPanel.refresh_size()
        self.legendPanel.move(max(4, self.width() - self.legendPanel.width() - 12), 10)
        if self.legendPanel.isVisible():
            self.legendPanel.raise_()
        if self.endgameOverlay.isVisible():
            self.endgameOverlay.resize(self.size())
            self.endgameOverlay.raise_()
        self.legendButton.raise_()

    def setStrings(self):
        self.menuOption[1].setText(Local.strings[Local.MAIN_PANEL][12])
        # Icons are chosen per verb; the labels come from LABEL_POLICY so that
        # the trade policy (verb 8) needs no extra wiring.
        icons = (5, 4, 0, 1, 2, 3, 6, 7, 8)
        for action in range(9):
            option = self.menuOption[action + 2]
            option.setText(Local.strings[Local.LABEL_POLICY][action])
            option.setIcon(self.parent.graphics.icon[icons[action] + 9])
        self.legendButton.setToolTip(_caption("legend"))

    def hideOrShowLegend(self):
        visible = not self.legendPanel.isVisible()
        self.legendPanel.setVisible(visible)
        if visible:
            self.updateLegend()
            self.legendPanel.raise_()

    def updateLegend(self):
        title, entries = self.scene().mapPainter.legend(
            self.scene().mapPainter.mapMode, self.selection)
        self.legendPanel.setLegend(title, entries)
        self.legendPanel.refresh_size()
        self.legendPanel.move(max(4, self.width() - self.legendPanel.width() - 12), 10)
        # The country under the cursor keeps its step marked across a redraw.
        self._highlightLegend()

    # -- mouse --------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MidButton:
            self.__prevMousePos = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.LeftButton:
            self.oldSelection = self.selection
            self.selection = item.parent if isinstance(item, QGraphicsPolygonItem) else None
            if 8 <= self.mapMode <= 21:
                if self.selection and not (self.selection.id > 1
                        and self.mapMode in (M_DESTAB, M_TREATY, M_PRESS, M_ECONAID)):
                    self.scene().mapPainter.doMapRedraw(self.selection, self.mapMode)
                else:
                    self.selection = self.oldSelection
                    return
            if self.selection != self.oldSelection:
                self._apply_selection_effect()
                if self.selection:
                    if item.id < 2:
                        self.selectSuperpowerEffect()
                    else:
                        self.selectCountryEffect()
                    for i in self.parent.controlPanel.mapModeAction[17:22]:
                        i.setEnabled(True)
                    self.updateMap(item.id)
                else:
                    self.updateMap(None)
                self.parent.controlPanel.updateSelection()
        elif event.button() == Qt.RightButton:
            if isinstance(item, QGraphicsPolygonItem):
                self.rightSelection = self.parent.world.country[item.id]
                availableActions = AVL_ACTIONS[self.parent.world.level - 1]
                for i in range(9):
                    self.menuOption[i + 2].setEnabled(
                        self.rightSelection.id > 1 and i in availableActions
                        and self.parent.can_act())
                self.menuOption[0].setText(
                    Local.strings[Local.DATA_COUNTRIES + self.rightSelection.id][Local.CTRY_NAME])
                self.menuOption[0].setIcon(QIcon(self.parent.graphics.flag[self.rightSelection.id]))
                self.contextMenu.exec(QCursor.pos())
        super().mouseReleaseEvent(event)

    def _apply_selection_effect(self):
        if self.oldSelection is not None:
            self.oldSelection.setSelected(False)
        if self.selection is not None:
            self.selection.setSelected(True)

    def mouseDoubleClickEvent(self, event):
        """Display country close-up on left mouse button double click."""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, QGraphicsPolygonItem):
                self.selection = item.parent
                self.parent.closeUpWindow.loadCountry(self.parent.world.country[item.id])

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MidButton:
            offset = self.__prevMousePos - event.pos()
            self.__prevMousePos = event.pos()
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + offset.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + offset.x())
        else:
            self.oldHover = self.hover
            item = self.itemAt(event.pos())
            if isinstance(item, QGraphicsPolygonItem):
                self.hover = item.parent
            else:
                self.hover = None
            if self.oldHover != self.hover:
                if self.oldHover is not None:
                    self.oldHover.setHover(False)
                if self.hover is not None:
                    self.hover.setHover(True)
                self.parent.hoverCountryChanged(self.hover)
                self._highlightLegend()
        super().mouseMoveEvent(event)

    def _highlightLegend(self):
        """Point the legend at the step the hovered country occupies (F8)."""
        index = None
        if self.hover is not None:
            index = self.scene().mapPainter.legend_index_for(self.hover.id)
        self.legendPanel.highlight(index)

    def wheelEvent(self, event):
        if not self.parent.menu.options[1].isChecked():
            return
        numDegrees = event.angleDelta() / 8
        numSteps = (numDegrees / 15).y()
        self._numScheduledScalings += numSteps
        if self._numScheduledScalings * numSteps < 0:
            self._numScheduledScalings = numSteps
        anim = QTimeLine(350, self)
        anim.setUpdateInterval(20)
        anim.valueChanged.connect(self.scalingTime)
        anim.finished.connect(self.animFinished)
        anim.start()

    def scalingTime(self, x):
        factor = 1.0 + self._numScheduledScalings / 300.0
        self.scale(factor, factor)

    def animFinished(self):
        if self._numScheduledScalings > 0:
            self._numScheduledScalings -= 1
        else:
            self._numScheduledScalings += 1

    # -- map modes ----------------------------------------------------------

    def setMapMode(self, value):
        self.mapMode = value
        self.scene().mapPainter.doMapRedraw(self.selection, self.mapMode)
        self.parent.controlPanel.updateSelection()
        if self.legendPanel.isVisible():
            self.updateLegend()

    def selectNothingEffect(self):
        for i in self.parent.controlPanel.mapModeButton[8:17]:
            i.setEnabled(False)
            i.actionOwner.setEnabled(False)
        for i in self.parent.controlPanel.mapModeAction[17:22]:
            i.setEnabled(False)
        self.parent.controlPanel.updateSelection()

    def selectCountryEffect(self):
        for i in self.parent.controlPanel.mapModeButton[8:13]:
            i.setEnabled(True)
            i.actionOwner.setEnabled(True)
        self.parent.controlPanel.updateSelection()

    def selectSuperpowerEffect(self):
        for i, j in zip(self.parent.controlPanel.mapModeButton[8:17], range(8, 17, 1)):
            if j in INAVL_MAP_MODES[self.parent.world.level - 1]:
                continue
            i.setEnabled(True)
            i.actionOwner.setEnabled(True)
        self.parent.controlPanel.updateSelection()

    def resetMapView(self):
        self.endgameOverlay.stop()
        self.parent.controlPanel.mapModeAction[M_EVENTS].setChecked(True)
        self.selection = None
        self.selectNothingEffect()
        self.mapMode = M_EVENTS
        self.scene().mapPainter.mapMode = M_EVENTS
        self.updateMap(None)
        self.updateLegend()

    def updateMap(self, selected):
        self.scene().mapPainter.paint(self.scene().mapPainter.mapMode, selected)
