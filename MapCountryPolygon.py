"""
Graphic representation of a country.

A country owns one or more ``QGraphicsPolygonItem`` objects (some countries are
drawn as several disjoint shapes).  ``MapCountryPolygon`` keeps them together
and owns their appearance: fill colour, outline, hover highlight, selection
highlight and tooltip.

The reference to this class object is stored on the parenting
:class:`GameLogic.Country.Country` as ``mapPolyObject``.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor, QPen

import Local
import Theme
from Theme import Palette


class MapCountryPolygon:

    def __init__(self, parent, id, polygon):
        super(MapCountryPolygon, self).__init__()
        self.parent = parent          # the MapScene
        self.id = id
        self.flagStr = '<img src="data:image/png;base64,{}">'.\
                format(self.parent.parent.graphics.flagToolTip[self.id])
        self.value = ""
        self.name = Local.strings[Local.DATA_COUNTRIES + self.id][Local.CTRY_NAME]
        self.polys = []
        self._hover = False
        self._selected = False
        #: The current fill, before the transparency option is applied.  The
        #: highlight pens are chosen against it.
        self._fill = QColor(Palette.NEUTRAL)
        self.addPolygon(id, polygon)

    # -- construction -------------------------------------------------------

    def addPolygon(self, id, polygon):
        item = self.parent.addPolygon(polygon)
        item.setPen(QPen(Palette.MAP_OUTLINE, 1.0))
        item.id = id
        item.parent = self
        item.setAcceptHoverEvents(False)
        self.polys.append(item)
        self._apply_tooltip()

    # -- appearance ---------------------------------------------------------

    def _alpha(self):
        """Opacity follows the 'transparent map' option in the View menu."""
        try:
            transparent = self.parent.parent.menu.options[2].isChecked()
        except AttributeError:
            transparent = False
        return 150 if transparent else 235

    def setColor(self, color, caption):
        color = QColor(color)
        self._fill = QColor(color)
        self.value = caption
        color.setAlpha(self._alpha())
        for item in self.polys:
            item.setBrush(QBrush(color))
        self._apply_pen()
        self._apply_tooltip()

    def setHover(self, value):
        value = bool(value)
        if value == self._hover:
            return
        self._hover = value
        self._apply_pen()

    def setSelected(self, value):
        value = bool(value)
        if value == self._selected:
            return
        self._selected = value
        self._apply_pen()

    def _apply_pen(self):
        if self._selected:
            pen = QPen(Theme.outline_highlight(self._fill, Palette.MAP_SELECTED), 2.4)
        elif self._hover:
            pen = QPen(Theme.outline_highlight(self._fill, Palette.MAP_HOVER), 2.0)
        else:
            pen = QPen(Palette.MAP_OUTLINE, 1.0)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.RoundJoin)
        for item in self.polys:
            item.setPen(pen)
            item.setZValue(2 if (self._hover or self._selected) else 1)

    def _apply_tooltip(self):
        text = "%s<b>%s</b>" % (self.flagStr, self.name)
        if self.value:
            text += " &mdash; " + self.value
        for item in self.polys:
            item.setToolTip(text)
