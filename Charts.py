"""
Self-contained chart widgets drawn with QPainter.

The original port used ``PyQt5.QtChart`` for the history/economy charts and for
the score window.  That module ships in the separate ``PyQtChart`` wheel, which
is not part of a plain PyQt5 install and — as of this writing — the available
wheels are ABI-incompatible with the PyQt5 wheels distributed for current
CPython builds, so importing it aborts with an undefined-symbol error.  The game
therefore could not start at all.

These widgets reproduce the handful of charts the game actually needs, need no
extra dependency, and match the application theme.

Public API
----------
``LineChart``  – one or more line series.
``BarChart``   – grouped bars, or a 100 % stacked bar.
Both accept ``data`` as a sequence of series, where a series is a sequence of
numbers, and both expose ``setData``, ``setTitle`` and ``setAxisRange``.

Charts draw themselves on progressively the first time they are shown (F5 in
``docs/RECOMMENDATIONS.md``).  Two rules keep that from getting in the way: the
reveal runs only when :mod:`Theme` says motion is wanted, and it is over before
the hover readout is allowed to answer, so a value can never be reported for a
point that has not been drawn yet.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PyQt5.QtGui import (QBrush, QColor, QFontMetrics, QPainter, QPainterPath,
                         QPen, QPolygonF)
from PyQt5.QtWidgets import QSizePolicy, QWidget

import Theme
from Theme import Palette


class ChartBase(QWidget):
    """Common frame, axes and grid painting for the concrete charts."""

    BAR_CHART = 0
    PERCENT_CHART = 1

    #: Fraction of the widget reserved for axis labels.
    LEFT_GUTTER = 42
    RIGHT_GUTTER = 10
    TOP_GUTTER = 24
    BOTTOM_GUTTER = 18

    def __init__(self, parent=None, title=""):
        super().__init__(parent)
        self._title = title
        self._series = []
        self._user_range = None
        self._categories = None
        self._legend = ()
        self._empty_text = "no data yet"
        self._compact = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(90, 70)
        # Hover readout: a chart that shows a shape but no numbers is decoration.
        self.setMouseTracking(True)
        self._hover = None
        #: How much of each series is drawn, 0..1.  1.0 is the normal state:
        #: motion switched off, a chart that has already revealed itself, or a
        #: chart whose data arrived while it was on screen.
        self._reveal = 1.0
        self._revealed = False
        self._revealAnimation = None

    # -- progressive first draw (F5) ----------------------------------------

    def showEvent(self, event):
        """Reveal the series the first time the chart is actually looked at."""
        super().showEvent(event)
        if self._revealed or self._point_count() == 0:
            self._reveal = 1.0
            return
        self._revealed = True
        duration = Theme.duration("chart_draw")
        if duration <= 0 or not Theme.motion_enabled():
            # Reduce motion: the finished chart, immediately.
            self._reveal = 1.0
            self.update()
            return
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.valueChanged.connect(self._step_reveal)
        animation.finished.connect(self._reveal_finished)
        self._revealAnimation = animation
        self._reveal = 0.0
        animation.start()

    def _step_reveal(self, value):
        self._reveal = float(value)
        self.update()

    def _reveal_finished(self):
        self._revealAnimation = None
        self._reveal = 1.0
        self.update()

    def reveal_count(self, count):
        """How many points of a series of ``count`` are drawn right now."""
        if self._reveal >= 1.0 or count <= 1:
            return count
        return max(1, int(round(self._reveal * count)))

    def reveal_window(self, count):
        """``(points to draw, fraction of the next one)`` at this reveal."""
        keep = self.reveal_count(count)
        if self._reveal >= 1.0 or keep >= count or count <= 1:
            return keep, 0.0
        fraction = self._reveal * count - keep
        return keep, max(0.0, min(1.0, fraction))

    # -- public API ---------------------------------------------------------

    def setTitle(self, text):
        self._title = text or ""
        self.update()

    def title(self):
        return self._title

    def setData(self, series):
        """Replace the chart contents.

        ``series`` is a sequence of sequences of numbers.  Series may have
        different lengths and may be empty; the chart adapts.
        """
        cleaned = []
        for s in series or ():
            try:
                cleaned.append([float(v) for v in s])
            except (TypeError, ValueError):
                cleaned.append([])
        self._series = cleaned
        # Data filled in while the chart is off screen reveals itself when the
        # chart is first shown; data refreshed while it is being looked at must
        # not make the line crawl again on every update.
        if not self.isVisible():
            self._revealed = False
            self._reveal = 1.0
        self.update()

    def data(self):
        return self._series

    def setCompact(self, compact=True):
        """Sparkline mode: no axis labels, small margins.

        A chart a few dozen pixels tall cannot hold tick labels; they print on
        top of each other.  The shape and the hover readout remain.
        """
        self._compact = bool(compact)
        if self._compact:
            self.LEFT_GUTTER, self.RIGHT_GUTTER = 8, 8
            self.TOP_GUTTER, self.BOTTOM_GUTTER = 6, 6
        else:
            for name in ("LEFT_GUTTER", "RIGHT_GUTTER", "TOP_GUTTER", "BOTTOM_GUTTER"):
                self.__dict__.pop(name, None)
        self.update()

    def setAxisRange(self, lo, hi):
        """Force the vertical range; ``None`` restores automatic scaling."""
        if lo is None or hi is None:
            self._user_range = None
        else:
            self._user_range = (float(lo), float(hi))
        self.update()

    def setCategories(self, categories):
        self._categories = list(categories) if categories else None
        self.update()

    def setLegend(self, labels):
        self._legend = tuple(labels or ())
        self.update()

    def setEmptyText(self, text):
        self._empty_text = text
        self.update()

    # -- geometry -----------------------------------------------------------

    def _plot_rect(self):
        top = self._plot_top()
        return QRectF(self.LEFT_GUTTER, top,
                      max(1.0, self.width() - self.LEFT_GUTTER - self.RIGHT_GUTTER),
                      max(1.0, self.height() - top - self.BOTTOM_GUTTER))

    # -- legend --------------------------------------------------------------
    #
    # The legend used to be drawn *inside* the plot, on top of the lines, and cut
    # off at the first entry that did not fit ("USA anti..").  It now has its own
    # rows between the title and the plot, wrapping as needed, so it can never
    # hide data.

    def _legend_entries(self):
        return ()

    def _legend_layout(self):
        """``[(x, row, label_text, series_index)]`` and the number of rows."""
        labels = list(self._legend_entries())
        if not labels or self._compact:
            return [], 0
        fm = QFontMetrics(Theme.font(7))
        avail = max(40, self.width() - 16)
        items, x, row = [], 0, 0
        for index, label in enumerate(labels):
            text = fm.elidedText(str(label), Qt.ElideRight, max(20, avail - 11))
            w = 11 + fm.width(text) + 12
            if x > 0 and x + w > avail:
                x, row = 0, row + 1
            items.append((x, row, text, index))
            x += w
        return items, row + 1

    def _plot_top(self):
        _items, rows = self._legend_layout()
        if rows == 0:
            return self.TOP_GUTTER
        return (18 if self._title else 4) + rows * 12 + 6

    def _paint_legend(self, painter, plot):
        items, _rows = self._legend_layout()
        if not items:
            return
        painter.setFont(Theme.font(7))
        fm = QFontMetrics(painter.font())
        base_y = 18 if self._title else 4
        for x, row, text, index in items:
            color = Palette.SERIES[index % len(Palette.SERIES)]
            left = 8 + x
            top = base_y + row * 12
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRect(QRectF(left, top + 3, 8, 6))
            painter.setPen(QPen(Palette.TEXT_MUTED))
            painter.drawText(QPointF(left + 11, top + fm.ascent()), text)

    def _point_count(self):
        return max((len(s) for s in self._series), default=0)

    def _value_range(self):
        if self._user_range is not None:
            return self._user_range
        values = [v for s in self._series for v in s]
        if not values:
            return 0.0, 1.0
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            pad = abs(hi) * 0.1 or 1.0
            lo, hi = lo - pad, hi + pad
        else:
            pad = (hi - lo) * 0.08
            lo, hi = lo - pad, hi + pad
        # Keep zero visible for quantities that are naturally non-negative.
        if min(values) >= 0 and lo < 0:
            lo = 0.0
        return lo, hi

    @staticmethod
    def _nice_ticks(lo, hi, count=4):
        if hi <= lo:
            return [lo]
        raw = (hi - lo) / max(1, count)
        magnitude = 10 ** int(_floor_log10(raw))
        for mult in (1, 2, 2.5, 5, 10):
            step = magnitude * mult
            if step >= raw:
                break
        first = step * int(lo / step)
        ticks, v = [], first
        while v <= hi + step * 0.5 and len(ticks) < 24:
            if v >= lo - step * 0.5:
                ticks.append(v)
            v += step
        return ticks

    # -- hover --------------------------------------------------------------

    def mouseMoveEvent(self, event):
        # While the reveal is running there is nothing to point at yet, and a
        # readout for a point that is not on screen would be a lie.
        if self._reveal < 1.0:
            return
        count = self._point_count()
        if count == 0:
            return
        plot = self._plot_rect()
        if not plot.contains(event.pos()):
            if self._hover is not None:
                self._hover = None
                self.update()
            return
        if count == 1:
            index = 0
        else:
            ratio = (event.pos().x() - plot.left()) / max(1.0, plot.width())
            index = int(round(ratio * (count - 1)))
            index = max(0, min(count - 1, index))
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def _paint_hover(self, painter, plot, lo, hi):
        """Mark the hovered point and print its values."""
        index = self._hover
        if index is None or index >= self._point_count():
            return
        n = self._point_count()
        x = self._x_at(index, n, plot)
        painter.setPen(QPen(QColor(Palette.ACCENT), 1.0, Qt.DashLine))
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        rows = []
        for series_index, series in enumerate(self._series):
            if index < len(series):
                rows.append((Palette.SERIES[series_index % len(Palette.SERIES)],
                             _short_number(series[index])))
        if not rows:
            return
        painter.setFont(Theme.font(7))
        metrics = QFontMetrics(painter.font())
        label = self._label_for(index)
        width = max(metrics.width(label), max(metrics.width(v) for _, v in rows)) + 26
        height = (len(rows) + 1) * (metrics.height() + 1) + 6
        box = QRectF(x + 6, plot.top() + 4, width, height)
        if box.right() > plot.right():
            box.moveLeft(x - width - 6)
        painter.setPen(QPen(Palette.BORDER_LIGHT, 1))
        painter.setBrush(QBrush(QColor(Palette.PANEL_ALT)))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QPen(Palette.TEXT))
        painter.drawText(QRectF(box.left() + 5, box.top() + 3, box.width() - 10,
                                metrics.height()), Qt.AlignLeft, label)
        y = box.top() + 3 + metrics.height()
        for color, value in rows:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRect(QRectF(box.left() + 5, y + metrics.height() / 2.0 - 3, 7, 6))
            painter.setPen(QPen(Palette.TEXT))
            painter.drawText(QRectF(box.left() + 16, y, box.width() - 20,
                                    metrics.height()), Qt.AlignLeft, value)
            y += metrics.height() + 1

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter):
        rect = QRectF(self.rect())
        Theme.draw_panel(painter, rect, radius=5, fill=QColor(Palette.CHART_BG), border=QColor(Palette.BORDER))

        # Title
        if self._title:
            painter.setPen(QPen(Palette.TEXT_MUTED))
            painter.setFont(Theme.font(8, bold=True))
            painter.drawText(QRectF(8, 4, rect.width() - 16, 16),
                             Qt.AlignLeft | Qt.AlignVCenter, _elide(painter, self._title, rect.width() - 16))

        plot = self._plot_rect()
        if self._point_count() == 0:
            painter.setPen(QPen(Palette.TEXT_DIM))
            painter.setFont(Theme.font(8, italic=True))
            painter.drawText(plot, Qt.AlignCenter, self._empty_text)
            return

        lo, hi = self._value_range()
        self._paint_grid(painter, plot, lo, hi)
        self._paint_series(painter, plot, lo, hi)
        self._paint_x_labels(painter, plot)
        if self._reveal >= 1.0:
            self._paint_hover(painter, plot, lo, hi)

    def _paint_grid(self, painter, plot, lo, hi):
        ticks = self._nice_ticks(lo, hi)
        painter.setFont(Theme.font(7))
        fm = QFontMetrics(painter.font())
        labels = _tick_labels(ticks)
        for value, label in zip(ticks, labels):
            y = plot.bottom() - (value - lo) / (hi - lo) * plot.height()
            if y < plot.top() - 1 or y > plot.bottom() + 1:
                continue
            zero = abs(value) < 1e-9
            painter.setPen(QPen(Palette.CHART_AXIS if zero else Palette.CHART_GRID,
                                1.0 if zero else 0.6,
                                Qt.SolidLine if zero else Qt.DotLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            if self._compact:
                continue
            painter.setPen(QPen(Palette.TEXT_DIM))
            painter.drawText(QRectF(0, y - fm.height() / 2.0, plot.left() - 4, fm.height()),
                             Qt.AlignRight | Qt.AlignVCenter, label)
        painter.setPen(QPen(Palette.CHART_AXIS, 1))
        painter.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
        painter.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

    def _paint_x_labels(self, painter, plot):
        n = self._point_count()
        if n == 0 or self._compact:
            return
        painter.setFont(Theme.font(7))
        fm = QFontMetrics(painter.font())
        max_labels = max(2, int(plot.width() // 34))
        stride = max(1, (n + max_labels - 1) // max_labels)
        painter.setPen(QPen(Palette.TEXT_DIM))
        for i in range(0, n, stride):
            x = self._x_at(i, n, plot)
            label = self._label_for(i)
            w = fm.width(label) + 6
            # Keep the label inside the widget: the last one sits on the right
            # edge of the plot and used to lose its final digit.
            left = max(1.0, min(x - w / 2.0, self.width() - w - 1.0))
            painter.drawText(QRectF(left, plot.bottom() + 2, w, self.BOTTOM_GUTTER - 2),
                             Qt.AlignCenter, label)

    def _label_for(self, index):
        if self._categories and index < len(self._categories):
            return str(self._categories[index])
        return str(index + 1)

    @staticmethod
    def _x_at(index, count, plot):
        if count <= 1:
            return plot.center().x()
        return plot.left() + index / float(count - 1) * plot.width()

    def _paint_series(self, painter, plot, lo, hi):
        raise NotImplementedError


class LineChart(ChartBase):
    """One or more line series with visible data points."""

    def __init__(self, data=None, parent=None, title=""):
        super().__init__(parent, title)
        self._point_radius = 2.4
        if data is not None:
            self.setData(data)

    def _paint_series(self, painter, plot, lo, hi):
        span = (hi - lo) or 1.0
        n = self._point_count()
        painter.save()
        painter.setClipRect(plot.adjusted(-2, -6, 2, 2))
        for index, series in enumerate(self._series):
            if not series:
                continue
            color = Palette.SERIES[index % len(Palette.SERIES)]
            points = []
            if n <= 1:
                points = [QPointF(plot.center().x(),
                                  plot.bottom() - (series[0] - lo) / span * plot.height())]
            else:
                for i, value in enumerate(series):
                    x = self._x_at(i, n, plot)
                    y = plot.bottom() - (value - lo) / span * plot.height()
                    points.append(QPointF(x, y))
            # The first draw stops part-way along the line, mid-segment, so the
            # reveal reads as the chart being drawn rather than as the data
            # arriving point by point.
            keep, fraction = self.reveal_window(len(points))
            drawn = points[:keep]
            if not drawn:
                continue
            path_points = list(drawn)
            if fraction > 0.0 and keep < len(points):
                last, following = points[keep - 1], points[keep]
                path_points.append(QPointF(last.x() + (following.x() - last.x()) * fraction,
                                           last.y() + (following.y() - last.y()) * fraction))
            if len(path_points) >= 2:
                path = QPainterPath(path_points[0])
                for point in path_points[1:]:
                    path.lineTo(point)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPath(path)
            # Points
            painter.setPen(QPen(QColor(Palette.CHART_BG), 1))
            painter.setBrush(QBrush(color))
            radius = self._point_radius if len(points) <= 40 else 1.6
            for point in drawn:
                painter.drawEllipse(point, radius, radius)
        painter.restore()
        self._paint_legend(painter, plot)

    def _legend_entries(self):
        if len(self._legend) < 2 and len(self._series) < 2:
            return ()
        return self._legend or tuple("series %d" % (i + 1) for i in range(len(self._series)))


class BarChart(ChartBase):
    """Grouped bars, or a 100 % stacked bar."""

    def __init__(self, data=None, type=ChartBase.BAR_CHART, parent=None, title=""):
        super().__init__(parent, title)
        self._type = type
        if data is not None:
            self.setData(data)

    def _value_range(self):
        if self._user_range is not None:
            return self._user_range
        if self._type == self.PERCENT_CHART:
            return 0.0, 1.0
        values = [v for s in self._series for v in s]
        if not values:
            return 0.0, 1.0
        lo, hi = min(0.0, min(values)), max(values)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        return lo, hi * 1.05

    def _paint_series(self, painter, plot, lo, hi):
        n = self._point_count()
        if n == 0:
            return
        span = (hi - lo) or 1.0
        painter.save()
        painter.setClipRect(plot)
        slot = plot.width() / n
        keep, fraction = self.reveal_window(n)
        if self._type == self.PERCENT_CHART:
            self._paint_stacked(painter, plot, slot, keep)
        else:
            groups = max(1, len(self._series))
            inner = slot * 0.72
            bar_w = inner / groups
            for index, series in enumerate(self._series):
                color = Palette.SERIES[index % len(Palette.SERIES)]
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(color))
                for i, value in enumerate(series):
                    if i >= n or i > keep:
                        break
                    # The bar being grown right now comes up out of the axis.
                    growth = fraction if i == keep else 1.0
                    x = plot.left() + i * slot + (slot - inner) / 2.0 + index * bar_w
                    y = plot.bottom() - (value - lo) / span * plot.height()
                    y = max(plot.top(), min(plot.bottom(), y))
                    height = (plot.bottom() - y) * growth
                    painter.drawRect(QRectF(x + 0.5, plot.bottom() - height,
                                            max(1.0, bar_w - 1.2), height))
        painter.restore()
        self._paint_legend(painter, plot)

    def _paint_stacked(self, painter, plot, slot, count):
        totals = []
        for i in range(count):
            totals.append(sum(s[i] for s in self._series if i < len(s)) or 1.0)
        inner = slot * 0.62
        for i in range(count):
            x = plot.left() + i * slot + (slot - inner) / 2.0
            y_cursor = plot.bottom()
            for index, series in enumerate(self._series):
                if i >= len(series):
                    continue
                fraction = series[i] / totals[i]
                height = fraction * plot.height()
                painter.setPen(QPen(QColor(Palette.CHART_BG), 0.6))
                painter.setBrush(QBrush(Palette.SERIES[index % len(Palette.SERIES)]))
                painter.drawRect(QRectF(x, y_cursor - height, max(1.0, inner), height))
                y_cursor -= height

    def _legend_entries(self):
        return tuple(self._legend[:5])


class Sparkline(QWidget):
    """A tiny borderless trend line, used for inline indicators."""

    def __init__(self, parent=None, color=None):
        super().__init__(parent)
        self._data = []
        self._color = color or Palette.ACCENT
        self.setMinimumHeight(16)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setData(self, data, color=None):
        self._data = [float(v) for v in (data or ())]
        if color is not None:
            self._color = color
        self.update()

    def paintEvent(self, event):
        if len(self._data) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        lo, hi = min(self._data), max(self._data)
        span = (hi - lo) or 1.0
        points = [QPointF(rect.left() + i / (len(self._data) - 1.0) * rect.width(),
                          rect.bottom() - (v - lo) / span * rect.height())
                  for i, v in enumerate(self._data)]
        painter.setPen(QPen(self._color, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF(points))
        painter.end()


# --- helpers ----------------------------------------------------------------

def _floor_log10(value):
    import math
    if value <= 0:
        return 0
    return math.floor(math.log10(value))


def _short_number(value):
    magnitude = abs(value)
    if magnitude >= 1e9:
        return "%.1fB" % (value / 1e9)
    if magnitude >= 1e6:
        return "%.1fM" % (value / 1e6)
    if magnitude >= 1e4:
        return "%.0fk" % (value / 1e3)
    if magnitude >= 1000:
        return "%.1fk" % (value / 1e3)
    if magnitude >= 10 or value == int(value):
        return "%d" % round(value)
    return "%.1f" % value


def _tick_labels(ticks):
    """Axis labels for ``ticks``, with just enough decimals to tell them apart.

    ``_short_number`` rounds, so a narrow range such as 1.68k..1.74k came out as
    "1.7k, 1.7k, 1.7k" and 0..1 in quarters as "0.2, 0.5, 0.8".
    """
    if len(ticks) < 2:
        return [_short_number(v) for v in ticks]
    top = max(abs(v) for v in ticks)
    for scale, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k"), (1.0, "")):
        if top >= scale:
            break
    for decimals in range(0, 5):
        labels = ["%.*f%s" % (decimals, v / scale, suffix) for v in ticks]
        exact = all(abs(round(v / scale, decimals) - v / scale) < 1e-9 for v in ticks)
        if exact and len(set(labels)) == len(labels):
            break
    return ["0" if abs(v) < 1e-9 else l for v, l in zip(ticks, labels)]


def _elide(painter, text, width):
    metrics = QFontMetrics(painter.font())
    return metrics.elidedText(text, Qt.ElideRight, int(width))
