"""
Loads the in-game graphics into program memory.

Three things here are not a straight file load.

**The advisor portraits.**  The original four are *black line art on
transparency*, drawn for the 1981 game's white interface; composited as-is onto
this port's dark chrome they are all but invisible.  :func:`_card` therefore
prints a portrait onto a small cream mat with a coloured edge, the way a
photograph sits on a desk.

**The roster is per side.**  Playing the Americans you are advised by Shultz,
Kirkpatrick, Casey and Weinberger; playing the Soviets, by Gromyko, Chernenko,
Andropov and Ustinov (see :mod:`GameLogic.Advisors`).  If the historical
photographs have not been installed the original line art is used instead, so a
bare checkout still plays.

**The map is no longer one stretched bitmap.**  ``img/background.png`` is
948x483, and blowing it up to fill a zoomed view is what made the map mushy.
The bitmap is still read, but only as *data*: :func:`_relief_mask` turns its
brightness into a multiply mask, which the map scene lays over the political
fill so that hills and coastlines read through the country colours, and
:func:`relief_tile` generates the small seamless texture that replaces the
stretched raster as the terrain layer.  Both are built here because this class
already owns the bitmap.
"""

import os
import random

from PyQt5.QtCore import QBuffer, QIODevice, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter,
                         QPen, QPixmap, QRadialGradient)

import Paths
from GameLogic import Advisors

#: Card edge colour per advisor *slot*.  The 1990 source passes the advisor
#: index as the ``Bias`` argument of the importance function, so each advisor
#: weights one factor more heavily than the others; the colours say which, and
#: the caption under each portrait names it.
ADVISOR_RINGS = (
    QColor("#e0a33c"),   # 0 — diplomatic affinity
    QColor("#5b8fc9"),   # 1 — treaties and commitments
    QColor("#4fb783"),   # 2 — sphere of influence
    QColor("#cf4f45"),   # 3 — adventurousness / military posture
)

#: Card geometry.
SMALL_CARD = (72, 86)
LARGE_CARD = (112, 134)

#: Icon sizes pre-rendered into every ``QIcon``.  Qt then picks a pixmap that
#: already exists instead of scaling one down badly, which is what made the
#: toolbar look soft on a scaled display (see F3 in docs/RECOMMENDATIONS.md).
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64)

#: The sea in the source bitmap is a single flat grey; the tone curve is
#: calibrated so that value maps to white, i.e. "no shading at all".
_SHADE_SEA = 210.0
#: The darkest the mask may go.  A floor rather than zero, because a black
#: mask would turn the political colours into mud and destroy the one thing the
#: map has to communicate: which bloc a country belongs to.
_SHADE_FLOOR = 0.45
#: A power curve, so the mid-tones (where the terrain actually lives) separate
#: more than the highlights do.
_SHADE_GAMMA = 1.5

#: Generated terrain tile size, in device pixels before the pixel ratio.
TILE_SIZE = 96


def _card(source, width, height, ring, cover=False):

    """Print a portrait onto a cream mat with a coloured edge.

    ``cover=True`` centre-crops the source to fill the mat (right for a
    photograph); ``cover=False`` fits the whole image inside it (right for the
    original line art, which must not lose the top of a head).
    """
    card = QPixmap(width, height)
    card.fill(Qt.transparent)
    painter = QPainter(card)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # Soft drop shadow, so the card sits above the panel rather than in it.
    painter.setPen(Qt.NoPen)
    for step in range(4, 0, -1):
        painter.setBrush(QBrush(QColor(0, 0, 0, 14)))
        painter.drawRoundedRect(QRectF(step * 0.7, step * 1.1,
                                       width - 2.0, height - 2.0), 7, 7)

    body = QRectF(0.5, 0.5, width - 2.0, height - 2.0)
    paper = QLinearGradient(body.topLeft(), body.bottomLeft())
    paper.setColorAt(0.0, QColor("#faf7f0"))
    paper.setColorAt(0.55, QColor("#efe9dc"))
    paper.setColorAt(1.0, QColor("#d9cfba"))
    painter.setPen(QPen(ring, 2.0))
    painter.setBrush(QBrush(paper))
    painter.drawRoundedRect(body, 7, 7)

    margin = max(4.0, width * 0.075)
    target = body.adjusted(margin, margin, -margin, -margin)
    if not source.isNull():
        if cover:
            scaled = source.scaled(int(target.width()), int(target.height()),
                                   Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
            # Centre-crop the overflow in both axes.
            x = (scaled.width() - target.width()) / 2.0
            y = (scaled.height() - target.height()) / 2.0
            painter.setClipRect(target)
            painter.drawPixmap(int(target.left() - x), int(target.top() - y), scaled)
            painter.setClipping(False)
        else:
            scaled = source.scaled(int(target.width()), int(target.height()),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(int(target.left() + (target.width() - scaled.width()) / 2.0),
                               int(target.top() + (target.height() - scaled.height()) / 2.0),
                               scaled)

    # Photo-print sheen: a faint vignette plus a hairline highlight.
    vignette = QRadialGradient(body.center(), max(width, height) * 0.72)
    vignette.setColorAt(0.58, QColor(255, 255, 255, 0))
    vignette.setColorAt(1.0, QColor(70, 55, 30, 44))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(vignette))
    painter.drawRoundedRect(body.adjusted(1.5, 1.5, -1.5, -1.5), 6, 6)
    painter.setPen(QPen(QColor(255, 255, 255, 100), 1.0))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(body.adjusted(3.0, 3.0, -3.0, -3.0), 4, 4)
    painter.end()
    return card


# --- relief and terrain -----------------------------------------------------

def _shade_table():
    """A 256-entry tone curve as a ``bytes`` translation table.

    ``bytes.translate`` runs in C, so the whole 948x483 mask is remapped in one
    call instead of 457 884 Python-level pixel writes.
    """
    table = bytearray(256)
    for value in range(256):
        relative = value / _SHADE_SEA
        if relative > 1.0:
            relative = 1.0
        mask = _SHADE_FLOOR + (1.0 - _SHADE_FLOOR) * (relative ** _SHADE_GAMMA)
        table[value] = int(mask * 255.0 + 0.5)
    return bytes(table)


def _tone_mapped(gray, table):
    """Remap an 8-bit grey image through ``table``, in one pass."""
    pointer = gray.constBits()
    pointer.setsize(gray.byteCount())
    mapped = bytes(pointer).translate(table)
    # The QImage borrows the buffer, so copy before the bytes object goes away.
    borrowed = QImage(mapped, gray.width(), gray.height(), gray.bytesPerLine(),
                      QImage.Format_Grayscale8)
    return borrowed.copy().convertToFormat(QImage.Format_ARGB32)


def _relief_mask(source):
    """Build the multiply mask that makes the political fill read as terrain.

    Brightness is the only channel used: the sea in the source is one flat
    grey exactly at :data:`_SHADE_SEA`, so it maps to white and vanishes, while
    the land — and the black coastline the original drew — map to a darker
    grey.  Multiplying the finished map by this layer shades the country
    colours without touching their hue, which is what keeps the two blocs
    apart.
    """
    gray = source.convertToFormat(QImage.Format_Grayscale8)
    return _tone_mapped(gray, _shade_table())


def relief_tile(size=TILE_SIZE, scale=1):
    """Generate the seamless terrain texture drawn over the land.

    Procedural rather than a stored bitmap, for the same reason the sea is a
    gradient: a tile is generated at the resolution it is shown at, so it can
    be rendered at the device pixel ratio instead of upscaled from a small
    image.  ``random.Random`` is seeded explicitly — the game seeds the global
    generator for its own dice, and a texture must not consume that stream.
    """
    size = max(8, int(size * max(1, scale) + 0.5))
    rng = random.Random(0xB0F1E)
    # A coarse value grid, bilinearly interpolated with wrap-around: the wrap is
    # what makes the tile seamless, so tiling it never shows a join.
    cells = 6
    # A whole number of cells per tile, or the wrap lands mid-cell and the join
    # shows as a faint line at fractional pixel ratios.
    size -= size % cells
    grid = [[rng.random() for _ in range(cells)] for _ in range(cells)]
    step = size / float(cells)

    def sample(gx, gy):
        x0 = int(gx) % cells
        y0 = int(gy) % cells
        x1 = (x0 + 1) % cells
        y1 = (y0 + 1) % cells
        fx = gx - int(gx)
        fy = gy - int(gy)
        top = grid[y0][x0] + (grid[y0][x1] - grid[y0][x0]) * fx
        bottom = grid[y1][x0] + (grid[y1][x1] - grid[y1][x0]) * fx
        return top + (bottom - top) * fy

    pixels = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            coarse = sample(x / step, y / step)
            # Fine grain on top of the broad undulation, so the texture still
            # has something to say at high zoom where the coarse layer is flat.
            grain = rng.random()
            level = 0.62 * coarse + 0.38 * grain
            # Still the top quarter of the range: this is a light modulation of
            # the land gradient, not camouflage.
            pixels[y * size + x] = 188 + int(level * 67.0)
    borrowed = QImage(bytes(pixels), size, size, size, QImage.Format_Grayscale8)
    tile = borrowed.copy().convertToFormat(QImage.Format_ARGB32)
    return QPixmap.fromImage(tile)


def pixel_ratio():
    """The device pixel ratio to build pixmaps for.

    ``BOP_DPR`` overrides it so a scaled display can be exercised on a machine
    that does not have one — the same escape hatch ``BOP_REDUCE_MOTION`` gives
    the animation code.
    """
    from PyQt5.QtWidgets import QApplication
    override = os.environ.get("BOP_DPR", "").strip()
    if override:
        try:
            return max(1.0, float(override))
        except ValueError:
            pass
    app = QApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def _smooth(source, width, height):
    """Scale a pixmap smoothly, and never ask for a zero-sized result."""
    return source.scaled(max(1, int(width)), max(1, int(height)),
                         Qt.KeepAspectRatio, Qt.SmoothTransformation)


#: The colour the black line art is redrawn in for this dark interface.
ICON_TINT = QColor("#ccd8e8")


def _readable_on_dark(source):
    """Return a copy of ``source`` that can actually be seen on dark chrome.

    The icon sheet is black line art drawn for the original's light Macintosh
    interface.  Dropped into this theme unchanged it is invisible: the map-mode
    buttons read as six shades of near-black, so the mode could only be chosen by
    clicking blindly.  A pixmap whose visible pixels are dark and colourless is
    recoloured (shape and alpha kept); one that already carries a readable colour
    -- the red star, the green heart -- is returned untouched, because flattening
    it would throw away the meaning.
    """
    image = source.toImage().convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    if width == 0 or height == 0:
        return source
    total = 0.0
    weight = 0
    colourful = 0
    # Every second pixel is enough to judge an icon and halves the start-up cost.
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 40:
                continue
            red, green, blue = pixel.red(), pixel.green(), pixel.blue()
            total += (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
            weight += 1
            if max(red, green, blue) - min(red, green, blue) > 70:
                colourful += 1
    if not weight:
        return source                    # an empty icon: nothing to recolour
    if total / weight > 0.75 or colourful > weight * 0.6:
        return source                    # light already, or genuinely coloured

    # Recolour pixel by pixel rather than in one pass over the whole pixmap: an
    # icon like the Capitol carries dark line art *and* a coloured flag, and a
    # blanket tint would flatten the part that carries the meaning.  Only the
    # dark, colourless pixels are lifted; the rest are left exactly as drawn.
    tinted = source.copy()
    image = tinted.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 40:
                continue
            red, green, blue = pixel.red(), pixel.green(), pixel.blue()
            luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
            if luminance >= 0.62 or max(red, green, blue) - min(red, green, blue) >= 70:
                continue
            image.setPixelColor(x, y, QColor(ICON_TINT.red(), ICON_TINT.green(),
                                             ICON_TINT.blue(), pixel.alpha()))
    return QPixmap.fromImage(image)


def _multi_size_icon(source):
    """A ``QIcon`` carrying every size the interface asks for.

    A one-pixmap icon makes Qt invent each requested size on the fly; giving it
    the sizes up front costs a few hundred kilobytes and removes the soft
    edges, which is all that can be done for 64x64 art without new artwork.
    """
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_smooth(source, size, size))
    return icon


class Graphics:
    """
    Loads the in-game graphics into the program memory. An object of this class
    is declared in the MainWindow main object.

    """
    def __init__(self):
        self.pixelRatio = pixel_ratio()
        #Program icon
        self.progIcon = QPixmap(Paths.image("icon175x175.png"))
        #Flags
        _img = QPixmap(Paths.image("flags.png"))
        self.flag = [QPixmap(_img.copy(37 * (i % 10), 22 * (i // 10), 36, 22)) for i in range(80)]
        #buffer the flags - used for showing them in system tooltips
        buffer = [QBuffer() for i in range(80)]
        for img,buf in zip(self.flag, buffer):
            buf.open(QIODevice.WriteOnly)
            # Smooth, because the default downscale of a 36x22 flag to 12 px
            # high is the nearest-neighbour kind, and a tooltip is small enough
            # that the aliasing is most of what the eye sees.
            img.scaledToHeight(12, Qt.SmoothTransformation).save(buf, "PNG", quality=100)
        self.flagToolTip = [bytes(i.data().toBase64()).decode() for i in buffer]
        self.emptyFlag = QPixmap(36,22)
        self.emptyFlag.fill(QColor(255,255,255,255))
        #: Size cache for :meth:`flagScaled`; the close-up shows a flag at
        #: 56x34, and letting a label scale the 36x22 original produced a
        #: nearest-neighbour edge that was the visible part of the blurriness.
        self._flagCache = {}

        # Action icons.  The sheet is black line art, so every icon is made
        # readable on the dark chrome before anything uses it.
        _img = QPixmap(Paths.image("icons.png"))
        self.iconArt = [_readable_on_dark(_img.copy(65 * (i % 10), 65 * (i // 10), 64, 64))
                        for i in range(30)]
        self.icon = [_multi_size_icon(art) for art in self.iconArt]

        # Advisors: one roster per side, historical photos when installed.
        self.advisorArt = [QPixmap(Paths.image("adv" + str(i + 1) + ".png")) for i in range(4)]
        self.historical_portraits = Advisors.portraits_installed()
        self.advisorSmall = {}
        self.advisorLarge = {}
        for side in (0, 1):
            small, large = [], []
            for index, advisor in enumerate(Advisors.roster(side)):
                path = advisor.portrait_path()
                # A modded roster may be longer than the four original stylised
                # portraits; reuse the art rather than crashing on startup.
                source = (QPixmap(path) if path
                          else self.advisorArt[index % len(self.advisorArt)])
                cover = bool(path)
                ring = ADVISOR_RINGS[index % len(ADVISOR_RINGS)]
                small.append(_card(source, SMALL_CARD[0], SMALL_CARD[1], ring, cover))
                large.append(_card(source, LARGE_CARD[0], LARGE_CARD[1], ring, cover))
            self.advisorSmall[side] = small
            self.advisorLarge[side] = large

        # Backwards-compatible aliases for the American roster.
        self.advisor = self.advisorSmall[0]

        # The backing bitmap.  It is no longer drawn as the map's base layer —
        # the scene paints the sea as a gradient and the land as vector shapes
        # (see MapView.MapScene) — but it remains the source of two things that
        # cannot be derived from the country outlines: its size, which fixes the
        # map's coordinate space, and its brightness, which becomes the relief
        # mask multiplied over the political fill.
        self.background = QPixmap(Paths.image("background.png"))
        self.mapSize = (self.background.width(), self.background.height())
        self.relief = _relief_mask(self.background.toImage())
        #: Terrain texture, generated at the device pixel ratio.
        self.terrainTile = relief_tile(TILE_SIZE, self.pixelRatio)

    # -- flags --------------------------------------------------------------

    def flagScaled(self, country_id, width, height):
        """A smoothly scaled flag, cached per size.

        Upscaling cannot add detail the 36x22 sheet does not have; it can stop
        the ugly stair-stepping a plain label scale produces.  Replacing the art
        with SVG or 2x PNGs is what would actually make flags sharp on HiDPI,
        and that needs artwork this checkout does not ship.
        """
        key = (country_id, int(width), int(height))
        cached = self._flagCache.get(key)
        if cached is None:
            source = self.flag[country_id] if 0 <= country_id < len(self.flag) else self.emptyFlag
            cached = _smooth(source, width, height)
            self._flagCache[key] = cached
        return cached

