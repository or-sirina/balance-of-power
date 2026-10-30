"""
Colour schemes for every map mode.

Each map mode produces, for every country, an integer "level" plus a caption.
This module turns those levels into colours and produces the legend entries the
map view displays.

Compared with the original port this version:

* clamps every colour channel (the old code computed ``QColor(255, 297, 297)``
  for insurgent countries, which is not a valid colour and silently produced
  black patches);
* removes the stray ``print`` that ran on every repaint of the insurgency map;
* derives the ramps from :mod:`Theme` so the map and the chrome agree;
* exposes :meth:`MapPainter.legend` so the legend widget does not have to
  reverse-engineer colours out of the painter.
"""

from PyQt5.QtCore import QVariantAnimation
from PyQt5.QtGui import QColor

import Local
import Theme
from Theme import Palette, lerp_color
from constants import (ENCYCLOPEDIA_UNITS, M_DESTAB, M_DIPL_IN, M_DIPL_OUT,
                       M_ECONAID, M_EVENTS, M_FINLPROB_USA, M_FINLPROB_USSR, M_GNP,
                       M_GNPCAP, M_GOVTAID_IN, M_GOVTAID_OUT, M_GOVTINTV_IN,
                       M_GOVTINTV_OUT, M_GOVTSTAB, M_INSG, M_INSGAID_IN,
                       M_INSGAID_OUT, M_INSGINTV_IN, M_INSGINTV_OUT, M_MILMEN,
                       M_POP, M_PRESS, M_PRESTIGE, M_SPHINFL, M_TRADE_IN,
                       M_TRADE_OUT, M_TREATY, M_WAR)


def _clamp_channel(value):
    value = int(round(value))
    return 0 if value < 0 else (255 if value > 255 else value)


def _ramp(colors, count):
    """Resample a list of colours into exactly ``count`` steps."""
    if count <= 1 or len(colors) == 1:
        return [QColor(colors[0]) for _ in range(max(1, count))]
    out = []
    for i in range(count):
        position = i / float(count - 1) * (len(colors) - 1)
        low = int(position)
        high = min(low + 1, len(colors) - 1)
        out.append(lerp_color(QColor(colors[low]), QColor(colors[high]), position - low))
    return out


#: Index 0 = "Enemy" (red) ... 8 = "Close" (green), matching the localised
#: relation words in ``TAG_RELATION``.  A fuller opinion must look friendlier,
#: so the ramp runs red -> white -> green as the level rises.
_DIPLO_RAMP = [QColor(176, 48, 48), QColor(226, 132, 132), QColor(238, 238, 232),
               QColor(120, 190, 120), QColor(46, 125, 70)]
#: Index 0 = "Absolutely USSR" (red) ... 12 = "Absolutely USA" (blue), matching
#: ``TAG_SPHERE``.  ``Country.getSphOfInfluence`` returns a high value for a
#: high ``dMess``, which is the American sphere.
_SPHERE_RAMP = [QColor(176, 44, 38), QColor(226, 140, 130), QColor(238, 238, 232),
                QColor(120, 164, 220), QColor(38, 92, 168)]
#: Amber -> red, for pressure/insurgency/stability.
_HEAT_RAMP = [QColor(250, 240, 210), QColor(246, 200, 108), QColor(232, 140, 60),
              QColor(198, 74, 48), QColor(140, 26, 26)]
#: The same two scales for a colour-blind reader.  "Hostile" to "friendly" and
#: "Soviet" to "American" are both two-ended scales, and both were drawn with a
#: red end - which is exactly the end that disappears next to the other one.
#: Orange to blue keeps both ends legible, and keeps them distinct from the
#: amber heat ramp used by every other map mode.
_DIPLO_RAMP_SAFE = [QColor(200, 90, 20), QColor(240, 170, 110), QColor(238, 238, 232),
                    QColor(130, 175, 220), QColor(0, 90, 160)]
_SPHERE_RAMP_SAFE = [QColor(214, 94, 0), QColor(240, 170, 110), QColor(238, 238, 232),
                     QColor(130, 180, 225), QColor(0, 100, 175)]


def bloc_ramps():
    """``(diplomacy, sphere)`` ramps for the current colour-vision setting."""
    if Theme.colour_blind():
        return _DIPLO_RAMP_SAFE, _SPHERE_RAMP_SAFE
    return _DIPLO_RAMP, _SPHERE_RAMP


#: Reversed heat, so "good" is cool and "dangerous" is hot.
_HEAT_RAMP_REVERSED = list(reversed(_HEAT_RAMP))
#: Yellow -> red, for resources; green -> dark for the encyclopedia.
_RESOURCE_RAMP = [QColor(250, 232, 160), QColor(246, 196, 90), QColor(232, 130, 50),
                  QColor(180, 46, 32)]
_ENCYCLOPEDIA_RAMP = [QColor(180, 232, 170), QColor(120, 200, 120), QColor(56, 150, 80),
                      QColor(16, 80, 46)]


class MapPainter:

    def __init__(self, parent, world):
        super(MapPainter, self).__init__()

        self.parent = parent
        self.world = world
        self.mapMode = M_EVENTS
        self.buffer = {}
        self.recalculateMapBuffer()
        #: Colours currently on the map, and the running cross-fade (if any).
        self._colors = None
        self._animation = None
        #: The per-country levels the map was last painted from.  Keeping them
        #: is what lets the legend highlight the step a hovered country sits on
        #: without recomputing every value on every mouse move.
        self._values = []

        self._build_legends()

    # -- legends ------------------------------------------------------------

    def rebuildLegends(self):
        """Rebuild the colour tables, e.g. after the palette was swapped.

        The legend tables bake the ramp colours in at construction time, so a
        change of colour-vision mode has to rebuild them, not just repaint.
        """
        self._build_legends()

    def _build_legends(self):
        """Build ``mode -> (captions, colours)`` plus the resource legends.

        Captions and colours always have the same length, which is what lets the
        same table drive both the map fill and the legend panel.
        """
        s = Local.strings
        diplo_ramp, sphere_ramp = bloc_ramps()

        def pair(colors, captions):
            return (list(captions), _ramp(colors, len(captions)))

        self.legends = {
            M_SPHINFL: pair(sphere_ramp, s[Local.TAG_SPHERE]),
            M_EVENTS: pair([QColor("#3a4756"), QColor("#c0553f"), QColor("#3f8f5c"),
                            QColor("#8d5fb8"), QColor("#c9a227")], s[Local.TAG_EVENT]),
            M_INSG: pair(_HEAT_RAMP_REVERSED, s[Local.TAG_INSURGENCY]),
            M_GOVTSTAB: pair(_HEAT_RAMP_REVERSED, s[Local.TAG_COUP_CHANCE]),
            # Finlandisation is a *risk* scale ("Invulnerable" .. "Very high"),
            # so its zero end is the safe one and it takes the ramp the natural
            # way round.  With the reversed ramp the whole world was painted
            # alarm-red for being invulnerable, and the two countries actually at
            # risk came out nearly white.
            M_FINLPROB_USA: pair(_HEAT_RAMP, s[Local.FINL_PROB]),
            M_FINLPROB_USSR: pair(_HEAT_RAMP, s[Local.FINL_PROB]),
            M_WAR: pair([QColor("#e8e4d8"), QColor("#b03030")], s[Local.TAG_WARPEACE]),
            M_DIPL_IN: pair(diplo_ramp, s[Local.TAG_RELATION]),
            M_DIPL_OUT: pair(diplo_ramp, s[Local.TAG_RELATION]),
        }
        policy = s[Local.TAG_POLICY]
        # Policy scales run from "no activity" (pale) to "maximum" (hot), so the
        # ramp is used in its natural light-to-dark order.  The insurgency- and
        # stability-style scales above are the other way round: their zero end
        # is the dangerous one.
        for mode, offset in ((M_GOVTAID_IN, 0), (M_GOVTAID_OUT, 0),
                             (M_INSGAID_IN, 0), (M_INSGAID_OUT, 0),
                             (M_GOVTINTV_IN, 6), (M_GOVTINTV_OUT, 6),
                             (M_INSGINTV_IN, 6), (M_INSGINTV_OUT, 6),
                             (M_ECONAID, 12), (M_DESTAB, 18), (M_PRESS, 24), (M_TREATY, 30)):
            self.legends[mode] = pair(_HEAT_RAMP, policy[offset:offset + 6])
        # Trade policy (Multipolar level) has its own step wording.
        self.legends[M_TRADE_OUT] = pair(_HEAT_RAMP, s[Local.TRADE])
        self.legends[M_TRADE_IN] = pair(_HEAT_RAMP, s[Local.TRADE])

        legend = s[Local.LEGEND][:5]
        self.resourceLegend = pair(_RESOURCE_RAMP, legend)
        # The prestige map is painted by ``_diverging``: dark brown for the
        # lowest, cream at the mean, amber for the highest.
        self.prestigeLegend = pair([QColor("#4a2f10"), QColor("#efe9dd"), Palette.ACCENT], legend)
        self.encyclopediaLegend = pair(_ENCYCLOPEDIA_RAMP, legend)

    def _title_for(self, mode, selection):
        names = Local.strings[Local.MAP_MODE_NAME]
        menu = Local.strings[Local.MENU]
        if mode in (M_TRADE_OUT, M_TRADE_IN):
            # Added after the original 35 map-mode names, so it lives in MENU.
            index = 72 if mode == M_TRADE_OUT else 73
            title = menu[index] if 0 <= index < len(menu) else ""
        elif mode > 34:
            index = mode - 4
            title = menu[index] if 0 <= index < len(menu) else ""
        else:
            title = names[mode] if 0 <= mode < len(names) else ""
        if selection is not None and 8 <= mode <= 21:
            title = "%s\n%s" % (title,
                Local.strings[Local.DATA_COUNTRIES + selection.id][Local.CTRY_NAME])
        elif selection is None and 8 <= mode <= 21 and title:
            # The names of these modes end in "of" / "by": without a country
            # the title would stop mid-sentence.
            title = "%s\n(select a country)" % title
        return title

    def legend(self, mode, selection=None):
        """Return ``(title, [(QColor, caption), ...])`` for the legend panel."""
        captions, colors = self._legend_for(mode)
        return self._title_for(mode, selection), list(zip(colors, captions))

    def _legend_for(self, mode):
        # Trade modes are already in ``legends``; the fallbacks below only serve
        # the resource and encyclopedia families.
        if mode in self.legends:
            return self.legends[mode]
        if mode == M_PRESTIGE:
            return self.prestigeLegend
        if mode > 34:
            return self.encyclopediaLegend
        return self.resourceLegend

    def legend_index_for(self, country_id):
        """Which legend step a country currently occupies, or None.

        Only the discrete modes have a step to highlight: the prestige,
        resource and encyclopedia scales interpolate through 128 colours, so
        there is no row in the legend that a country "is on" and the legend
        simply keeps its normal appearance.
        """
        if self.mapMode not in self.legends:
            return None
        if not 0 <= country_id < len(self._values):
            return None
        steps = len(self.legends[self.mapMode][1])
        index = int(self._values[country_id])
        if 0 <= index < steps:
            return index
        return None

    # -- painting -----------------------------------------------------------

    def paint(self, mode, addArg, animate=False):
        """
        Paint countries on the map and set their tooltip labels.
        `mode` - a positive integer, current map mode
        `addArg` - id of a currently selected country that should be painted black;
                   used in the international relations map modes only, None elsewhere.
        `animate` - cross-fade from the colours currently on the map.  Only worth
                    it when the *mode* changes; a refresh of the same mode should
                    not flash.
        """
        values = [self.getDisplayedValue(i.id, mode, addArg) for i in self.world.country]
        values = [0 if v is None else v for v in values]
        color = self.color_for(mode, values, addArg)
        captions = self.captions_for(mode, values)
        self._values = values

        previous = self._colors
        self._stop_animation()
        if animate and previous is not None and len(previous) == len(color) \
                and Theme.motion_enabled():
            # What each country *is* is known now; only the colour is worth
            # animating.  Leaving the captions to the first animation frame kept
            # the SELECTION panel on the previous mode's wording until the fade
            # ended, and for good when nothing else refreshed it.
            self._set_captions(captions)
            self._cross_fade(previous, color, captions)
        else:
            self._apply(color, captions)
        self._colors = [QColor(c) for c in color]

    # -- cross-fade ---------------------------------------------------------

    def _apply(self, colors, captions):
        for item, colour, caption in zip(self.world.country, colors, captions):
            item.mapPolyObject.setColor(colour, caption)

    def _set_captions(self, captions):
        """Store what each country is showing, without touching its colour."""
        for item, caption in zip(self.world.country, captions):
            item.mapPolyObject.value = caption

    def _stop_animation(self):
        if self._animation is not None:
            self._animation.stop()
            self._animation = None

    def _cross_fade(self, start, end, captions):
        """Interpolate every country's fill from the old palette to the new one."""
        animation = QVariantAnimation()
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(Theme.duration("map_fade"))

        def step(value):
            t = float(value)
            blended = [lerp_color(a, b, t) for a, b in zip(start, end)]
            self._apply(blended, captions)

        animation.valueChanged.connect(step)
        animation.finished.connect(self._animation_finished)
        self._animation = animation
        animation.start()

    def _animation_finished(self):
        self._animation = None

    def color_for(self, mode, values, addArg=None):
        """Turn per-country levels into a list of colours.

        Every discrete mode (spheres, relations, policies, war, events,
        insurgency, stability, Finlandization) is driven by the same
        ``mode -> (captions, colours)`` table that builds the legend, so the map
        and the legend can never disagree.
        """
        if mode in self.legends:
            colors = self.legends[mode][1]
            last = len(colors) - 1
            color = []
            for value in values:
                index = int(value)
                index = 0 if index < 0 else (last if index > last else index)
                color.append(QColor(colors[index]))
        elif mode == M_PRESTIGE:
            color = self._diverging(values, Palette.ACCENT, QColor("#4a2f10"))
        elif mode > 21:
            base = _ENCYCLOPEDIA_RAMP if mode >= 35 else _RESOURCE_RAMP
            color = self._relative(values, base)
        else:
            color = [QColor(Palette.NEUTRAL) for _ in values]

        if addArg is not None and 0 <= addArg < len(color):
            color[addArg] = QColor("#1b2430")
        return color

    def _relative(self, values, ramp):
        """Colour values relative to the mean, so the map always has contrast."""
        if not values:
            return []
        mean = sum(values) / float(len(values))
        _max = max(values)
        colors = _ramp(ramp, 128)
        out = []
        for value in values:
            # Minimum -> pale end, mean -> middle of the ramp, maximum -> dark
            # end, which is the order the legend lists them in.
            if value > mean and _max > mean:
                index = 64 + int((value - mean) / (_max - mean) * 63)
            elif mean > 0:
                index = int(value / mean * 64)
            else:
                index = 0
            index = 0 if index < 0 else (127 if index > 127 else index)
            out.append(QColor(colors[index]))
        return out

    def _diverging(self, values, hot, cold):
        if not values:
            return []
        mean = sum(values) / float(len(values)) or 1.0
        _max = max(values)
        out = []
        for value in values:
            if value > mean and _max > mean:
                t = (value - mean) / (_max - mean)
                out.append(lerp_color(QColor("#efe9dd"), hot, t))
            else:
                t = value / mean if mean else 0.0
                out.append(lerp_color(QColor("#efe9dd"), cold, 1.0 - max(0.0, min(1.0, t))))
        return out

    def captions_for(self, mode, values):
        """Human-readable value for each country in the current map mode."""
        if mode in self.legends or mode > 34 or mode in (M_PRESTIGE,):
            captions = self._legend_for(mode)[0] if mode in self.legends else None
            if captions is not None:
                return [captions[int(v)] if 0 <= int(v) < len(captions) else "" for v in values]
        if mode in (M_GNP, 24, 27, 30):
            return [Local.formatValue(v, 11) for v in values]
        if mode in (M_GNPCAP, 25, 28, 31):
            return [Local.formatValue(v, 12) for v in values]
        if mode in (26, 29, 32):
            return ['{:.1%}'.format(v) for v in values]
        if mode == M_POP:
            return [Local.formatValue(v, 10) for v in values]
        if mode == M_MILMEN:
            return ['{:,}'.format(int(v * 1000)) for v in values]
        if mode == M_PRESTIGE:
            return ['{:,} {}'.format(int(v), Local.strings[Local.UNIT][12]) for v in values]
        if mode > 34:
            index = mode - 35
            units = Local.strings[Local.UNIT]
            unit = units[ENCYCLOPEDIA_UNITS[index]] \
                if index < len(ENCYCLOPEDIA_UNITS) and ENCYCLOPEDIA_UNITS[index] < len(units) else ""
            return [('{:,} {}'.format(int(v), unit)).strip() for v in values]
        return ["" for _ in values]

    def getDisplayedValue(self, id, mode, addArg):
        """
        Return a value associated with the country of specified `id` and the current map mode (`mode`).
        The international relations map modes require `addArg` to be an id of a source country,
        in the other cases, `addArg` is left None.
        """
        c = self.world.country[id]
        actor = None
        if addArg is not None and M_DIPL_OUT <= mode <= M_INSGINTV_IN:
            actor = self.world.country[addArg]
            # The economic aid, destabilisation, pressure and treaty modes read
            # arrays that only a superpower has (a minor country has no econAid
            # of its own); asking a minor for them raised AttributeError inside
            # the paint slot.  A minor country sends none of these, so the
            # truthful answer is zero.  Every other relation mode (opinion,
            # military aid, intervention) exists for minors too.  Modes below
            # M_DIPL_OUT ignore `addArg` apart from the selection highlight, so
            # selecting a minor must not blank them.
            if actor.id >= 2 and mode in (M_ECONAID, M_DESTAB, M_PRESS, M_TREATY):
                return 0
        # value buffered turn-wise
        if mode in self.buffer:
            return self.buffer[mode][id]
        # value buffered game-wise (encyclopedia data)
        elif mode > 34:
            index = mode - 35
            return c.encyclopedia[index] if index < len(c.encyclopedia) else 0
        # non-buffered value
        elif mode == M_WAR:
            return 1 if c.id > 1 and any([i == -127 for i in c.diplOpinion[2:]]) else 0
        elif mode == M_SPHINFL:
            return c.getSphOfInfluence(self.world)
        elif actor is None:
            return 0
        elif mode == M_DIPL_OUT:
            return actor.getDiplOpinionTowards(c)
        elif mode == M_GOVTAID_OUT:
            return actor.govtAid[id]
        elif mode == M_INSGAID_OUT:
            return actor.insgAid[id]
        elif mode == M_GOVTINTV_OUT:
            return actor.govtIntv[id]
        elif mode == M_INSGINTV_OUT:
            return actor.insgIntv[id]
        elif mode == M_ECONAID:
            return actor.econAid[id]
        elif mode == M_DESTAB:
            return actor.destab[id]
        elif mode == M_PRESS:
            return actor.pressure[id]
        elif mode == M_TREATY:
            return actor.treaty[id]
        elif mode == M_TRADE_OUT:
            return actor.trade[id]
        elif mode == M_TRADE_IN:
            return c.trade[addArg]
        elif mode == M_DIPL_IN:
            return c.getDiplOpinionTowards(actor)
        elif mode == M_GOVTAID_IN:
            return c.govtAid[addArg]
        elif mode == M_INSGAID_IN:
            return c.insgAid[addArg]
        elif mode == M_GOVTINTV_IN:
            return c.govtIntv[addArg]
        elif mode == M_INSGINTV_IN:
            return c.insgIntv[addArg]
        return 0

    @staticmethod
    def _finl_step(value):
        """Clamp a finlandization step into the legend's range (0..len-1)."""
        top = len(Local.strings[Local.FINL_PROB]) - 1
        try:
            return max(0, min(top, int(value)))
        except (TypeError, ValueError):
            return 0

    def recalculateMapBuffer(self):
        """
        Create a buffer of values that do not change during a player's turn
        (internal conflicts, economic data).  Refreshed at the start of each turn.
        """
        world = self.world
        self.buffer = {
            M_EVENTS: [i.getMajorEvents() for i in world.country],
            M_PRESTIGE: [i.prestigeVal // 8 for i in world.country],
            M_INSG: [i.getInsurgency() for i in world.country],
            M_GOVTSTAB: [i.getGovtStability() for i in world.country],
            M_FINLPROB_USA: [self._finl_step(i.getCloseUpInfoValue(world, world.USA, 10)[1]) for i in world.country],
            M_FINLPROB_USSR: [self._finl_step(i.getCloseUpInfoValue(world, world.USSR, 10)[1]) for i in world.country],
            M_GNP: [i.getNominalGNP(3) for i in world.country],
            M_GNPCAP: [i.getGNPpcap(3) for i in world.country],
            M_POP: [i.population for i in world.country],
            M_MILMEN: [i.milMen for i in world.country]
        }
        for i in range(3):
            self.buffer[24 + i * 3] = [c.getNominalGNP(i) for c in world.country]
            self.buffer[25 + i * 3] = [c.getGNPpcap(i) for c in world.country]
            self.buffer[26 + i * 3] = [c.gnpFrac[i] / 255.0 for c in world.country]

    def doMapRedraw(self, selection, mapMode, animate=True):
        changed = mapMode != self.mapMode
        self.mapMode = mapMode
        self.paint(mapMode, selection.id if selection is not None else None,
                   animate=animate and changed)

    def setWorld(self, world):
        self.world = world
