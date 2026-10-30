from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QBoxLayout, QDialog, QGridLayout, QGroupBox, QLabel,
                             QTabWidget, QTextEdit, QWidget)

import Local
import Theme
from Charts import BarChart, LineChart
from Theme import Palette
from Widgets import FitScrollArea
from GameLogic.Globals import econConv, intvConv, mAidConv
from constants import *


def _tag(group, index):
    """``Local.strings[group][index]`` clamped into range.

    The close-up shows derived quantities (stability change, finlandization
    odds, ...) that the rules code does not promise to keep inside the label
    tables.  A value off the end of a table must show the nearest label, never
    raise out of a Qt slot and leave the dialog half filled.  Python's negative
    indexing would silently pick the wrong label, so that is clamped too.
    """
    table = Local.strings[group]
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    return table[max(0, min(len(table) - 1, index))]


def _parse(mode, value):
    """``Local.parseValue`` that never raises on an out-of-range value."""
    try:
        return Local.parseValue(mode, value)
    except (IndexError, KeyError, TypeError):
        pass
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""
    candidates = range(value - 1, -1, -1) if value > 0 else range(0, 40)
    for candidate in candidates:
        try:
            return Local.parseValue(mode, candidate)
        except (IndexError, KeyError, TypeError):
            continue
    return ""


def _fmt(value, mode):
    """``Local.formatValue`` that falls back to the bare number."""
    try:
        text = Local.formatValue(value, mode)
    except (IndexError, KeyError, TypeError):
        return str(value)
    # "$35 Ms" is jargon; the rest of the table says "million".
    return text.replace(" Ms", " million") if isinstance(text, str) else text


class SectionLabel(QLabel):
    """Small upper-case heading used inside the close-up tabs."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setFont(Theme.font(9, bold=True))
        self.setStyleSheet("color: %s; padding-top: 4px;" % Palette.ACCENT.name())


class BasicInfoTab(QWidget):
    """Everything the player can know about one country at a glance."""

    #: Index into ``WINDOW_INFO`` for each policy-table row.  Rows 0-11 are the
    #: original twelve; row 12 is trade policy, whose label was appended to the
    #: string table rather than inserted, so that nothing else shifts.
    ROW_LABEL = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 27)

    def __init__(self, parent):
        super(BasicInfoTab, self).__init__()
        self.parent = parent

        root = QBoxLayout(QBoxLayout.TopToBottom)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # --- header: flag + identity -------------------------------------
        header = QBoxLayout(QBoxLayout.LeftToRight)
        self.flag = QLabel()
        self.flag.setFixedSize(56, 34)
        self.flag.setScaledContents(True)
        self.title = QLabel()
        self.title.setFont(Theme.font(16, bold=True))
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        titleCol = QBoxLayout(QBoxLayout.TopToBottom)
        titleCol.addWidget(self.title)
        titleCol.addWidget(self.subtitle)
        header.addWidget(self.flag)
        header.addSpacing(10)
        header.addLayout(titleCol)
        header.addStretch(1)
        self.insurgents = QLabel()
        self.insurgents.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.insurgents.setStyleSheet("color: %s;" % Palette.WARN.name())
        header.addWidget(self.insurgents)
        root.addLayout(header)

        # --- status strip -------------------------------------------------
        self.statusStrip = QBoxLayout(QBoxLayout.LeftToRight)
        self.statusValues = {}
        for key, caption in (("insurgency", 12), ("stability", 16), ("military", 14),
                             ("sphere", 15), ("pressure", 8)):
            box = QGroupBox(Local.strings[Local.WINDOW_INFO][caption])
            box.setFont(Theme.font(8, bold=True))
            inner = QBoxLayout(QBoxLayout.TopToBottom)
            value = QLabel("-")
            value.setAlignment(Qt.AlignCenter)
            value.setFont(Theme.font(11, bold=True))
            pace = QLabel("")
            pace.setAlignment(Qt.AlignCenter)
            pace.setFont(Theme.font(8))
            pace.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
            inner.addWidget(value)
            inner.addWidget(pace)
            box.setLayout(inner)
            self.statusStrip.addWidget(box, 1)
            self.statusValues[key] = (value, pace)
        root.addLayout(self.statusStrip)

        # --- policy table -------------------------------------------------
        self.policyGroup = QGroupBox()
        policyLayout = QGridLayout()
        policyLayout.setHorizontalSpacing(14)
        policyLayout.setVerticalSpacing(3)
        self.policyHeader = [QLabel() for _ in range(4)]
        for column, header in enumerate(self.policyHeader):
            header.setFont(Theme.font(9, bold=True))
            header.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
            policyLayout.addWidget(header, 0, column)
        self.paramName = []
        self.usaValue = []
        self.ussrValue = []
        # 12 rows for the levels that predate trade policy; the Multipolar level
        # adds a thirteenth for it (CLOSE_UP_AVL_DATA).
        self.rowCount = 13
        for row in range(self.rowCount):
            name = QLabel()
            name.setStyleSheet("color: %s;" % Palette.TEXT.name())
            left = QLabel()
            right = QLabel()
            for label in (left, right):
                label.setFont(Theme.font(10, mono=True))
            policyLayout.addWidget(name, row + 1, 0)
            policyLayout.addWidget(left, row + 1, 1)
            policyLayout.addWidget(right, row + 1, 2)
            self.paramName.append(name)
            self.usaValue.append(left)
            self.ussrValue.append(right)
        self.totalHeader = QLabel()
        policyLayout.addWidget(self.totalHeader, 0, 3)
        self.totalValues = []
        for row in range(10):
            label = QLabel()
            label.setFont(Theme.font(10, mono=True))
            policyLayout.addWidget(label, row + 1, 3)
            self.totalValues.append(label)
        self.policyGroup.setLayout(policyLayout)
        root.addWidget(self.policyGroup)
        # What the braces mean: the original showed them without a word of
        # explanation, and "{$0 million}" reads as a data error.
        self.braceNote = QLabel(
            "{ } = already at the most you can give at present "
            "(limited by your budget or by the rules); \u25b2 \u25bc = changed since last year.")
        self.braceNote.setWordWrap(True)
        self.braceNote.setStyleSheet("color: %s;" % Palette.TEXT_DIM.name())
        self.braceNote.setFont(Theme.font(8))
        root.addWidget(self.braceNote)
        self.policyGroup.setToolTip(
            "Braces { } mean the value is already at the maximum currently possible.")

        # --- local news ---------------------------------------------------
        self.localNewsGroup = QGroupBox()
        newsLayout = QBoxLayout(QBoxLayout.LeftToRight)
        self.localNewsLabel = QTextEdit()
        self.localNewsLabel.setReadOnly(True)
        self.localNewsLabel.setMinimumHeight(90)
        newsLayout.addWidget(self.localNewsLabel)
        self.localNewsGroup.setLayout(newsLayout)
        root.addWidget(self.localNewsGroup, 1)

        self.setLayout(root)

    # -- data ---------------------------------------------------------------

    def loadCountry(self, world, country):
        c = country
        # Smooth-scaled rather than handed to the label raw: the sheet holds
        # 36x22 flags and this header shows them at 56x34, and a plain upscale
        # of that is what reads as blurry.  Only new artwork — SVG or a 2x
        # sheet — can actually make it sharp (F3).
        self.flag.setPixmap(self.parent.graphics.flagScaled(c.id, 56, 34))
        self.title.setText(Local.strings[Local.DATA_COUNTRIES + c.id][Local.CTRY_NAME])
        capital = Local.strings[Local.DATA_COUNTRIES + c.id][Local.CTRY_CAPITAL]
        leader = c.leaderName or Local.strings[Local.DATA_COUNTRIES + c.id][Local.CTRY_LEADER_NAME]
        title = Local.strings[Local.DATA_COUNTRIES + c.id][Local.CTRY_LEADER_TITLE]
        self.subtitle.setText("%s \u2014 %s %s" % (capital, title, leader))
        self.insurgents.setText(c.getInsurgentsName())

        # status strip
        insurgency = self.statusValues["insurgency"]
        insurgency[0].setText(_tag(Local.TAG_INSURGENCY, c.getInsurgency()))
        insurgency[1].setText(_tag(Local.TAG_INSG_PACE, c.getInsurgencyChange()))
        stability = self.statusValues["stability"]
        stability[0].setText(_tag(Local.TAG_COUP_CHANCE, c.getGovtStability()))
        stability[1].setText(_tag(Local.TAG_COUP_PACE, c.getGovtStabilityChange()))
        self.statusValues["military"][0].setText(_tag(Local.TAG_STREMGTH, c.getMilPower()))
        self.statusValues["military"][1].setText(_tag(Local.TAG_IDEOLOGY, c.getIdeology("govt")))
        self.statusValues["sphere"][0].setText(_tag(Local.TAG_SPHERE, c.getSphOfInfluence(world)))
        self.statusValues["sphere"][1].setText("")
        self.statusValues["pressure"][0].setText(str(c.milPressure))
        self.statusValues["pressure"][1].setText(_tag(Local.TAG_COUP_CHANCE, c.getGovtStability()))

        for group in (self.policyGroup, self.localNewsGroup):
            group.setTitle("")

        if c.id < 2:
            self._load_superpower(world, c)
        else:
            self._load_minor(world, c)

        self.localNewsLabel.setText(c.localNews)

    def _load_superpower(self, world, c):
        visible = CLOSE_UP_SUPERPWR[world.level - 1]
        self.policyHeader[0].setText("")
        self.policyHeader[1].setText(Local.strings[Local.WINDOW_INFO][23])
        self.policyHeader[2].setText(Local.strings[Local.WINDOW_INFO][24])
        self.policyHeader[3].setText("")
        self.totalHeader.setText("")
        sumAidG = sum(mAidConv(i) for i in c.govtAid[2:])
        sumAidI = sum(mAidConv(i) for i in c.insgAid[2:])
        sumIntvG = sum(intvConv(i) for i in c.govtIntv[2:])
        sumIntvI = sum(intvConv(i) for i in c.insgIntv[2:])
        sumEconAid = sum(econConv(i) for i in c.econAid[2:])
        for i in range(self.rowCount):
            if i not in visible:
                self.paramName[i].setText("")
                self.usaValue[i].setText("")
                self.ussrValue[i].setText("")
                continue
            self.paramName[i].setText(Local.strings[Local.WINDOW_INFO][self.ROW_LABEL[i]])
            if i == 2:
                self.usaValue[i].setText(_fmt(2 * sumAidG, 2))
                self.ussrValue[i].setText(_fmt(c.getAvailableAid(), 2))
            elif i == 3:
                self.usaValue[i].setText(_fmt(2 * sumAidI, 3))
                self.ussrValue[i].setText(_fmt(c.getAvailableAid(), 3))
            elif i == 4:
                self.usaValue[i].setText(_fmt(sumIntvG, 4))
                self.ussrValue[i].setText(_fmt(c.getAvailableMen(), 4))
            elif i == 5:
                self.usaValue[i].setText(_fmt(sumIntvI, 5))
                self.ussrValue[i].setText(_fmt(c.getAvailableMen(), 5))
            elif i == 6:
                self.usaValue[i].setText(_fmt(2 * sumEconAid, 6))
                self.ussrValue[i].setText(_fmt((c.GNP // 44) - 2 * sumEconAid, 6))
            else:
                self.usaValue[i].setText("")
                self.ussrValue[i].setText("")
        for i in range(10):
            self.totalValues[i].setText("")

    def _load_minor(self, world, c):
        for header in self.policyHeader:
            header.setText("")
        self.policyHeader[1].setText(Local.strings[Local.WINDOW_INFO][20])
        self.policyHeader[2].setText(Local.strings[Local.WINDOW_INFO][21])
        self.totalHeader.setText(Local.strings[Local.WINDOW_INFO][22])
        visible = CLOSE_UP_AVL_DATA[world.level - 1]
        values = [[], []]
        for s in world.country[:2]:
            s.setMaxPolicy()
            for m in range(self.rowCount):
                if m not in visible:
                    values[s.id].append("")
                    continue
                labelType, val, old, maxNum, maxVal = c.getCloseUpInfoValue(world, s, m)
                if m == 1:
                    values[s.id].append(str(val))
                    continue
                text = ""
                if 2 <= m <= 9 or m == 12:
                    if old > val:
                        text += "\u25bc "
                    elif old < val:
                        text += "\u25b2 "
                text += _parse(labelType, val)
                if maxVal == val and m not in (0,):
                    text = "{" + text + "}"
                values[s.id].append(text)
        for i in range(self.rowCount):
            if i not in visible:
                self.paramName[i].setText("")
            else:
                self.paramName[i].setText(Local.strings[Local.WINDOW_INFO][self.ROW_LABEL[i]])
            self.usaValue[i].setText(values[0][i])
            self.ussrValue[i].setText(values[1][i])

        self.totalValues[1].setText(str(c.prestigeVal // 8))  # a score, not money
        for i in range(2, 6):
            if i == 2:
                val = sum(mAidConv(k.govtAid[c.id]) * 2 for k in world.country)
            elif i == 3:
                val = sum(mAidConv(k.insgAid[c.id]) * 2 for k in world.country)
            elif i == 4:
                val = sum(intvConv(k.govtIntv[c.id]) for k in world.country)
            else:
                val = sum(intvConv(k.insgIntv[c.id]) for k in world.country)
            self.totalValues[i].setText(_fmt(val, i))

    def setStrings(self):
        self.policyGroup.setTitle(Local.strings[Local.WINDOW_INFO][26])
        self.localNewsGroup.setTitle(Local.strings[Local.LOCAL_NEWS][0])
        # Labels come from the current world's level, which is not known until a
        # country is loaded; the per-row labels are set in loadCountry.


class HistoryTab(QWidget):
    """Nine trend charts, mirroring the original history screen."""

    #: (chart index, legend captions, forced value range)
    LAYOUT = (
        (4, "Military and Insurgency Aid", None),
        (2, "Government Stability", (0, 20)),
        (2, "Finlandization Likelihood", (0, 128)),
        (1, "Insurgency", (0, 80)),
        (4, "Economic Aid and Stability", None),
        (4, "Treaties and Diplomatic Pressure", None),
        (1, "Military and Insurgency Intervene", None),
        (2, "Diplomatic Relationships", (-127, 127)),
        (1, "Internal Pressure on Security", (0, 336)),
    )
    #: Which chart in the grid each data set belongs to (original ordering).
    ORDER = (0, 3, 6, 7, 8, 1, 4, 2, 5)

    #: Which charts a given difficulty actually has anything to put in.  The
    #: original drew 12, 17 or 23 history panels depending on the level
    #: (``CASE Level OF 1: j:=12; 2: j:=17; 3,4: j:=23;``); this remake draws a
    #: fixed set of nine series and gates some of them by level instead, which is
    #: the same idea at a smaller scale.  Hiding the empty frames matters more
    #: than the exact count: a Beginner was being shown four blank panels and
    #: told nothing by them.
    MIN_LEVEL = {1: 2, 2: 3, 4: 2, 5: 2}

    def __init__(self, parent):
        super(HistoryTab, self).__init__()
        self.parent = parent
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        self.charts = []
        for slot in range(9):
            chart = LineChart([[]])
            chart.setMinimumSize(200, 130)
            self.charts.append(chart)
        self.setLayout(self.grid)
        self._level = None
        self._layoutFor(1)

    def _visibleSlots(self, level):
        """The chart indices to display at this difficulty, in display order."""
        return [i for i in self.ORDER
                if level >= self.MIN_LEVEL.get(i, 1)]

    def _layoutFor(self, level):
        """Place exactly the charts this level has data for."""
        if level == self._level:
            return
        self._level = level
        while self.grid.count():
            self.grid.takeAt(0)
        for chart in self.charts:
            chart.hide()
        slots = self._visibleSlots(level)
        columns = 3 if len(slots) > 4 else 2
        for position, index in enumerate(slots):
            chart = self.charts[index]
            chart.show()
            self.grid.addWidget(chart, position // columns, position % columns)

    def loadCountry(self, level, cHistory):
        self._layoutFor(level)
        charts = self.charts
        charts[0].setData(cHistory.sqrtStrength)
        charts[3].setData(cHistory.govtAid + cHistory.insgAid)
        charts[6].setData(cHistory.govtIntv + cHistory.insgIntv)
        charts[7].setData(cHistory.diplOpinion)
        charts[8].setData(cHistory.milPressure)
        charts[1].setData(cHistory.govtPopul if level > 1 else [[]])
        charts[4].setData((cHistory.econAid + cHistory.destab) if level > 1 else [[]])
        charts[2].setData(cHistory.finlProb if level > 2 else [[]])
        charts[5].setData((cHistory.treaty + cHistory.trade + cHistory.pressure)
                          if level > 2 else [[]])
        # one history point per year, as on the Economy tab
        points = max([len(s) for s in cHistory.sqrtStrength] + [0])
        years = ["'%d" % (GAME_BASE_YEAR + i) for i in range(points)]
        for chart in charts:
            chart.setCategories(years)

    def setStrings(self):
        captions = Local.strings[Local.WINDOW_HISTORY]
        for i in range(9):
            if i < len(captions):
                self.charts[i].setTitle(captions[i])
        legends = Local.strings[Local.WINDOW_HISTORY_LEGEND]
        for index in (3, 4, 6):
            self.charts[index].setLegend(legends[:4])
        self.charts[5].setLegend(legends[5:11])
        for index in (7, 2):
            self.charts[index].setLegend((legends[0], legends[1]))
        for index in (0, 1, 8):
            self.charts[index].setLegend(())


class EconomyTab(QWidget):
    """Sector composition and the historical GNP series."""

    def __init__(self, parent):
        super(EconomyTab, self).__init__()
        self.parent = parent
        root = QBoxLayout(QBoxLayout.TopToBottom)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QBoxLayout(QBoxLayout.LeftToRight)
        self.sectorGroup = QGroupBox()
        sectorLayout = QBoxLayout(QBoxLayout.LeftToRight)
        self.sectorChart = BarChart([[[], [], []]], BarChart.PERCENT_CHART)
        self.sectorChart.setMinimumSize(260, 180)
        self.sectorLegend = QLabel()
        self.sectorLegend.setWordWrap(True)
        sectorLayout.addWidget(self.sectorChart)
        sectorLayout.addWidget(self.sectorLegend)
        self.sectorGroup.setLayout(sectorLayout)
        top.addWidget(self.sectorGroup, 3)

        self.tableGroup = QGroupBox()
        tableLayout = QGridLayout()
        tableLayout.setHorizontalSpacing(18)
        self.gnpRows = []
        for row in range(5):
            caption = QLabel()
            caption.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
            current = QLabel()
            current.setFont(Theme.font(10, mono=True))
            share = QLabel()
            share.setFont(Theme.font(10, mono=True))
            share.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
            tableLayout.addWidget(caption, row, 0)
            tableLayout.addWidget(current, row, 1)
            tableLayout.addWidget(share, row, 2)
            self.gnpRows.append((caption, current, share))
        self.tableGroup.setLayout(tableLayout)
        top.addWidget(self.tableGroup, 2)
        root.addLayout(top)

        bottom = QBoxLayout(QBoxLayout.LeftToRight)
        self.gnpChart = LineChart([[]])
        self.gnpCapChart = LineChart([[]])
        for chart in (self.gnpChart, self.gnpCapChart):
            chart.setMinimumHeight(170)
            bottom.addWidget(chart, 1)
        root.addLayout(bottom, 1)

        self.setLayout(root)

    def loadCountry(self, world, country):
        history = country.history
        self.sectorChart.setData(history.gnpFrac if history.gnpFrac[0] else [[], [], []])
        sectors = (Local.strings[Local.WINDOW_ECONOMY][0],
                   Local.strings[Local.WINDOW_ECONOMY][1],
                   Local.strings[Local.WINDOW_ECONOMY][2])
        self.sectorChart.setLegend(sectors)
        self.sectorLegend.setText(
            "<br>".join("<b>%s</b> %.1f%%" % (name, 100.0 * country.gnpFrac[i] / 255.0)
                        for i, name in enumerate(sectors)))

        total = country.getNominalGNP(3)
        self.gnpRows[0][1].setText(_fmt(country.getNominalGNP(0), 11))
        self.gnpRows[1][1].setText(_fmt(country.getNominalGNP(1), 11))
        self.gnpRows[2][1].setText(_fmt(country.getNominalGNP(2), 11))
        self.gnpRows[3][1].setText(_fmt(total, 11))
        self.gnpRows[4][1].setText(_fmt(country.getGNPpcap(3), 12))
        for i in range(3):
            self.gnpRows[i][2].setText("{:.1%}".format(country.gnpFrac[i] / 255.0))
        self.gnpRows[3][2].setText("")
        self.gnpRows[4][2].setText("")

        self.gnpChart.setData(history.GNP)
        self.gnpCapChart.setData(history.GNPcap)
        # one history point per year, starting with the opening position
        points = max([len(s) for s in history.GNP] + [0])
        years = ["'%d" % (GAME_BASE_YEAR + i) for i in range(points)]
        for chart in (self.sectorChart, self.gnpChart, self.gnpCapChart):
            chart.setCategories(years)

    def setStrings(self):
        strings = Local.strings[Local.WINDOW_ECONOMY]
        self.sectorGroup.setTitle(strings[8])
        self.tableGroup.setTitle(strings[14])
        self.gnpChart.setTitle(strings[10])
        self.gnpCapChart.setTitle(strings[11])
        # rows: Consumer, Investment, Military, Total, per capita
        for index, caption in enumerate(strings[0:4] + [strings[5]]):
            if index < len(self.gnpRows):
                self.gnpRows[index][0].setText(caption)
        self._sectorLabels = (strings[0], strings[1], strings[2])


class CloseUpWindow(QDialog):
    """
    The main Close-Up class. Consists of QTabWidget with three tabs
    - basic info tab, history tab and economy tab.
    All child tab data updates are called from within this object.

    """

    def __init__(self, parent):
        super(CloseUpWindow, self).__init__(parent)
        self.parent = parent
        self.basicInfoTab = BasicInfoTab(parent)
        self.historyTab = HistoryTab(parent)
        self.economyTab = EconomyTab(parent)
        self.tabWidget = QTabWidget()
        # Each tab scrolls: the close-up is taller than a 1366x768 laptop screen.
        self.tabWidget.addTab(FitScrollArea(self.basicInfoTab), "")
        self.tabWidget.addTab(FitScrollArea(self.historyTab), "")
        self.tabWidget.addTab(FitScrollArea(self.economyTab), "")
        mainLayout = QBoxLayout(QBoxLayout.TopToBottom)
        mainLayout.setContentsMargins(8, 8, 8, 8)
        mainLayout.addWidget(self.tabWidget)
        self.setLayout(mainLayout)
        self.setMinimumSize(640, 420)
        self.resize(860, 620)
        self.setModal(True)
        self.setStrings()

    def loadCountry(self, country):
        self.setWindowTitle(Local.strings[Local.DATA_COUNTRIES + country.id][Local.CTRY_NAME] + " - " + \
            Local.strings[Local.MAIN_PANEL][12])
        self.basicInfoTab.loadCountry(country.parent, country)
        self.historyTab.loadCountry(self.parent.world.level, country.history)
        self.economyTab.loadCountry(country.parent, country)
        self.setVisible(True)

    def setStrings(self):
        self.basicInfoTab.setStrings()
        self.historyTab.setStrings()
        self.economyTab.setStrings()
        self.tabWidget.setTabText(0, Local.strings[Local.WINDOW_INFO][26])
        self.tabWidget.setTabText(1, Local.strings[Local.WINDOW_HISTORY_LEGEND][4])
        self.tabWidget.setTabText(2, Local.strings[Local.WINDOW_ECONOMY][14])
