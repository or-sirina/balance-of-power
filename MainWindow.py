"""
The main window: it owns the world, the widgets, and the turn loop.

Three ways to play
------------------
``offline, one player``
    The classic game: the player takes one superpower, the computer the other.
``offline, two players``
    Hot-seat on one machine, with the new head-to-head crisis ladder so that
    the two sides can actually challenge each other.
``networked``
    One machine hosts authoritatively and mirrors the world to the other.  Both
    sides are human, so the crisis ladder is used there as well.

Anything that changes the world goes through :meth:`MainWindow.request_policy`
and :meth:`MainWindow.request_end_turn`; those decide whether to apply the
change locally or to forward it to the host over the network.
"""

import html
import json
import os
import pickle

from PyQt5.QtCore import QEventLoop, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox

import Local
import Paths
import Music
import Sound
import Theme
from ControlPanel import ControlPanel
from Dialog.CloseUpWindow import CloseUpWindow
from Dialog.CrisisWindow import CrisisWindow
from Dialog.ObjectivesBar import ObjectivesBar
from Dialog.LostGameWindow import LostGameWindow
from Dialog.MultiplayerWindow import MultiplayerWindow
from Dialog.NewGameWindow import NewGameWindow
from Dialog.NewsWindow import NewsWindow
from Dialog.PolicyWindow import PolicyWindow
from Dialog.ScoresWindow import ScoresWindow
from Async import run_blocking
from GameLogic.CrisisDuel import (CrisisDuel, CrisisPrompt, contestable_news)
from GameLogic.LLMClient import LLMConfig
from GameLogic.LLMOpponent import LLMOpponent
from GameLogic.CrisisHandler import reactNews
from GameLogic.MovePlanner import continueNextTurn, mainMove, prePlanMove
from GameLogic import Objectives
from GameLogic.AdvisorChat import set_ai_advisors
from GameLogic.World import World
from GraphicsLoader import Graphics
from MapView import MapView
from Menu import Menu
from Net import apply_state, world_to_state
from Net.Protocol import Action
from Net.Session import Session
from StatusBar import StatusBar
from Theme import Palette
from Widgets import ScreenFitFilter
from constants import (DEFAULT_OPTS, INAVL_MAP_MODES, LEVEL_LLM, MAP_MODE_COUNT)

#: What the player is told when the autosave (or a slot) cannot be read.
_UNREADABLE_SAVE = ("That saved game could not be read. It may be from a "
                    "different version of the game, or damaged.")


def _pickle_atomically(obj, path):
    """Pickle ``obj`` to ``path`` so that a failure leaves the old file intact.

    The bytes go to a temporary file in the same folder, are flushed to disk and
    then renamed over the destination; the rename is retried briefly because
    Windows, OneDrive and virus scanners hold files open for a moment.
    """
    import tempfile
    from Net.GameFile import _replace_with_retry
    directory = os.path.dirname(os.path.abspath(path))
    handle = temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".bop-save-", suffix=".part",
                                         dir=directory)
        handle = os.fdopen(fd, "wb")
        pickle.dump(obj, handle)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass        # some network drives refuse fsync; the rename still orders
        handle.close()
        handle = None
        _replace_with_retry(temporary, path)
        temporary = None
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if temporary is not None:
            try:
                os.remove(temporary)
            except OSError:
                pass


class MainWindow(QMainWindow):

    def __init__(self, parent=None):
        super(MainWindow, self).__init__()
        self.graphics = Graphics()
        self.parent = parent

        # --- networking state ------------------------------------------
        self.session = None
        self.local_side = 0
        self.last_port = 45454
        self.last_level = 4
        self.pending_end = set()
        #: True once a play-by-mail game has been opened/created/loaded in the
        #: lobby dialog.  The opponent is not at this keyboard, so crises that
        #: they could contest are not put to a duel (see ``resolve_turn``).
        self._mail_mode = False
        #: Set when a position has just been loaded; see ``_resume_load_state``.
        self._resume_pending = False
        #: Why the last ``loadWorld`` found nothing to load ("" if it did not fail).
        self.load_error = ""
        self.duel = None
        self.crisis_queue = []
        self.crisis_pending = False
        #: "Undo last turn": the world as it stood at the start of the previous
        #: turn, plus the flag that makes it a once-per-turn affair.
        self.turn_start_state = None
        self.undo_state = None
        self.undo_used = False
        # --- language-model opponent (fifth difficulty level) ----------
        self.llm_config = LLMConfig()
        self.llm_opponent = None
        #: The advisors' chat client, one per game so the call budget is real.
        self._advisor_client = None
        #: Recent plans, newest last: (year, reasoning, actions).
        self.llm_log = []
        self.llm_settingsWindow = None
        self.advisorChatWindow = None
        self.opponentLogWindow = None
        self.helpWindow = None
        self.multiplayerWindow = None
        #: The start screen, when one was shown (see Dialog/StartWindow.py).
        self.startWindow = None
        self.saveSlotsWindow = None
        #: True while the host is resolving a turn; nobody may end a turn then.
        self.resolving = False
        #: Turns this host has completed, replicated so the guest can tell when
        #: its end-turn request has been consumed.
        self.turn_counter = 0
        self.remote_turn = -1
        #: Rolling log of the turn handshake, for diagnosing stalls.
        self.netlog = []

        self.world = World(4, False, 0)
        self.setStyleSheet("QMainWindow::separator { width: 0px; height: 0px; }")
        self.setWindowTitle("Balance of Power")
        self.setWindowIcon(QIcon(self.graphics.progIcon))
        # Every dialog and window is clamped to the screen when it is shown
        # (lab PCs: 1366x768 at 125-150%, ~1090x570 usable logical pixels).
        self._screenFit = ScreenFitFilter(self)
        QApplication.instance().installEventFilter(self._screenFit)
        self.setMinimumSize(960, 520)

        # --- widgets ----------------------------------------------------
        # Construction order matters: the map view wires its context menu to
        # the policy window, and the menu reads the control panel's actions.
        self.statusBarWidget = StatusBar(self)
        self.objectivesBar = ObjectivesBar(self)
        self.policyWindow = PolicyWindow(self)
        self.mapView = MapView(self, self.world)
        self.mapView.setAlignment(Qt.AlignCenter)
        self.controlPanel = ControlPanel(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.controlPanel)
        self.addDockWidget(Qt.TopDockWidgetArea, self.statusBarWidget)
        self.addDockWidget(Qt.TopDockWidgetArea, self.objectivesBar)
        # Stacked, not side by side: sharing one row with the status bar left
        # the objective chips about 55 px each ("All..", "Th..").
        self.splitDockWidget(self.statusBarWidget, self.objectivesBar, Qt.Vertical)
        self.setCentralWidget(self.mapView)

        self.newGameWindow = NewGameWindow(self)
        self.newsWindow = NewsWindow(self)
        self.closeUpWindow = CloseUpWindow(self)
        self.scoresWindow = ScoresWindow(self)
        self.lostGameWindow = LostGameWindow(self)
        self.crisisWindow = CrisisWindow(self)
        self.crisisWindow.decided.connect(self.on_crisis_decision)
        self.controlPanel.connectActions()
        self.menu = Menu(self)
        self.setMenuBar(self.menu)
        self.menu.buildAssistantMenu(self)

        self.loadOptions()
        self.mapView.resetMapView()
        #: Whether the autosave was restored; if not, ``world`` is an unstarted
        #: placeholder until a game is started (see ``main.main``).
        self.restored = self.loadWorld()
        self.refresh_ui()

    @property
    def mail_mode(self):
        return self._mail_mode

    @mail_mode.setter
    def mail_mode(self, value):
        """A play-by-mail game has two human players, whatever it started as.

        The lobby may open a mailbox over a game that began as a one-player one
        (``twoPFlag`` False).  Left like that, the turn went through the
        computer-opponent path: the AI moved for the absent player and the
        mover was asked to answer a crisis prompt for every move of theirs.
        """
        self._mail_mode = bool(value)
        world = getattr(self, "world", None)
        if self._mail_mode and world is not None and not world.twoPFlag:
            world.twoPFlag = True
            self.llm_opponent = None

    # ------------------------------------------------------------------
    # Options and persistence
    # ------------------------------------------------------------------

    def loadOptions(self):
        try:
            with open(Paths.user_file("options.dat"), "r", encoding="utf-8") as f:
                options = json.load(f)
            if len(options) < 7:
                options = list(DEFAULT_OPTS)
        except (OSError, ValueError):
            options = list(DEFAULT_OPTS)
        for i, j in zip(options[:3], self.menu.options[:3]):
            j.setChecked(bool(i))
        # Index 7 (if present) is the reduce-motion setting.
        reduce_motion = bool(options[7]) if len(options) > 7 else False
        self.menu.options[4].setChecked(reduce_motion)
        Theme.set_motion_enabled(not reduce_motion)
        # Indices 8 and 9 are the graphics switches, added with the graphics
        # pass.  Default on: they are improvements, and both are reversible.
        relief = bool(options[8]) if len(options) > 8 else True
        sound = bool(options[9]) if len(options) > 9 else True
        self.menu.options[5].setChecked(relief)
        self.menu.options[6].setChecked(sound)
        self.mapView.setReliefEnabled(relief)
        Sound.set_enabled(sound)
        colour_blind = bool(options[10]) if len(options) > 10 else False
        self.menu.options[7].setChecked(colour_blind)
        self.mapView.setColourBlind(colour_blind)
        # Which advisory system is in play.  Default on, because the AI advisors
        # are the point of the feature, and because the setting is honest about
        # itself: with no key the historical bench answers regardless.
        ai_advisors = bool(options[11]) if len(options) > 11 else True
        self.menu.options[8].setChecked(ai_advisors)
        set_ai_advisors(ai_advisors)
        # Music: on by default, at a volume that sits under a conversation.  The
        # built-in themes are generated in the background the first time, so the
        # playlist may be empty here; the callback starts playback the moment
        # the first track exists.
        music_on = bool(options[12]) if len(options) > 12 else True
        music_volume = self._nearest_volume(
            int(options[13]) if len(options) > 13 else 50)
        self.menu.options[9].setChecked(music_on)
        action = self.menu.musicVolumeAction.get(music_volume)
        if action is not None:
            action.setChecked(True)
        Music.set_volume(music_volume)
        Music.set_enabled(music_on)
        # Generation starts only once the window has actually painted.  Doing it
        # during construction cost the first frame a second of wall time: the
        # renderer is pure Python, so its worker holds the interpreter and the
        # interface waits its turn.  Measured, the difference is 1280 ms against
        # 52 ms for the first paint.
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1500, self._start_music_if_needed)
        if not Music.available():
            # Nothing to control on a machine with no audio output; say so on
            # the entries rather than leaving two switches that do nothing.
            self.menu.options[9].setEnabled(False)
            self.menu.options[9].setToolTip(Music.status_note())
            self.menu.musicVolumeMenu.setEnabled(False)
            self.menu.musicVolumeMenu.setToolTip(Music.status_note())
        # Guard the stored indices: an options file from an older build can name
        # a difficulty that no longer exists.
        self._check_option(self.newGameWindow.levelOpt, options[4])
        self._check_option(self.newGameWindow.modeOpt, options[5])
        self._check_option(self.newGameWindow.sideOpt, options[6])
        language = options[3]
        if language in self.menu.languages:
            self.menu.languages[language].setChecked(True)

    @staticmethod
    def _check_option(buttons, index):
        try:
            buttons[int(index)].setChecked(True)
        except (IndexError, TypeError, ValueError):
            buttons[0].setChecked(True)

    def saveOptions(self):
        options = [i.isChecked() for i in self.menu.options[:3]]
        for name, action in self.menu.languages.items():
            if action.isChecked():
                options.append(name)
                break
        else:
            options.append("english.json")
        options += [i.checkedId() for i in self.newGameWindow.buttonGroups]
        options.append(bool(self.menu.options[4].isChecked()))
        options.append(bool(self.menu.options[5].isChecked()))
        options.append(bool(self.menu.options[6].isChecked()))
        options.append(bool(self.menu.options[7].isChecked()))
        options.append(bool(self.menu.options[8].isChecked()))
        options.append(bool(self.menu.options[9].isChecked()))
        for level, action in self.menu.musicVolumeAction.items():
            if action.isChecked():
                options.append(int(level))
                break
        else:
            options.append(Music.volume())
        try:
            with open(Paths.user_file("options.dat"), "w", encoding="utf-8") as f:
                json.dump(options, f)
        except OSError:
            pass

    def saveWorld(self, manual=False):
        """Pickle the current world so the next launch resumes it."""
        if not manual and (self.world.NWFlag or self.world.ANWFlag):
            return      # never autosave a world that has ended in nuclear war
        net = self.net
        if net is not None and net.is_client:
            # The guest's copy is a mirror; saving it would be misleading.
            if manual:
                QMessageBox.information(self, Local.strings[Local.MENU][61],
                                        Local.strings[Local.MENU][70])
            return
        try:
            _pickle_atomically(self.world, Paths.user_file("save.dat"))
            if manual:
                QMessageBox.information(self, Local.strings[Local.MENU][61],
                                        Local.strings[Local.MENU][70])
        except Exception:
            if manual:
                QMessageBox.critical(self, Local.strings[Local.MENU][61],
                                     Local.strings[Local.MENU][71])

    def saveWorldTo(self, path):
        """Write the world to a named slot, with its sidecar."""
        world = self.world
        self.last_save_error = ""
        try:
            _pickle_atomically(world, path)
        except Exception as exc:
            self.last_save_error = str(exc) or type(exc).__name__
            return False
        from Dialog.SaveSlotsWindow import write_meta
        write_meta(os.path.basename(path)[:-len(".bop")], world)
        return True

    def loadWorldFrom(self, path):
        """Restore a named slot, keeping the map polygons."""
        try:
            with open(path, "rb") as handle:
                saved = pickle.load(handle)
        except Exception:
            return False
        try:
            self.leave_session()
            self.setWorld(saved)
            self.setup_llm_opponent(saved.level)
            self.reset_undo_history()
            self.setStatus(-1)
            self.refresh_ui()
            self.check_game_over()
            self._resume_load_state()
            return True
        except Exception:
            return False

    def open_help(self):
        from Dialog.HelpWindow import HelpWindow
        if self.helpWindow is None:
            self.helpWindow = HelpWindow(self)
        self.helpWindow.show()
        self.helpWindow.raise_()

    def open_save_slots(self, mode="both"):
        """Show the slot manager.

        Deliberately ``show()`` rather than ``exec_()``: nothing here demands an
        answer before the rest of the program can continue, and a modal nested
        event loop is exactly what makes a window impossible to script or to
        leave open while you look at the map behind it.
        """
        from Dialog.SaveSlotsWindow import SaveSlotsWindow
        if self.saveSlotsWindow is None:
            self.saveSlotsWindow = SaveSlotsWindow(self, mode)
        else:
            self.saveSlotsWindow.mode = mode
            self.saveSlotsWindow.refresh()
        self.saveSlotsWindow.show()
        self.saveSlotsWindow.raise_()
        return self.saveSlotsWindow

    def loadWorld(self):
        """Restore the autosave, if there is one.

        Returns True when a game was restored.  ``load_error`` says why not when
        a save exists but cannot be used, so the start screen can tell the
        player instead of quietly leaving them in a fresh game.
        """
        self.load_error = ""
        try:
            with open(Paths.user_file("save.dat"), "rb") as f:
                saved = pickle.load(f)
        except FileNotFoundError:
            return False
        except Exception:
            self.load_error = _UNREADABLE_SAVE
            return False
        try:
            # The same steps as loading a slot: a level-5 game needs its model
            # opponent back, and the advisors' client belongs to the old game.
            self.leave_session()
            self.setWorld(saved)
            self.setup_llm_opponent(saved.level)
            self.reset_undo_history()
            self.setStatus(-1)
            self.refresh_ui()
            self._resume_load_state()
            return True
        except Exception:
            # A save from an incompatible version must never stop us starting.
            self.load_error = _UNREADABLE_SAVE
            return False

    def _resume_load_state(self):
        """Open what a freshly loaded position was waiting on.

        A game saved in the middle of a crisis has ``beingQuestioned`` set and
        its Next-turn button disabled; the news window is the only way out, and
        nothing told the player so.  The window may still be hidden (the start
        screen is up), so the opening waits for the first show.
        """
        world = self.world
        self._resume_pending = bool(world.beingQuestioned) and not any(
            (world.winFlag, world.ANWFlag, world.NWFlag))
        if self._resume_pending and self.isVisible():
            QTimer.singleShot(0, self._run_resume)

    def _run_resume(self):
        if not self._resume_pending or not self.isVisible():
            return
        self._resume_pending = False
        if self.world.beingQuestioned:
            self.newsWindow.showUp()

    def showEvent(self, event):
        super(MainWindow, self).showEvent(event)
        if self._resume_pending:
            QTimer.singleShot(0, self._run_resume)

    def setWorld(self, newWorld):
        """Swap in a new world, carrying the map polygons across.

        The incoming object is validated *before* anything is touched: a pickle
        that is not a World used to be deleted-over the live one, leaving the
        window without a world at all.  If anything fails half way the previous
        world is put back.
        """
        if not isinstance(newWorld, World) or len(getattr(newWorld, "country", ()) or ()) < 2:
            raise TypeError("not a Balance of Power game: %s" % type(newWorld).__name__)
        # A different game is not the mail game -- unless it is one resumed from
        # the autosave or a slot, which remembers that it was (``mailGame``).
        self._mail_mode = bool(getattr(newWorld, "mailGame", False))
        self._resume_pending = False
        oldWorld = self.world
        polys = [c.mapPolyObject for c in oldWorld.country]
        try:
            self._install_world(newWorld, polys)
        except Exception:
            self.world = oldWorld
            try:
                self.mapView.scene().mapPainter.setWorld(oldWorld)
                self.updateLevel()
                self.local_side = oldWorld.human
            except Exception:
                pass
            raise

    def _install_world(self, newWorld, polys):
        # Every world enters the window through here -- new, loaded, imported or
        # received over the network -- so this is the one place a save written by
        # an older build gets the fields it is missing.  Without it a stale
        # autosave kills the game at start-up with an AttributeError.
        if hasattr(newWorld, "repair"):
            newWorld.repair()
        self.world = newWorld
        if self._mail_mode:
            newWorld.twoPFlag = True        # see the ``mail_mode`` setter
        # Establish (or adopt) the intermediate-objective baseline.  A world
        # loaded from a save already carries its own, which ``ensure_state``
        # keeps; one from a save made before objectives existed gets a baseline
        # of the position it was loaded at, which is the best that can be done.
        Objectives.ensure_state(self.world)
        self.mapView.scene().mapPainter.setWorld(self.world)
        self.updateLevel()
        for poly, country in zip(polys, self.world.country):
            country.mapPolyObject = poly
        # A new position starts a new year: nobody has finished their move yet.
        self.pending_end.clear()
        self.newsWindow.setLocked(any((newWorld.winFlag, newWorld.ANWFlag, newWorld.NWFlag)))
        self.newsWindow.question.setEnabled(False)
        self.newsWindow.backDown.setEnabled(False)
        self.newsWindow.filters[2 * newWorld.cmptr].setChecked(True)
        self.local_side = newWorld.human
        mail_side = getattr(newWorld, "mailSide", None)
        if self._mail_mode and mail_side in (0, 1):
            # A mail game resumed from a save: the position may already be
            # handed to the opponent, but this machine still plays its own side.
            self.local_side = int(mail_side)
        self.newsWindow.setAdvisorSide(self.local_side)

    def updateLevel(self):
        """Disable the map modes that the current difficulty does not allow."""
        for i in range(MAP_MODE_COUNT):
            self.controlPanel.mapModeAction[i].setEnabled(True)
        for i in INAVL_MAP_MODES[self.world.level - 1]:
            self.controlPanel.mapModeAction[i].setEnabled(False)
            if i < 17:
                self.controlPanel.mapModeButton[i].setEnabled(False)

    def closeEvent(self, event):
        if self.menu.options[0].isChecked():
            self.saveWorld()
        if self.session is not None:
            self.session.close()
        # Music is the one thing here with a thread and an audio device behind
        # it; leaving either running after the window has gone is how a process
        # that looks closed keeps playing.
        Music.shutdown()
        event.accept()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def setStatus(self, id):
        """Set the status label.  ``-1`` means 'show whose turn it is'."""
        if id == -1:
            if self.mail_waiting():
                text = html.escape(self.waiting_for_text())
            elif self.world.twoPFlag or self.network_game:
                name = Local.strings[Local.DATA_COUNTRIES + self.local_side][Local.CTRY_NAME]
                text = Local.strings[Local.MAIN_PANEL][15] + name
            else:
                text = Local.strings[Local.MAIN_PANEL][14]
        else:
            text = Local.strings[Local.MAIN_PANEL][id]
        self.statusBarWidget.setLabel("<b>%s</b>" % text)
        if self.network_game:
            # Repaint only.  This is called many times while the host resolves a
            # turn from inside the handling of the guest's message; a full
            # ``processEvents`` there lets the sockets deliver (or drop) the
            # guest in the middle of the resolution.  The sockets can wait; the
            # label cannot.
            QApplication.processEvents(QEventLoop.ExcludeSocketNotifiers
                                       | QEventLoop.ExcludeUserInputEvents)
        else:
            QApplication.processEvents()

    def updateTension(self):
        """Show what the player *believes* the tension is, not the truth.

        The gap between the two is the whole point of the intelligence budget:
        at level 0 the reading can be off by about a quarter of the scale, and the
        advisor chat is the only way to reason about it.
        """
        from GameLogic.MovePlanner import estimate_error
        if self.world.NWFlag or self.world.ANWFlag:
            # The game is over and the gauge must say so, not keep the last
            # estimate from before the exchange.
            self.statusBarWidget.setTension(1.0, "", war=True)
            return
        side = 0 if int(getattr(self, "local_side", 0)) == 0 else 1
        known = getattr(self.world, "knownNastiness", None)
        value = known[side] if known else self.world.nastiness
        value = min(1.0, max(0.0, value / 127.0))
        error = estimate_error((getattr(self.world, "intel", [0, 0]) or [0, 0])[side])
        detail = Local.strings[Local.TENSION][1] + " \u00b1%d" % error
        self.statusBarWidget.setTension(value, detail)

    def updateAiStatus(self):
        """Say what is playing the other side, for the whole game.

        Without this the fifth level is indistinguishable from the fourth when
        no key is configured: the player picks "Adaptive (LLM)", the opponent
        plays exactly as before, and nothing explains why.
        """
        if self.llm_opponent is None:
            self.statusBarWidget.setAiStatus("")
            return
        self.statusBarWidget.setAiStatus(self.llm_opponent.status_line())

    def setIntelLevel(self, level):
        """Change how much the local player spends on intelligence."""
        side = 0 if int(getattr(self, "local_side", 0)) == 0 else 1
        self.world.intel[side] = max(0, min(5, int(level)))
        self.refresh_ui()

    def intelLevel(self):
        side = 0 if int(getattr(self, "local_side", 0)) == 0 else 1
        return self.world.intel[side]

    def hoverCountryChanged(self, poly):
        if poly is None:
            self.statusBarWidget.setHoverText("")
            return
        name = Local.strings[Local.DATA_COUNTRIES + poly.id][Local.CTRY_NAME]
        text = "<b>%s</b>" % name
        if poly.value:
            text += " &nbsp;<span style='color:%s'>%s</span>" % (Palette.ACCENT.name(), poly.value)
        self.statusBarWidget.setHoverText(text)

    def showCloseUpForSelection(self):
        selection = self.mapView.selection
        if selection is not None:
            self.closeUpWindow.loadCountry(self.world.country[selection.id])

    # ------------------------------------------------------------------
    # Game setup
    # ------------------------------------------------------------------

    def game_in_progress(self):
        """Is there a started, unfinished game on screen that a new one would replace?

        False on the start screen (the main window is not shown and the world is
        only the placeholder) and once the game has ended either way.
        """
        world = self.world
        if not self.isVisible() or not world.country[0].historyScore:
            return False
        return not any((world.winFlag, world.ANWFlag, world.NWFlag))

    def confirm_abandon_game(self):
        """Ask before a new game replaces (and autosaves over) the current one."""
        if not self.game_in_progress():
            return True
        answer = QMessageBox.question(
            self, "Balance of Power",
            "Abandon the current game?\nStarting a new game replaces it, "
            "including the autosave.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def start_local_game(self, level, two_player, side):
        """Begin a game on this machine only."""
        self.leave_session()
        self.last_level = level
        self.setStatus(25)
        self.setWorld(World(level, two_player, side))
        self.local_side = side
        self.setup_llm_opponent(level)
        prePlanMove(self.world)
        mainMove(self, self.world)
        # The baseline for the objectives is the position the player actually
        # starts from, i.e. after the opening AI move, not before it.
        Objectives.snapshot(self.world)
        self.mapView.scene().mapPainter.recalculateMapBuffer()
        self.mapView.resetMapView()
        self.controlPanel.yearLabel.setText(str(self.world.year))
        self.setStatus(-1)
        self.reset_undo_history()
        self.refresh_ui()

    @property
    def net(self):
        """The session, but only while it is actually in use.

        A :class:`Net.Session.Session` outlives its connection: the multiplayer
        lobby creates one, and closing the lobby only disconnects it.  Treating
        that leftover object as a live session disabled the End Turn button in
        every later single-player game — the player opens Multiplayer once, backs
        out, and the game stops responding to its main control.  Anything that
        asks "are we playing over the network right now?" must ask this.
        """
        session = self.session
        if session is not None and session.is_online and session.is_connected:
            return session
        return None

    @property
    def network_game(self):
        """True while a network game is in progress, a reconnection included.

        Between the drop and the reconnect there is no live socket, so
        :attr:`net` is ``None`` — but the position still belongs to two
        machines and neither may answer for the other.  Everything that asks
        "is the other side a different computer?" asks this.
        """
        if self.net is not None:
            return True
        session = self.session
        return session is not None and bool(getattr(session, "reconnecting", False))

    def player_side(self):
        """The superpower whose player sits at this keyboard.

        On a network or in play by mail that is the fixed ``local_side``;
        ``world.human`` follows the move there (it flips each year in a mail
        game) and in hot-seat it *is* whoever has the mouse.
        """
        if self.network_game or self.mail_mode:
            return 0 if int(self.local_side) == 0 else 1
        return 0 if int(self.world.human) == 0 else 1

    # ------------------------------------------------------------------
    # Language-model opponent
    # ------------------------------------------------------------------

    def setup_llm_opponent(self, level):
        """Create (or clear) the model-backed opponent for this game."""
        # A new game starts the advisors' call budget afresh.
        self._advisor_client = None
        if level != LEVEL_LLM or self.world.twoPFlag:
            self.llm_opponent = None
            return None
        self.llm_log = []
        self.llm_opponent = LLMOpponent(
            config=self.llm_config,
            notify=self.llm_notify,
            record=self.llm_record,
            execute=self.llm_execute)
        return self.llm_opponent

    def advisor_client(self):
        """The advisors' chat client for this game, or None without a usable model.

        Built once per game and reused by the council, the crisis window and the
        one-to-one chats: a fresh client per question starts its counters at
        zero every time, so the per-game call limit was never actually reached.
        The configuration is re-resolved on every call, because the settings
        window may have changed the model or key since the client was made.
        """
        from GameLogic.AdvisorChat import ai_advisors_enabled, chat_config
        from GameLogic.LLMClient import LLMClient
        if not ai_advisors_enabled(self.llm_config):
            return None
        resolved = chat_config(self.llm_config)
        if resolved is None or not getattr(resolved, "usable", False):
            return None
        if self._advisor_client is None:
            self._advisor_client = LLMClient(resolved)
        else:
            self._advisor_client.config = resolved
        return self._advisor_client

    def llm_execute(self, fn, timeout=None):
        """Run the API call off the UI thread, with a live status line."""
        timeout = timeout or (self.llm_config.timeout + 5.0)

        def tick(elapsed):
            self.statusBarWidget.setHoverText(
                "%s is deliberating\u2026 %.0fs" % (self.ai_name(), elapsed / 1000.0))

        try:
            return run_blocking(fn, timeout=timeout, on_tick=tick, parent=self)
        finally:
            self.statusBarWidget.setHoverText("")

    def netlog_add(self, text):
        import time as _time
        self.netlog.append("%.1f %s" % (_time.monotonic() % 1000, text))
        del self.netlog[:-60]

    def ai_name(self):
        try:
            return Local.strings[Local.DATA_COUNTRIES + self.world.cmptr][Local.CTRY_NAME]
        except (AttributeError, IndexError):
            return "The opponent"

    def llm_notify(self, text):
        self.statusBarWidget.setHoverText(text)

    def llm_record(self, plan):
        self.llm_log.append((self.world.year, plan.source, plan.reasoning,
                             list(plan.actions)))
        del self.llm_log[:-60]

    def llm_note(self, text):
        """Record something the model decided that was not one of its policies.

        Chiefly whether it chose to contest the player's moves: that is the only
        decision the opponent makes about the player rather than about the map,
        and it is worth showing in the reasoning window beside its policy moves.
        """
        self.llm_log.append((self.world.year, "crisis", text, []))
        del self.llm_log[:-60]

    def run_council(self, situation=None, headline=None, rounds=1, side=None):
        """Ask all four advisors at once and return ``{advisor_key: line}``.

        One batched request rather than four: the four sentences cost one call,
        and because they answer in the same breath they can see each other's
        positions.  Falls back to the rule-based verdicts whenever there is no
        model or the model is unreachable, so this never returns nothing.
        """
        from GameLogic.AdvisorCouncil import convene
        if side is None:
            # Default to whoever is at this keyboard.  A crisis passes the side
            # that is actually deciding, which is not always the same thing: the
            # opponent's move can leave *us* as the challenged party.
            if getattr(self, "session", None) is not None and \
                    getattr(self.session, "is_online", False):
                side = int(getattr(self, "local_side", 0))
            else:
                side = int(self.world.human)
        side = 0 if int(side) == 0 else 1
        transcript, _used = convene(
            self.world, side, situation=situation, headline=headline,
            config=self.llm_config, client=self.advisor_client(),
            execute=self.llm_execute, rounds=rounds)
        return {advisor.key: (text, round_number, advisor)
                for advisor, text, round_number in transcript}

    def installGame(self, document, side=None):
        """Become the position described by a portable game file.

        The position is applied *in place* through ``Net.State.apply_state`` and
        not by building a new ``World``: the map polygons and every open dialog
        hold references to the current ``Country`` objects, so replacing the
        world would leave the whole interface pointing at a discarded one.  This
        is the same rule the network snapshot path follows.
        """
        from Net import apply_state, world_to_state
        world = self.world
        backup = world_to_state(world)
        old_side = (world.human, world.cmptr)
        # Validate and apply first (rolled back by itself on failure); only a
        # successful load may end a running network session.
        from Net.GameFile import install_into
        install_into(world, document)   # GameFileError, position untouched
        try:
            return self._finish_install_game(world, side, document)
        except Exception:
            apply_state(world, backup)
            world.human, world.cmptr = old_side
            self.local_side = world.human
            try:
                self.refresh_ui()
            except Exception:
                pass
            raise

    def _finish_install_game(self, world, side, document=None):
        self.leave_session()
        # The file is applied over the live world, so a field the file does not
        # carry would keep the previous game's value: its advisor-memory id, the
        # mail flag, who started a war.  Take them from the file, or clear them.
        saved = ((document or {}).get("state") or {}).get("world") or {}
        world.advisorGameId = saved.get("advisorGameId") or None
        world.mailGame = bool(saved.get("mailGame", False))
        world.warStarter = saved.get("warStarter")
        world.mailSide = None           # the file may carry the sender's side
        self.mail_mode = world.mailGame
        if side is not None:
            world.human, world.cmptr = int(side), 1 - int(side)
        self.local_side = world.human
        self.duel = None
        self.crisis_pending = False
        self.crisis_queue = []
        self.pending_end.clear()
        self.remote_turn = -1
        Objectives.ensure_state(world)
        self.updateLevel()
        self.newsWindow.setLocked(any((world.winFlag, world.ANWFlag, world.NWFlag)))
        self.newsWindow.filters[2 * world.cmptr].setChecked(True)
        self.newsWindow.setAdvisorSide(world.human)
        self.setup_llm_opponent(world.level)
        self.reset_undo_history()
        self.refresh_ui()
        self.check_game_over()
        self.setStatus(-1)
        return world

    def exportGame(self, path, game_name="", turn=None):
        """Write this position as one portable game file."""
        from Dialog.GameTransfer import export_to
        return export_to(self, path, game_name=game_name, turn=turn)

    def open_objectives(self):
        """The menu entry for the objectives, matching the strip's button."""
        self.objectivesBar.openDetails()

    def open_llm_settings(self):
        from Dialog.LLMSettingsWindow import LLMSettingsWindow
        if self.llm_settingsWindow is None:
            self.llm_settingsWindow = LLMSettingsWindow(self)
        self.llm_settingsWindow.reload()
        self.llm_settingsWindow.show()
        self.llm_settingsWindow.raise_()

    def open_opponent_log(self):
        from Dialog.OpponentLogWindow import OpponentLogWindow
        if self.opponentLogWindow is None:
            self.opponentLogWindow = OpponentLogWindow(self)
        self.opponentLogWindow.refresh()
        self.opponentLogWindow.show()
        self.opponentLogWindow.raise_()

    def open_advisor_chat(self):
        from Dialog.AdvisorChatWindow import AdvisorChatWindow
        if self.advisorChatWindow is None:
            self.advisorChatWindow = AdvisorChatWindow(self)
        self.advisorChatWindow.reload()
        self.advisorChatWindow.show()
        self.advisorChatWindow.raise_()

    # ------------------------------------------------------------------
    # Undo last turn (single-machine play only)
    # ------------------------------------------------------------------

    def reset_undo_history(self):
        """Start tracking undo points for a fresh game."""
        self.turn_start_state = self._snapshot()
        self.undo_state = None
        self.undo_used = False
        if getattr(self, "menu", None) is not None:
            self.menu.updateNetworkActions()

    def _snapshot(self):
        try:
            return world_to_state(self.world)
        except TypeError:
            return None

    def push_undo_point(self):
        """Called whenever a new turn begins: rotate the undo snapshots.

        Skipped in a network game — undo is not offered there, and snapshotting
        the world every turn would be wasted work on the authoritative host.
        """
        if self.session is not None and self.session.is_online:
            return
        self.undo_state = self.turn_start_state
        self.turn_start_state = self._snapshot()
        self.undo_used = False
        if self.menu is not None:
            self.menu.updateNetworkActions()

    def can_undo_turn(self):
        """Undo is a single-machine convenience, once per turn.

        It is deliberately unavailable in a network game: rewinding the world
        would silently undo the other player's decisions too.
        """
        if self.session is not None and self.session.is_online:
            return False
        if self.undo_state is None or self.undo_used:
            return False
        return not any((self.world.winFlag, self.world.ANWFlag, self.world.NWFlag))

    def do_undo_turn(self):
        if not self.can_undo_turn():
            return
        apply_state(self.world, self.undo_state)
        if self.is_hotseat():
            # ``human`` came back with the position; the keyboard must follow it
            # or the side at the mouse is not the side that is to move.
            self.local_side = self.world.human
        self.undo_used = True
        # The position we just restored IS the start of the current turn.  Without
        # this, push_undo_point carries the abandoned turn forward as the next
        # undo point, so undoing twice steps back to the turn that was rejected
        # and reinstates its score.
        self.turn_start_state = self._snapshot()
        self.pending_end.clear()
        self.duel = None
        self.crisis_queue = []
        self.crisis_pending = False
        self.mapView.scene().mapPainter.recalculateMapBuffer()
        self.controlPanel.yearLabel.setText(str(self.world.year))
        self.setStatus(-1)
        self.refresh_ui()
        if self.menu is not None:
            self.menu.updateNetworkActions()

    def open_multiplayer(self, autorun=None, port=None, address=None):
        self.ensure_session()
        if port:
            self.last_port = port
        # One lobby window for the life of the window, not one per visit.  A new
        # MultiplayerWindow each time leaked its whole widget tree -- measured at
        # 2.7 MB per open, and it also built a second discovery browser and
        # beacon.  A reused window has to rewire itself, because closing it
        # disconnects the session signals; without that, hosting from the
        # second visit would silently receive nothing.
        window = self.multiplayerWindow
        if window is None:
            window = MultiplayerWindow(self, self.session)
            self.multiplayerWindow = window
        else:
            window.session = self.session
            window._connect_session()
            window._update_controls()
        window.show()
        if autorun == "host":
            window.portSpin.setValue(self.last_port)
            window._do_host()
        elif autorun == "join":
            if address:
                window.addressEdit.setText(address)
            window._do_join()
        return window

    def ensure_session(self):
        if self.session is None:
            self.session = Session(self)
            self._connect_session()
        self.menu.updateNetworkActions()
        return self.session

    def leave_session(self):
        if self.session is not None and self.session.is_online:
            self.session.close()
        self.resolving = False
        self.pending_end.clear()
        self.menu.updateNetworkActions()
        self.controlPanel.refreshTurnState()

    # ------------------------------------------------------------------
    # Networking glue
    # ------------------------------------------------------------------

    def _connect_session(self):
        session = self.session
        session.gameStarted.connect(self.start_network_game)
        session.snapshotReceived.connect(self.on_snapshot)
        session.actionReceived.connect(self.on_remote_action)
        session.crisisPrompted.connect(self.on_crisis_prompted)
        session.peerDisconnected.connect(self.on_peer_disconnected)
        session.statusMessage.connect(self.on_network_status)
        session.errorOccurred.connect(self.on_network_error)

    def start_network_game(self, settings):
        """Both machines receive this; the host builds the world."""
        level = int(settings.get("level", self.last_level))
        self.last_level = level
        self.setStatus(25)
        if self.session.is_host:
            side = int(settings.get("host_side", 0))
            world = World(level, True, side)
            self.session.settings = dict(settings)
            self.setWorld(world)
            self.local_side = side
            self.setup_llm_opponent(level)
            self.pending_end.clear()
            prePlanMove(self.world)
            mainMove(self, self.world)
            Objectives.snapshot(self.world)
            self.mapView.scene().mapPainter.recalculateMapBuffer()
            self.mapView.resetMapView()
            self.controlPanel.yearLabel.setText(str(self.world.year))
            self.setStatus(-1)
            self.refresh_ui()
            self.broadcast_state()
        else:
            side = int(settings.get("guest_side", 1))
            if self.session.local_side in (0, 1):
                # What the host actually assigned (WELCOME), which also covers
                # a guest that restarted and was handed this START again.
                side = int(self.session.local_side)
            self.local_side = side
            # Keep the local mirror pointing at the right superpower until the
            # host's first snapshot arrives.
            self.world.human = side
            self.world.cmptr = 1 - side
            self.world.twoPFlag = True
            # A LAN game is not a mail game, even if the world it replaces was
            # one (the host's snapshot never carries these fields).
            self._mail_mode = False
            self.world.mailGame = False
            self.world.mailSide = None
            self.pending_end.clear()
            self.setStatus(-1)

    def broadcast_state(self):
        net = self.net
        if net is not None and net.is_host:
            try:
                net.broadcast_snapshot(world_to_state(self.world),
                                       turn=self.turn_counter)
            except TypeError:
                # A payload we cannot serialise must not break the game; the
                # guest will simply catch up on the next state change.
                pass

    def on_snapshot(self, payload):
        # The frame carries the world plus the host's turn marker.
        if isinstance(payload, dict) and "state" in payload:
            state = payload.get("state") or {}
            marker = payload.get("turn")
        else:                                   # older peer, state only
            state, marker = payload or {}, None
        try:
            apply_state(self.world, state)
        except Exception as exc:  # malformed or incompatible snapshot
            self.on_network_error("state update failed: %s" % exc)
            return
        session = self.session
        if session is not None and session.is_client and session.local_side in (0, 1) \
                and int(session.local_side) != int(self.local_side):
            # A guest that was restarted and rejoined never saw START, so it
            # does not know which superpower it plays; the host told it in
            # WELCOME.
            self.local_side = int(session.local_side)
            self.newsWindow.setAdvisorSide(self.local_side)
        # The host's view of ``human`` is the host's own side; on this machine
        # the local player must stay the local player.
        self.world.human = self.local_side
        self.world.cmptr = 1 - self.local_side
        # Clear our end-of-turn request only when the host says a turn has
        # actually completed.  Watching the year was wrong: snapshots sent
        # during a crisis already carry the incremented year, so the button
        # re-armed halfway through the opponent's resolution.
        if marker is not None and int(marker) != self.remote_turn:
            self.remote_turn = int(marker)
            self.pending_end.clear()
        self.mapView.scene().mapPainter.recalculateMapBuffer()
        self.refresh_ui()
        self.check_game_over()

    def on_remote_action(self, message):
        """The host applies whatever the guest asked for."""
        net = self.net
        if net is None or not net.is_host:
            return
        kind = message.get("action")
        if kind == Action.POLICY:
            # ``Session`` has already forced ``actor`` to the guest's side and
            # checked the types and ranges; the country index can only be
            # checked against the real world here.
            try:
                target = int(message.get("target"))
                policy = int(message.get("policy"))
                value = int(message.get("value"))
                actor = int(message.get("actor", self.local_side ^ 1))
            except (TypeError, ValueError):
                return
            if not (0 <= target < len(self.world.country)) or actor not in (0, 1) \
                    or actor == self.local_side:
                self.netlog_add("ignored a policy request with a bad target/actor")
                return
            from GameLogic.PolicyRules import check_request
            ok, why = check_request(self.world, self.world.country[actor], policy,
                                    target, value)
            if not ok:
                self.netlog_add("refused a policy request: %s" % why)
                # Re-send the real state so the guest's screen drops the move.
                self.broadcast_state()
                return
            try:
                self._apply_policy(target, policy, value, actor_side=actor)
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                self.netlog_add("ignored a policy request that does not apply: %s" % exc)
                return
            self.broadcast_state()
        elif kind == Action.END_TURN:
            self.netlog_add("END_TURN from %s (resolving=%s)"
                            % (message.get("actor"), self.resolving))
            if self.resolving:
                # A request that arrived while the turn was already being
                # resolved belongs to the next turn; the guest will send it
                # again once it sees the completed-turn marker.
                return
            self.pending_end.add(int(message.get("actor", 1)))
            self.maybe_resolve_turn()
        elif kind == Action.CRISIS:
            # New peers send a verb; a guest still running the old build sends
            # only a bool, which ``CrisisDuel.decide`` still understands.
            verb = message.get("choice")
            if verb is None and message.get("tough") is not None:
                verb = bool(message.get("tough"))
            self.on_crisis_decision(verb)

    def on_peer_disconnected(self, reason):
        if self.session is not None and not self.session.is_online:
            self.pending_end.clear()
            self.crisis_pending = False
            self.duel = None
            if self.resolving:
                # The turn was waiting on the player who has now gone for good.
                # Nothing will ever answer that crisis, so drop the queue and
                # finish the turn on this machine instead of staying
                # "resolving" for ever (which kept can_act() False).  This only
                # runs once the session is really over (not while a reconnect
                # window is open), so the returning peer cannot advance it twice.
                self.crisis_queue = []
                self.finish_turn()
                self.resolving = False
            self.setStatus(-1)
            self.controlPanel.refreshTurnState()
            self.menu.updateNetworkActions()
            # Deliberately not a modal dialog: a blocking box here freezes the
            # surviving side, which then cannot even be closed cleanly.
            self.statusBarWidget.setHoverText(
                Local.strings[Local.MULTIPLAYER][16] % reason)
            if self.crisisWindow.isVisible():
                self.crisisWindow.hide()

    def on_network_status(self, text):
        self.statusBarWidget.setHoverText(text)

    def on_network_error(self, text):
        self.statusBarWidget.setHoverText(Local.strings[Local.MULTIPLAYER][32] % text)

    # ------------------------------------------------------------------
    # Turn control
    # ------------------------------------------------------------------

    def can_act(self):
        """May the local player enact policies, and end the turn, right now?"""
        world = self.world
        if world.winFlag or world.ANWFlag or world.NWFlag:
            return False
        # A crisis in the news window owns the turn until it is answered.  The
        # original disabled the Next Turn button on exactly this condition; drop
        # the check and ending the turn starts a *new* year while the old crisis
        # is still open, so the game sails past 1990 without ever declaring
        # peace or war.
        if world.beingQuestioned:
            return False
        # While the host is resolving, a turn is already in flight; letting the
        # guest end another one would count against a turn that is over.
        if self.resolving:
            return False
        # A dropped-but-not-yet-abandoned connection is still a network game:
        # the other side holds the position and we are about to be told about
        # it.  Relying on ``Session.is_connected`` staying true through the
        # grace window would work, but saying it outright is clearer and does
        # not break the day that semantic changes.
        if self.session is not None and getattr(self.session, "reconnecting", False):
            return False
        if self.duel is not None or self.crisis_pending:
            return False
        net = self.net
        if net is None:
            if self.mail_waiting():
                return False
            return True
        return self.local_side == world.human

    def mail_waiting(self):
        """Play by mail, and it is the other player's move (or mine is not sent yet).

        ``world.human`` is who is to move in the position held here.  After this
        machine has finished its year ``changeSides`` hands the position to the
        opponent, and the same holds when the game is resumed with Continue (the
        autosave remembers the side in ``mailSide``): ``local_side`` stays this
        machine's own side, so the two differ until the opponent's move is loaded.
        """
        if not self.mail_mode or self.network_game:
            return False
        world = self.world
        if world.winFlag or world.ANWFlag or world.NWFlag:
            return False
        return int(self.local_side) != int(world.human)

    def can_end_turn(self):
        if not self.can_act():
            return False
        return self.local_side not in self.pending_end

    def waiting_for_text(self):
        """The 'waiting for the other side' line, or nothing at all.

        A session left over from a closed lobby is not somebody we are waiting
        for, and saying "Waiting for ? to finish the turn" over a single-player
        board was the visible half of the stale-session bug.
        """
        if self.mail_waiting():
            return ("Waiting for your partner's move \u2014 Multiplayer > Open "
                    "mailbox > Send my turn, then Load their move")
        if not self.network_game:
            return ""
        session = self.session
        peer = getattr(session, "peer_name", None) or "?"
        return Local.strings[Local.MULTIPLAYER][18] % peer

    def request_policy(self, action, target, value):
        """Enact a policy, locally or through the host."""
        net = self.net
        if net is None and self.mail_waiting():
            return                  # not this machine's move: see can_act
        if net is not None and net.is_client:
            net.send_action(Action.POLICY, actor=self.local_side,
                            policy=action, target=target, value=value)
            return
        self._apply_policy(target, action, value, actor_side=self.local_side)
        if net is not None and net.is_host:
            self.broadcast_state()

    def _apply_policy(self, target, policy, value, actor_side=None):
        from GameLogic.Globals import doPolicy
        side = self.world.human if actor_side is None else actor_side
        actor = self.world.country[side]
        doPolicy(self.world, actor, self.world.country[target], policy, value)
        self.refresh_ui()

    def request_end_turn(self):
        if not self.can_act():
            self.netlog_add("end-turn refused (can_act false)")
            return
        self.netlog_add("end-turn requested side=%d" % self.local_side)
        net = self.net
        self.pending_end.add(self.local_side)
        if net is not None and net.is_client:
            net.send_action(Action.END_TURN, actor=self.local_side)
            self.controlPanel.refreshTurnState()
            return
        if self.is_hotseat() and len(self.pending_end) < 2:
            # Hot-seat: the year is played by both superpowers and resolves
            # only when the second one is done.  The first player's "done"
            # hands the keyboard over.
            self.switch_hotseat_side()
            return
        self.maybe_resolve_turn()

    def is_hotseat(self):
        """Two humans at one keyboard (not a network game, not play by mail).

        In play by mail each player resolves the year on their own machine
        (see ``mail_mode``); the "pass the keyboard" hand-over would make the
        mover play the other superpower's half as well.
        """
        return (bool(self.world.twoPFlag) and not self.network_game
                and not self.mail_mode)

    def switch_hotseat_side(self):
        """Hand the keyboard to the other superpower (hot-seat only).

        Keeps ``world.human``, ``local_side`` and the status line in step: they
        used to be updated by three different code paths, so after a manual
        switch the scores panel and the 'Now playing' line disagreed.
        """
        if not self.is_hotseat():
            return
        self.world.changeSides()
        self.local_side = self.world.human
        self.setStatus(-1)
        self.refresh_ui()

    def hotseat_next_label(self):
        """Text for the Next button in a hot-seat game, or None."""
        if not self.is_hotseat():
            return None
        other = 1 - self.local_side
        if other in self.pending_end:
            return "End the year"
        name = Local.strings[Local.DATA_COUNTRIES + other][Local.CTRY_NAME]
        return "Pass to %s" % name

    def maybe_resolve_turn(self):
        """Resolve the turn once both players have ended it."""
        if self.resolving:
            return
        net = self.net
        if net is not None:
            if len(self.pending_end) < 2:
                self.controlPanel.refreshTurnState()
                self.statusBarWidget.setHoverText(Local.strings[Local.MULTIPLAYER][17])
                return
        self.netlog_add("resolving: pending=%s" % sorted(self.pending_end))
        self.pending_end.clear()
        self.resolving = True
        try:
            self.resolve_turn()
        finally:
            # resolve_turn may hand off to an asynchronous crisis chain; the
            # flag is cleared when the turn actually completes.
            if self.duel is None and not self.crisis_queue:
                self.resolving = False

    # ------------------------------------------------------------------
    # Turn resolution
    # ------------------------------------------------------------------

    def two_human_game(self):
        return self.world.twoPFlag

    def resolve_turn(self):
        """Run one end-of-turn: internal events, AI, then crises."""
        world = self.world
        self.controlPanel.nextTurnButton.setEnabled(False)
        self.setStatus(25)
        self.controlPanel.yearLabel.setText(str(world.year))
        prePlanMove(world)
        self.controlPanel.yearLabel.setText(str(world.year))

        if self.two_human_game():
            self._accumulate_nastiness()
            if self.mail_mode:
                # Play by mail: the other superpower's decisions belong to the
                # other player, who is not here.  Answering a duel for both
                # sides would let the mover decide the opponent's side of every
                # crisis, so contestable moves simply stand uncontested.
                self.crisis_queue = []
            else:
                self.crisis_queue = list(contestable_news(world))
            self._next_crisis()
        else:
            reactNews(self, world)

    def _accumulate_nastiness(self):
        """The tension bookkeeping that ``reactNews`` does for the AI game."""
        from constants import DESTAB, INGSINTV, INSGAID, PRESSURE
        world = self.world
        for n in world.news:
            if n.action in (INGSINTV, INSGAID, DESTAB, PRESSURE) and n.actor.id < 2:
                world.nastiness += (n.new - n.old)
                world.nastiness = max(1, min(127, world.nastiness))

    def war_declared(self):
        world = self.world
        return bool(world.NWFlag or world.ANWFlag)

    def _next_crisis(self):
        """Present the next contestable move, or finish the turn."""
        if self.war_declared():
            # A nuclear exchange ends the game: queued crises are moot, the
            # turn must not continue, and a post-war world is never autosaved.
            self.crisis_queue = []
            self.duel = None
            self.resolving = False
            self.refresh_ui()
            self.check_game_over()
            if self.net is not None and self.net.is_host:
                self.broadcast_state()
            return
        while self.crisis_queue:
            news = self.crisis_queue.pop(0)
            if news.crisisVal:
                continue
            self.duel = CrisisDuel(self.world, news)
            self._ask_decider()
            return
        self.duel = None
        self.finish_turn()

    def _ask_decider(self):
        prompt = self.duel.prompt()
        if prompt is None:
            self._duel_finished()
            return
        decider = prompt["decider"]
        if self._is_local(decider):
            self.crisisWindow.showPrompt(CrisisPrompt.from_duel(self.duel))
        else:
            net = self.net
            if net is not None and net.is_host:
                net.send_crisis(prompt)
            self.statusBarWidget.setHoverText(Local.strings[Local.MULTIPLAYER][31])

    def _is_local(self, side):
        """Is this side answered at this keyboard?

        A leftover session object from a closed lobby used to make this return
        False for one side in a *single-machine* game: the crisis window was
        never shown, nothing was sent over a network that did not exist, and
        ``can_end_turn`` stayed false for ever.  One contested move after a visit
        to the Multiplayer lobby made the turn impossible to finish.
        """
        if not self.network_game:
            return True  # one machine: both sides sit at this keyboard
        return side == self.local_side

    def on_crisis_decision(self, choice):
        """A decision arrived — locally, or from the guest.

        ``choice`` is a verb ("contest", "accept", "tough", "back_down",
        "summit", "yes", "no").  A plain bool is still honoured, because a guest
        running an older build sends ``tough`` and nothing else.
        """
        if not isinstance(choice, str):
            choice = bool(choice)
        net = self.net
        if net is not None and net.is_client:
            # Our mirror has no duel of its own: the host owns it.  Forward the
            # answer and wait for the resulting snapshot.
            self.crisis_pending = False
            leg = choice if isinstance(choice, str) else None
            net.send_action(Action.CRISIS, choice=leg,
                            tough=(choice if isinstance(choice, bool) else None),
                            actor=self.local_side)
            self.controlPanel.refreshTurnState()
            return
        if self.duel is None:
            return
        # Offline hot-seat reaches here with ``net is None``, and it must resolve
        # locally: both players sit at this keyboard and this process owns the
        # duel.  Returning early on ``net is None`` (as this did) threw the
        # answer away while the crisis window was still on screen, left
        # ``self.duel`` set, and so left ``can_end_turn()`` false for ever --
        # one contested move made a hot-seat game impossible to finish.
        decider = self.duel.decider.id
        finished = self.duel.decide(choice)
        if self.world.NWFlag and not self.world.ANWFlag:
            # Whoever raised the stakes at the last rung started the war.  It
            # lives in the world so the other machine and a save know it too.
            # An accidental launch is nobody's decision, so it names nobody.
            self.world.warStarter = decider
        if net is not None and net.is_host:
            self.broadcast_state()
        if finished:
            self._duel_finished()
        else:
            self._ask_decider()

    def on_crisis_prompted(self, payload):
        """Guest side: the host wants our answer."""
        self.duel = None
        self.crisis_pending = True
        prompt = CrisisPrompt(self.world, payload)
        self.statusBarWidget.setHoverText(Local.strings[Local.MULTIPLAYER][31])
        self.controlPanel.refreshTurnState()
        self.crisisWindow.showPrompt(prompt)

    def _duel_finished(self):
        if self.duel is not None:
            self.duel.finish()
            self.duel = None
        self.refresh_ui()
        self._next_crisis()

    def finish_turn(self):
        """Two-player path: hand over to ``continueNextTurn``.

        All the end-of-turn bookkeeping lives in :meth:`on_turn_completed`,
        which ``continueNextTurn`` calls; that way the one-player path (which
        reaches ``continueNextTurn`` from ``reactNews``) gets it too.
        """
        if self.war_declared():
            self._next_crisis()
            return
        continueNextTurn(self, self.world)

    def on_turn_completed(self):
        """Called by ``continueNextTurn`` once a turn is fully resolved."""
        self.resolving = False
        self.turn_counter += 1
        # Score the advisors' forecasts against the world the turn produced.
        # Done here, before the hot-seat hand-over below, so the side that has
        # just played is the one being scored.  Without this, a prediction made
        # in 1984 and never asked about again would stay open until the player
        # happened to reopen the advisor window.
        try:
            from GameLogic.AdvisorMemory import store
            store().observe(self.world, getattr(self, "local_side", self.world.human))
        except (ImportError, AttributeError, OSError, ValueError) as exc:
            self.netlog_add("advisor record unavailable: %s" % exc)
        self.update_objectives()
        self.netlog_add("turn %d complete" % self.turn_counter)
        self.mapView.flashYear(self.world.year)
        # Hot-seat: both superpowers have already moved this year (see
        # request_end_turn).  The player who closed the year opens the next one,
        # so who moves first alternates.  Resynchronise ``local_side`` in case
        # the resolution flipped ``world.human`` itself.  The test is
        # ``network_game``, not ``session``: a session left over from a closed
        # lobby used to confuse it.
        if self.mail_mode:
            # Play by mail: this machine plays one fixed side, and a move is one
            # resolved year.  Hand the position to the opponent (the file must say
            # they are to move, or "Send my turn" refuses it) -- except at the end
            # of the game, where nobody is to move and the final position is sent
            # as it stands (``Net.MailGame`` flags it ``game_over``).
            if not (self.world.winFlag or self.war_declared()):
                self.world.changeSides()
            # The turn's own autosave (MovePlanner.nextTurn) ran before this
            # hand-over.  Save again, or quit + Continue resumes a position that
            # still says it is this machine's move and the year can be replayed.
            if self.menu.options[0].isChecked():
                self.saveWorld()
        elif not self.network_game and self.world.twoPFlag:
            self.local_side = self.world.human
        self.refresh_ui()
        if not self.world.winFlag:
            self.setStatus(-1)
        self.check_game_over()
        self.push_undo_point()
        net = self.net
        if net is not None and net.is_host:
            # Broadcast last, so the guest sees the completed-turn marker and
            # only then becomes able to end its next turn.
            self.pending_end.clear()
            self.broadcast_state()

    @staticmethod
    def _nearest_volume(value):
        """Snap a stored volume to the nearest step the menu offers.

        The volume is chosen from five steps, so a file written by hand - or by
        a future build with a slider - could otherwise leave every step
        unchecked, which reads as "the setting is missing" rather than as
        "it is between two of them".
        """
        steps = (0, 25, 50, 75, 100)
        return min(steps, key=lambda step: abs(step - int(value)))

    def _start_music_if_needed(self):
        """Begin generating the built-in themes, once the window is on screen."""
        # Not when the music is switched off: rendering three themes for a silent
        # game is several seconds of work nobody asked for, and it competes with
        # the event loop while it happens.
        if Music.enabled():
            Music.prepare(on_ready=self._music_ready)
        self.statusBarWidget.refreshMusic()

    def _music_ready(self):
        """Called as each built-in theme finishes generating.

        The first launch has no music cache, so the playlist starts out empty and
        fills in over a few seconds.  This is what turns the first finished theme
        into sound, and what keeps the little transport honest while it waits.
        """
        Music.refresh_tracks()
        if Music.enabled() and not Music.playing():
            Music.play()
        if getattr(self, "statusBarWidget", None) is not None:
            self.statusBarWidget.refreshMusic()

    def _flash_hover(self, text, milliseconds=8000):
        """Show a notice in the hover line, and take it down again.

        A notice that stays until the mouse happens to cross a country was
        still reading 'Objective lost' years later.
        """
        from PyQt5.QtCore import QTimer
        bar = self.statusBarWidget
        bar.setHoverText(text)

        def clear():
            try:
                if bar.hover.text() == text:
                    bar.setHoverText("")
            except RuntimeError:              # the window is already gone
                pass
        QTimer.singleShot(milliseconds, clear)

    def update_objectives(self):
        """Recompute the standing commitments and tell the player what changed.

        Called once per completed turn.  The change notices matter more than the
        strip: a commitment that has just been lost is the one piece of news the
        player most needs and the score will not deliver until 1990.
        """
        world = getattr(self, "world", None)
        if world is None:
            return
        try:
            _bonus, gained, lost = Objectives.refresh(world, world.human)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            # A broken objective must never abort the end of a turn.
            self.netlog_add("objectives unavailable: %s" % exc)
            gained, lost = [], []
        if gained:
            self._flash_hover("Objective gained: %s" % "; ".join(gained))
        elif lost:
            self._flash_hover("Objective lost: %s" % "; ".join(lost))
        if getattr(self, "objectivesBar", None) is not None:
            self.objectivesBar.refresh()

    def check_game_over(self):
        world = self.world
        if world.ANWFlag or world.NWFlag:
            self._refresh_end_state()
            starter = getattr(world, "warStarter", None)
            who = None
            # Name the side that pushed when it was not the player at this
            # keyboard: the computer, the other human, or anyone in hot-seat.
            if starter in (0, 1) and (self.is_hotseat() or starter != self.player_side()):
                who = Local.countryInProse(starter)
                who = who[:1].upper() + who[1:]
            self.lostGameWindow.showUp(world.ANWFlag, who)
            self.setStatus(28)
        elif world.winFlag:
            self._refresh_end_state()
            self.scoresWindow.setVisible(True)
            self.setStatus(27)

    def _refresh_end_state(self):
        """Bring the gauge, turn box, scores and Next button up to date.

        The end of a game can be reached from places that do not call
        :meth:`refresh_ui` afterwards (a crisis answered in a dialog), which
        left the tension gauge at its old reading, the turn box saying 'your
        move' and Next enabled until it was clicked.
        """
        self.updateTension()
        self.controlPanel.drawScores()
        self.controlPanel.refreshTurnState()
        # After a nuclear war the objectives are void; the chips only know that
        # when they are redrawn.
        self.objectivesBar.refresh()
        self.menu.updateNetworkActions()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh_ui(self):
        painter = self.mapView.scene().mapPainter
        painter.recalculateMapBuffer()
        selection = self.mapView.selection
        if 8 <= self.mapView.mapMode <= 21:
            painter.doMapRedraw(selection, self.mapView.mapMode)
        else:
            painter.paint(self.mapView.mapMode, selection.id if selection else None)
        self.controlPanel.drawScores()
        self.controlPanel.updatePlayerNames()
        self.controlPanel.updateSelection()
        self.controlPanel.yearLabel.setText(str(self.world.year))
        self.controlPanel.refreshTurnState()
        self.updateTension()
        self.updateAiStatus()
        self.objectivesBar.refresh()
        self.menu.updateIntelActions(self.intelLevel())
        self.newsWindow.refresh_if_open()
        if self.mapView.legendPanel.isVisible():
            self.mapView.updateLegend()

    def endGame(self):
        """Legacy entry point used by the single-player crisis handler."""
        self.check_game_over()
