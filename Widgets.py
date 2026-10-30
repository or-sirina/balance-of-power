"""
Small reusable widgets shared by the main window and the dialogs.
"""

import math

from PyQt5.QtCore import (QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer,
                          QVariantAnimation)
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMenu,
                             QPushButton, QScrollArea, QSizePolicy, QWidget)

import Theme
from Theme import Palette, lerp_color


class TensionBar(QWidget):
    """A compact amber-to-red gauge for world tension and nuclear risk."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._caption = ""
        self._detail = ""
        self._phase = 0.0
        self.setMinimumWidth(250)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # The gauge only animates when there is something to be anxious about,
        # and only if animation is switched on at all.
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def setTension(self, value, caption="", detail=""):
        self._value = max(0.0, min(1.0, float(value)))
        self._caption = caption
        self._detail = detail
        should_animate = Theme.motion_enabled() and self._value >= 0.35
        if should_animate and not self._timer.isActive():
            self._timer.start()
        elif not should_animate and self._timer.isActive():
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self):
        # Runs a little faster as the world gets closer to the brink.
        self._phase = (self._phase + 0.08 + 0.22 * self._value) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)

        # Top line: "World tension: <word>" on the left, the DEFCON number and the
        # estimate error right-aligned in small type.  The word comes first so
        # the text reads the same way as the lit blocks below it.
        painter.setFont(Theme.font(7))
        detail_metrics = QFontMetrics(painter.font())
        detail_width = detail_metrics.horizontalAdvance(self._detail) + 2 if self._detail else 0
        if self._detail:
            painter.setPen(QPen(Palette.TEXT_DIM))
            painter.drawText(QRectF(rect.right() - detail_width, rect.top(), detail_width, 12),
                             Qt.AlignRight | Qt.AlignVCenter, self._detail)
        painter.setFont(Theme.font(8, bold=True))
        metrics = QFontMetrics(painter.font())
        painter.setPen(QPen(Palette.TEXT_MUTED))
        room = int(rect.width() - detail_width - 6)
        painter.drawText(QRectF(rect.left(), rect.top(), max(10, room), 12),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(self._caption, Qt.ElideRight, max(10, room)))

        # DEFCON ladder: nine segments, filled from the right.
        segments = 9
        gap = 2.0
        bar_top = rect.top() + 14
        width = (rect.width() - gap * (segments - 1)) / segments
        filled = int(round(self._value * segments))
        for i in range(segments):
            x = rect.left() + i * (width + gap)
            t = i / float(segments - 1)
            hot = lerp_color(Palette.OK, Palette.CRITICAL, t)
            if i < filled:
                color = hot
                # Above DEFCON 4 the gauge breathes, and from DEFCON 2 it
                # blinks: the indicator should be felt, not read.
                if self._value >= 0.35:
                    wave = 0.5 + 0.5 * math.sin(self._phase)
                    if self._value >= 0.8 and i >= filled - 2:
                        color = lerp_color(hot, Palette.TEXT, wave * 0.55)
                    else:
                        color = lerp_color(hot, Palette.TEXT, wave * 0.22)
            else:
                # Unlit rungs keep a faint tint of their own colour, so the
                # gauge still reads as a scale at full peace rather than as an
                # empty strip.
                color = lerp_color(Palette.PANEL, hot, 0.22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(x, bar_top, width, 8), 2, 2)

        painter.end()


class YearCard(QWidget):
    """A large year that fades in and out when the turn changes.

    Reads as the turn of a page, which is what the end of a year is.  Silent
    when animation is switched off, and never intercepts the mouse.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = 0
        self._opacity = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)
        self._animation = None

    def flash(self, year):
        if not Theme.motion_enabled():
            return
        self._year = int(year)
        self.setVisible(True)
        self.raise_()
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setKeyValueAt(0.35, 1.0)
        animation.setEndValue(0.0)
        animation.setDuration(1100)

        def step(value):
            self._opacity = float(value)
            self.update()

        def done():
            self.setVisible(False)
            self._animation = None

        animation.valueChanged.connect(step)
        animation.finished.connect(done)
        self._animation = animation
        animation.start()

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
        painter.drawText(rect.adjusted(0, -8, 0, -8), Qt.AlignCenter, str(self._year))
        painter.setPen(QPen(Palette.TEXT_MUTED))
        painter.setFont(Theme.font(10))
        painter.drawText(rect.adjusted(0, 66, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                         "a new year begins")
        painter.end()


class FlagChip(QWidget):
    """A flag plus a country name, used in lists and headers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.flag = QLabel()
        self.flag.setFixedSize(28, 17)
        self.flag.setScaledContents(True)
        self.label = QLabel()
        layout.addWidget(self.flag)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.setLayout(layout)

    def setCountry(self, pixmap, name):
        self.flag.setPixmap(pixmap)
        self.label.setText(name)


class TurnIndicator(QWidget):
    """Shows whose move it is, and whether we are waiting on the network."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._sub = ""
        self._color = Palette.ACCENT
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setState(self, text, sub="", color=None):
        self._text = text
        self._sub = sub
        if color is not None:
            self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        Theme.draw_panel(painter, rect, radius=6,
                         fill=QColor(Palette.PANEL_ALT), border=QColor(self._color).darker(160))
        painter.setPen(QPen(self._color))
        painter.drawLine(QPointF(rect.left() + 8, rect.top() + 5),
                         QPointF(rect.left() + 8, rect.bottom() - 5))

        # Two lines: the prompt, then the qualifier.  Drawing both on one line
        # used to make them overlap in the narrow turn panel.
        textRect = rect.adjusted(18, 3, -8, -3)
        painter.setFont(Theme.font(10, bold=True))
        painter.setPen(QPen(Palette.TEXT))
        first_height = textRect.height() / 2.0 if self._sub else textRect.height()
        metrics = QFontMetrics(painter.font())
        painter.drawText(QRectF(textRect.left(), textRect.top(), textRect.width(), first_height),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(self._text, Qt.ElideRight, int(textRect.width())))
        if self._sub:
            painter.setFont(Theme.font(8))
            painter.setPen(QPen(Palette.TEXT_DIM))
            metrics = QFontMetrics(painter.font())
            painter.drawText(QRectF(textRect.left(), textRect.top() + first_height,
                                    textRect.width(), textRect.height() - first_height),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(self._sub, Qt.ElideRight, int(textRect.width())))
        painter.end()


class MusicBar(QWidget):
    """A compact music control: previous, play/pause, next, and what is playing.

    The track name is a button, not a label: clicking it opens the playlist, so
    switching between the built-in themes and whatever the player has dropped
    into a ``music`` folder is one click from the map rather than a trip through
    the settings.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        import Music

        self.music = Music
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.backButton = _MusicButton("\u25c0\u25c0", "Previous track")
        self.playButton = _MusicButton("\u25b6", "Play or pause")
        self.forwardButton = _MusicButton("\u25b6\u25b6", "Next track")
        self.nameButton = QPushButton()
        self.nameButton.setFlat(True)
        self.nameButton.setFont(Theme.font(9))
        self.nameButton.setStyleSheet(
            "QPushButton { color: %s; border: none; padding: 0 4px; }"
            "QPushButton:hover { color: %s; }" % (Palette.TEXT_MUTED.name(),
                                                  Palette.ACCENT.name()))
        self.nameButton.setToolTip("Click for the playlist")

        self.backButton.clicked.connect(self.previous)
        self.playButton.clicked.connect(self.toggle)
        self.forwardButton.clicked.connect(self.next)
        self.nameButton.clicked.connect(self.openPlaylist)

        layout.addWidget(self.backButton)
        layout.addWidget(self.playButton)
        layout.addWidget(self.forwardButton)
        layout.addWidget(self.nameButton)
        self.setLayout(layout)
        self.refresh()

    # -- state --------------------------------------------------------------

    def refresh(self):
        """Follow the player: name, playing state, and reason for silence."""
        if not self.music.available():
            self.setVisible(False)
            return
        self.setVisible(True)
        playing = self.music.playing()
        self.playButton.setText("\u275a\u275a" if playing else "\u25b6")
        self.nameButton.setText("\u266a %s" % self.music.now_playing())
        note = self.music.status_note()
        enabled = self.music.enabled()
        self.nameButton.setToolTip(
            note if note else ("%s \u2014 %s" % (self.music.now_playing(),
                                                 self.music.current().description
                                                 if self.music.current() else "")))
        for button in (self.backButton, self.playButton, self.forwardButton):
            button.setEnabled(enabled)
        self.nameButton.setEnabled(enabled)

    # -- actions ------------------------------------------------------------

    def previous(self):
        self.music.previous_track()
        self.refresh()

    def next(self):
        self.music.next_track()
        self.refresh()

    def toggle(self):
        self.music.toggle()
        self.refresh()

    def openPlaylist(self):
        """Every track, with the current one ticked.

        A plain menu rather than a dialog: the list is short, the choice is one
        of a handful, and a dialog for this would be heavier than the thing it
        controls.
        """
        menu = QMenu(self)
        items = self.music.tracks()
        if not items:
            action = menu.addAction(self.music.status_note() or "No tracks")
            action.setEnabled(False)
        for position, track in enumerate(items):
            label = track.title
            if not track.ready:
                label += "  (preparing\u2026)"
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(position == self.music.current_index())
            action.setEnabled(track.ready)
            action.setToolTip(track.description)
            action.triggered.connect(
                lambda _checked=False, index=position: self._choose(index))
        menu.addSeparator()
        folder = menu.addAction("Open the music folder\u2026")
        folder.triggered.connect(self.openFolder)
        menu.exec_(self.nameButton.mapToGlobal(self.nameButton.rect().bottomLeft()))
        self.refresh()

    def _choose(self, position):
        self.music.set_index(position)
        self.refresh()

    def openFolder(self):
        """Create and reveal the folder the player drops their own tracks into."""
        import os
        import Paths
        directory = os.path.join(Paths.user_dir(), "music")
        try:
            os.makedirs(directory, exist_ok=True)
            # Qt picks the right opener on Windows, macOS and Linux.
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(directory))
        except Exception:
            pass
        self.music.refresh_tracks()
        self.refresh()


def _MusicButton(text, tooltip):
    """A small flat transport button."""
    button = QPushButton(text)
    button.setToolTip(tooltip)
    button.setFlat(True)
    button.setFixedSize(26, 20)
    button.setFont(Theme.font(9))
    button.setStyleSheet(
        "QPushButton { color: %s; border: none; background: transparent; }"
        "QPushButton:hover { color: %s; }"
        "QPushButton:disabled { color: %s; }"
        % (Palette.TEXT.name(), Palette.ACCENT.name(),
           Palette.TEXT_DIM.name()))
    return button


class FitScrollArea(QScrollArea):
    """A scroll area that asks for its content's size but accepts much less.

    Plain ``QScrollArea`` reports a small size hint, so a dialog built around
    one opens as a thumbnail; and wrapping content in one is how a dialog is
    made to fit a 1366x768 laptop (a scroll bar is better than a window that
    hangs off the bottom of the screen and hides its own buttons).
    """

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidget(content)

    def sizeHint(self):
        hint = self.widget().sizeHint() if self.widget() is not None else QSize(200, 120)
        # Leave room for a vertical scroll bar so it never costs a horizontal one.
        return QSize(hint.width() + 18, hint.height() + 4)

    def minimumSizeHint(self):
        return QSize(240, 120)


def available_area(widget=None):
    """The usable screen rectangle (taskbar excluded) for ``widget``."""
    import os
    # Test hook: the offscreen platform has a fixed 640x480 screen; this lets
    # the UI checks simulate a 1366x768 laptop (BOP_SCREEN_SIZE=1093x570, in
    # logical pixels, taskbar already subtracted).
    forced = os.environ.get("BOP_SCREEN_SIZE", "")
    if "x" in forced:
        try:
            from PyQt5.QtCore import QRect
            w, h = (int(v) for v in forced.lower().split("x", 1))
            return QRect(0, 0, w, h)
        except ValueError:
            pass
    screen = None
    if widget is not None:
        handle = widget.windowHandle() if widget.isWindow() else None
        if handle is not None:
            screen = handle.screen()
        if screen is None:
            parent = widget.parentWidget()
            if parent is not None and parent.window().windowHandle() is not None:
                screen = parent.window().windowHandle().screen()
    if screen is None:
        screen = QApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def fit_to_screen(widget):
    """Shrink ``widget`` and move it so that it lies inside the screen.

    Lab PCs run 1366x768 at 125-150% scaling, where the room left after the
    taskbar and title bar is about 1090x570 logical pixels.  A dialog that
    opens larger than that loses its buttons off the bottom edge.
    """
    area = available_area(widget)
    if area is None or not widget.isWindow():
        return
    frame = widget.frameGeometry()
    inner = widget.geometry()
    extra_w = max(0, frame.width() - inner.width())
    extra_h = max(0, frame.height() - inner.height())
    # Before the first show the frame is not known yet; assume a title bar.
    if extra_h == 0:
        extra_h = 32
    max_w = max(200, area.width() - extra_w - 4)
    max_h = max(150, area.height() - extra_h - 4)
    width = min(widget.width(), max_w)
    height = min(widget.height(), max_h)
    # A hard minimum bigger than the screen would make the clamp pointless.
    if widget.minimumWidth() > max_w:
        widget.setMinimumWidth(max_w)
    if widget.minimumHeight() > max_h:
        widget.setMinimumHeight(max_h)
    if (width, height) != (widget.width(), widget.height()):
        widget.resize(width, height)
    frame_w = width + extra_w
    frame_h = height + extra_h
    x = max(area.left(), min(widget.x(), area.right() - frame_w + 1))
    y = max(area.top(), min(widget.y(), area.bottom() - frame_h + 1))
    if (x, y) != (widget.x(), widget.y()):
        widget.move(x, y)


class ScreenFitFilter(QObject):
    """Application-wide: every dialog and window is clamped to the screen when shown."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow() \
                and obj.windowType() in (Qt.Window, Qt.Dialog) \
                and not obj.isMaximized() and not obj.isFullScreen():
            try:
                fit_to_screen(obj)
            except Exception:
                pass
        return False
