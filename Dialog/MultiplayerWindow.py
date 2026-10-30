"""
The multiplayer lobby.

Lets two people on the same network find each other and start a game: host or
join, pick a side, see who is ready, and talk while waiting.  Discovery is
automatic (see :mod:`Net.Discovery`), with a manual address field as a fallback
for networks where broadcast does not reach.

Two things live here because this is where a player goes when networking is not
working.  "Test connection" runs the checks in :mod:`Net.Diagnostics` and prints
the answers into the lobby log — whether the port is listened on, whether the
peer answers, whether UDP discovery returns anything — which used to be visible
only in a log file nobody opens.  And the play-by-mail group hands the whole
game to a shared folder for the networks where TCP between machines is blocked
outright (:mod:`Net.MailGame`), because a shared drive is not.
"""

import html
import os
import socket

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QRadioButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

import Local
from Async import run_blocking
from Net import world_to_state
from Net.Diagnostics import address_summary, diagnose, local_addresses
from Net.Discovery import DiscoveryBrowser, DiscoveryBeacon, game_key
from Net.MailGame import (DEFAULT_POLL_MS, MailError, MailForkError, MailGame,
                          default_marker_path, legacy_marker_paths,
                          normalize_game_code, new_game_code)
from Net import DISCOVERY_PORT
from Net.Session import DEFAULT_PORT, SIDE_USA, SIDE_USSR
from Theme import Palette
from Widgets import FitScrollArea


class MultiplayerWindow(QDialog):
    """Host/join dialog.  Emits nothing: it drives the session directly."""

    def __init__(self, parent, session):
        super().__init__(parent)
        self.parent = parent
        self.session = session
        self.setModal(True)
        self.setWindowTitle(Local.strings[Local.MULTIPLAYER][0])
        self.setMinimumSize(560, 320)

        self.browser = DiscoveryBrowser(self)
        self.browser.gameFound.connect(self._on_game_found)
        self.browser.gameLost.connect(self._on_game_lost)
        self.beacon = DiscoveryBeacon(self)
        self._games = {}
        #: Play-by-mail: the folder transport, and the last status it reported.
        self.mail = MailGame(self)
        self.mail.statusChanged.connect(self._on_mail_status)
        self._mail_status = {}
        self._diagnosing = False
        #: This PC's own addresses, for the host panel (see Net.Diagnostics).
        try:
            self._addresses = address_summary(local_addresses())
        except Exception:                      # never let a lookup stop the lobby
            self._addresses = ([], "", "")

        self._build()
        # No default button: Enter in the join address used to press Host.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self._connect_session()
        self._update_controls()

    # -- construction -------------------------------------------------------

    def _build(self):
        strings = Local.strings[Local.MULTIPLAYER]
        root = QVBoxLayout()
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # --- identity -----------------------------------------------------
        identity = QGroupBox(Local.strings[Local.MULTIPLAYER][34])
        identityLayout = QGridLayout()
        identityLayout.addWidget(QLabel(strings[3]), 0, 0)
        self.nameEdit = QLineEdit(self.session.local_name or "Player")
        identityLayout.addWidget(self.nameEdit, 0, 1, 1, 2)
        identityLayout.addWidget(QLabel(strings[12]), 0, 3)
        self.sideUSA = QRadioButton(Local.strings[Local.WINDOW_NEWGAME][4])
        self.sideUSSR = QRadioButton(Local.strings[Local.WINDOW_NEWGAME][5])
        (self.sideUSA if self.session.local_side == SIDE_USA else self.sideUSSR).setChecked(True)
        sideBox = QHBoxLayout()
        sideBox.addWidget(self.sideUSA)
        sideBox.addWidget(self.sideUSSR)
        identityLayout.addLayout(sideBox, 0, 4)
        identity.setLayout(identityLayout)
        root.addWidget(identity)

        # --- host / join --------------------------------------------------
        columns = QHBoxLayout()
        columns.addWidget(self._build_host_group(), 1)
        columns.addWidget(self._build_join_group(), 1)
        root.addLayout(columns)

        # --- lobby --------------------------------------------------------
        root.addWidget(self._build_lobby_group(), 1)
        # --- fallbacks for networks that block TCP or broadcast -----------
        fallbacks = QHBoxLayout()
        fallbacks.addWidget(self._build_mail_group(), 1)
        fallbacks.addWidget(self._build_diagnostics_group(), 1)
        root.addLayout(fallbacks)
        # Scrolls: the lobby is taller than a 1366x768 laptop screen, and
        # squeezed to fit it every control overlapped.
        content = QWidget()
        content.setLayout(root)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = FitScrollArea(content)
        outer.addWidget(scroll)
        self.resize(max(760, scroll.sizeHint().width() + 4), scroll.sizeHint().height() + 4)

    def _build_host_group(self):
        strings = Local.strings[Local.MULTIPLAYER]
        group = QGroupBox(strings[1])
        layout = QGridLayout()
        layout.addWidget(QLabel(strings[4]), 0, 0)
        self.portSpin = QSpinBox()
        self.portSpin.setRange(1024, 65535)
        self.portSpin.setValue(getattr(self.parent, "last_port", DEFAULT_PORT))
        layout.addWidget(self.portSpin, 0, 1)
        self.hostButton = QPushButton(strings[7])
        self.hostButton.setObjectName("primary")
        self.hostButton.clicked.connect(self._do_host)
        layout.addWidget(self.hostButton, 1, 0, 1, 2)
        # The address the other player has to type.  Always visible, because
        # the discovery list does not work on every network.
        self.addressLabel = QLabel()
        self.addressLabel.setWordWrap(True)
        self.addressLabel.setTextFormat(Qt.RichText)
        self.addressLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.addressLabel, 2, 0, 1, 2)
        self.hostHint = QLabel()
        self.hostHint.setWordWrap(True)
        self.hostHint.setTextFormat(Qt.RichText)
        self.hostHint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hostHint.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        layout.addWidget(self.hostHint, 3, 0, 1, 2)
        # Optional: for a network where students cannot connect to each other
        # but can all reach the teacher's PC, which runs relay.py.
        self.relayCheck = QCheckBox("Host through the teacher's relay (optional)")
        self.relayCheck.setToolTip(
            "Only if your teacher gave you a relay address and port. Instead of "
            "waiting for your opponent to connect to you, your game connects "
            "out to the relay, and your opponent joins that same address and "
            "port. Leave this off for a normal game.")
        self.relayCheck.toggled.connect(self._relay_toggled)
        layout.addWidget(self.relayCheck, 4, 0, 1, 2)
        self.relayEdit = QLineEdit()
        self.relayEdit.setPlaceholderText("teacher-pc:46003  (address:port)")
        self.relayEdit.setEnabled(False)
        layout.addWidget(self.relayEdit, 5, 0, 1, 2)
        layout.setRowStretch(6, 1)
        self._refresh_address_label()
        group.setLayout(layout)
        return group

    def _build_join_group(self):
        strings = Local.strings[Local.MULTIPLAYER]
        group = QGroupBox(strings[2])
        layout = QGridLayout()
        layout.addWidget(QLabel(strings[5]), 0, 0, 1, 2)
        self.gameList = QListWidget()
        self.gameList.setSelectionMode(QAbstractItemView.SingleSelection)
        self.gameList.setMaximumHeight(110)
        layout.addWidget(self.gameList, 1, 0, 1, 2)
        self.refreshButton = QPushButton(strings[20])
        self.refreshButton.clicked.connect(self._refresh_games)
        layout.addWidget(self.refreshButton, 2, 0, 1, 2)
        layout.addWidget(QLabel(strings[21]), 3, 0, 1, 2)
        self.addressEdit = QLineEdit("127.0.0.1")
        self.addressEdit.setPlaceholderText("192.168.1.42")
        # Typing an address overrides whatever game is highlighted in the list.
        self.addressEdit.textEdited.connect(self._address_edited)
        self.addressEdit.returnPressed.connect(self._do_join)
        layout.addWidget(self.addressEdit, 4, 0)
        self.joinPortSpin = QSpinBox()
        self.joinPortSpin.setRange(1024, 65535)
        self.joinPortSpin.setValue(DEFAULT_PORT)
        self.joinPortSpin.lineEdit().returnPressed.connect(self._do_join)
        layout.addWidget(self.joinPortSpin, 4, 1)
        self.joinButton = QPushButton(strings[8])
        self.joinButton.clicked.connect(self._do_join)
        layout.addWidget(self.joinButton, 5, 0, 1, 2)
        group.setLayout(layout)
        return group

    def _build_lobby_group(self):
        strings = Local.strings[Local.MULTIPLAYER]
        group = QGroupBox(strings[49])
        layout = QVBoxLayout()
        self.lobbyLabel = QLabel(strings[28])
        self.lobbyLabel.setWordWrap(True)
        layout.addWidget(self.lobbyLabel)

        self.readyButton = QPushButton(strings[29])
        self.readyButton.setCheckable(True)
        self.readyButton.clicked.connect(lambda: self._set_ready(self.readyButton.isChecked()))
        self.startButton = QPushButton(strings[13])
        self.startButton.setObjectName("primary")
        self.startButton.clicked.connect(self._do_start)
        self.leaveButton = QPushButton(strings[9])
        self.leaveButton.clicked.connect(self._do_leave)
        row = QHBoxLayout()
        row.addWidget(self.readyButton)
        row.addWidget(self.startButton)
        row.addStretch(1)
        row.addWidget(self.leaveButton)
        layout.addLayout(row)

        layout.addWidget(QLabel(strings[14]))
        self.chatLog = QTextEdit()
        self.chatLog.setReadOnly(True)
        self.chatLog.setMaximumHeight(110)
        layout.addWidget(self.chatLog)
        chatRow = QHBoxLayout()
        self.chatEdit = QLineEdit()
        self.chatEdit.returnPressed.connect(self._do_chat)
        self.chatSend = QPushButton(strings[15])
        self.chatSend.clicked.connect(self._do_chat)
        chatRow.addWidget(self.chatEdit, 1)
        chatRow.addWidget(self.chatSend)
        layout.addLayout(chatRow)

        group.setLayout(layout)
        return group

    # -- fallbacks: a shared folder, and a report ---------------------------

    def _build_mail_group(self):
        """Play-by-mail: the turn is a file, and the folder is the wire."""
        group = QGroupBox("Play by mail (shared folder)")
        layout = QVBoxLayout()
        hint = QLabel(
            "For networks where machines cannot open a connection to each "
            "other, but a shared drive is visible. A turn is one file; the "
            "other player picks it up from the same folder. Use one subfolder "
            "per pair (for example \\\\TEACHER\\bop-mail\\pair07). One player "
            "presses Create game and tells the other the game code that "
            "appears; the other types it and presses Open mailbox.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        layout.addWidget(hint)

        folderRow = QHBoxLayout()
        self.mailFolder = QLineEdit()
        self.mailFolder.setPlaceholderText("\\\\server\\share\\bop  or  /mnt/share/bop")
        self.mailBrowse = QPushButton("Browse\u2026")
        self.mailBrowse.clicked.connect(self._browse_mail_folder)
        folderRow.addWidget(self.mailFolder, 1)
        folderRow.addWidget(self.mailBrowse)
        layout.addLayout(folderRow)

        nameRow = QHBoxLayout()
        nameRow.addWidget(QLabel("Game code"))
        # Empty on purpose: a default shared by every PC made two pairs in the
        # same folder load each other's opening position.
        self.mailName = QLineEdit("")
        self.mailName.setPlaceholderText("leave empty to create a new game")
        self.mailName.setToolTip("The creator leaves this empty and presses Create "
                                 "game: a code is made up and shown. The other "
                                 "player must type exactly that code. It is what "
                                 "tells this game's files apart from anybody "
                                 "else's.")
        nameRow.addWidget(self.mailName, 1)
        layout.addLayout(nameRow)
        self.mailCode = QLabel()
        self.mailCode.setWordWrap(True)
        self.mailCode.setTextFormat(Qt.RichText)
        self.mailCode.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.mailCode)

        buttons = QHBoxLayout()
        self.mailOpen = QPushButton("Open mailbox")
        self.mailOpen.clicked.connect(self._do_mail_open)
        self.mailCreate = QPushButton("Create game")
        self.mailCreate.setToolTip("Write the starting position into the folder "
                                   "and keep the first turn for yourself.")
        self.mailCreate.clicked.connect(self._do_mail_create)
        self.mailSend = QPushButton("Send my turn")
        self.mailSend.clicked.connect(self._do_mail_send)
        self.mailLoad = QPushButton("Load their move")
        self.mailLoad.clicked.connect(self._do_mail_load)
        for button in (self.mailOpen, self.mailCreate, self.mailSend, self.mailLoad):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.mailStatus = QLabel("No mailbox is open.")
        self.mailStatus.setWordWrap(True)
        self.mailStatus.setTextFormat(Qt.RichText)
        layout.addWidget(self.mailStatus)
        group.setLayout(layout)
        return group

    def _build_diagnostics_group(self):
        """The button that replaces reading the log with a torch."""
        group = QGroupBox("Connection test")
        layout = QVBoxLayout()
        hint = QLabel("Checks the port, the peer and UDP discovery, and writes "
                      "the answer into the log below.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.testButton = QPushButton("Test connection")
        self.testButton.clicked.connect(self._do_test_connection)
        row.addWidget(self.testButton)
        self.testHint = QLabel()
        self.testHint.setWordWrap(True)
        self.testHint.setTextFormat(Qt.PlainText)
        self.testHint.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        row.addWidget(self.testHint, 1)
        layout.addLayout(row)
        layout.addStretch(1)
        group.setLayout(layout)
        return group

    # -- session wiring -----------------------------------------------------

    def _connect_session(self):
        session = self.session
        session.lobbyChanged.connect(self._on_lobby)
        session.peerConnected.connect(self._on_peer_connected)
        session.peerReconnected.connect(self._on_peer_reconnected)
        session.peerDisconnected.connect(self._on_peer_disconnected)
        session.chatReceived.connect(self._on_chat)
        session.statusMessage.connect(self._on_status)
        session.errorOccurred.connect(self._on_error)
        session.gameStarted.connect(self._on_game_started)

    def _disconnect_session(self):
        session = self.session
        for signal, slot in ((session.lobbyChanged, self._on_lobby),
                             (session.peerConnected, self._on_peer_connected),
                             (session.peerReconnected, self._on_peer_reconnected),
                             (session.peerDisconnected, self._on_peer_disconnected),
                             (session.chatReceived, self._on_chat),
                             (session.statusMessage, self._on_status),
                             (session.errorOccurred, self._on_error),
                             (session.gameStarted, self._on_game_started)):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    # -- actions ------------------------------------------------------------

    def _selected_side(self):
        return SIDE_USA if self.sideUSA.isChecked() else SIDE_USSR

    def _relay_toggled(self, checked):
        self.relayEdit.setEnabled(checked and not self.session.is_online)
        self.portSpin.setEnabled(not checked and not self.session.is_online)

    def _refresh_address_label(self):
        """Show this PC's address(es) so the player can read them out."""
        ips, text, warning = self._addresses
        if not ips:
            self.addressLabel.setText("<span style='color:%s'>%s</span>"
                                      % (Palette.ACCENT.name(), html.escape(warning)))
            return
        label = "Your address: <b>%s</b>" % html.escape(text)
        if warning:
            label += ("<br><span style='color:%s'>%s</span>"
                      % (Palette.TEXT_MUTED.name(), html.escape(warning)))
        self.addressLabel.setText(label)

    def _parse_relay(self):
        """``(address, port)`` from the relay field; ValueError says what is wrong."""
        text = self.relayEdit.text().strip()
        address, _, port = text.rpartition(":")
        address = address.strip()
        if not address or not port.strip().isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("Type the relay as address:port, for example "
                             "192.168.1.5:46003 (your teacher gives you both).")
        return address, int(port)

    def _do_host(self):
        name, side = self.nameEdit.text(), self._selected_side()
        if self.relayCheck.isChecked():
            try:
                address, port = self._parse_relay()
            except ValueError as exc:
                self._append_chat(None, str(exc))
                return
            if self.session.host_via_relay(address, port, name, side):
                self._append_chat(None, "Hosting through the relay at %s:%d. "
                                        "Tell your opponent to join %s, port %d."
                                  % (address, port, address, port))
                self.hostHint.setText(
                    "You are hosting through the relay. Tell your opponent to "
                    "join <b>%s</b> port <b>%d</b>; the game starts when they "
                    "have joined and pressed ready."
                    % (html.escape(address), port))
            self._update_controls()
            return
        port = self.portSpin.value()
        self.parent.last_port = port
        if self.session.host(port, name, side):
            self._addresses = self._fresh_addresses()
            self._refresh_address_label()
            ips, _text, warning = self._addresses
            self._append_chat(None, Local.strings[Local.MULTIPLAYER][10])
            self.hostHint.setText(Local.strings[Local.MULTIPLAYER][22])
            if ips:
                shown = ", ".join(ips)
                self.hostHint.setText(
                    "You are hosting. Tell your opponent to type: <b>%s</b> "
                    "port <b>%d</b>. The game starts when they have joined and "
                    "pressed ready." % (html.escape(shown), port))
                self._append_chat(None, "Your address for the opponent: %s, port %d"
                                  % (shown, port))
            elif warning:
                self._append_chat(None, warning)
            if not self.beacon.start(self._game_info):
                self._append_chat(None, "Others will not see this game in the "
                                        "list (UDP %d is busy%s). Tell them your "
                                        "address and port instead."
                                  % (DISCOVERY_PORT,
                                     ": " + self.beacon.error if self.beacon.error else ""))
        self._update_controls()

    def _fresh_addresses(self):
        try:
            return address_summary(local_addresses())
        except Exception:
            return self._addresses

    def _address_edited(self, _text):
        self.gameList.clearSelection()
        self.gameList.setCurrentItem(None)

    def _do_join(self):
        item = self.gameList.currentItem()
        if item is not None:
            address = item.data(Qt.UserRole) or self.addressEdit.text()
            port = item.data(Qt.UserRole + 1) or self.joinPortSpin.value()
            self.addressEdit.setText(str(address))
            self.joinPortSpin.setValue(int(port))
        address = self.addressEdit.text().strip()
        if not address:
            self._append_chat(None, "Type the host's address first (or pick a "
                                    "game from the list), then press Join.")
            self.addressEdit.setFocus()
            return
        # "Connected" is only written once the host has answered the handshake
        # (see _on_peer_connected); the session reports "Connecting to ..." and
        # then the real reason if it fails.
        self.session.join(address, self.joinPortSpin.value(),
                          self.nameEdit.text(), self._selected_side())
        self._update_controls()

    def _do_start(self):
        if not (self.session.is_host and self.session.peer_ready):
            return
        side = self.session.local_side
        self.session.start_game({
            "level": self.parent.last_level,
            "host_side": side,
            "guest_side": 1 - side,
            "host_name": self.session.local_name,
            "guest_name": self.session.peer_name,
        })

    def _do_leave(self):
        self.session.close()
        self.beacon.stop()
        self._update_controls()

    def _set_ready(self, ready):
        self.session.set_ready(ready)
        self.readyButton.setText(Local.strings[Local.MULTIPLAYER][29] if not ready
                                 else Local.strings[Local.MULTIPLAYER][9])
        self._update_controls()

    def _do_chat(self):
        text = self.chatEdit.text().strip()
        if not text:
            return
        self.chatEdit.clear()
        self.session.send_chat(text)
        self._append_chat(self.session.local_name, text)

    def _refresh_games(self):
        self._games.clear()
        self.gameList.clear()
        self.browser.stop()
        if self.browser.start():
            self._append_chat(None, Local.strings[Local.MULTIPLAYER][23])
        else:
            self._append_chat(None, Local.strings[Local.MULTIPLAYER][51])

    def _game_info(self):
        """Answer discovery probes while we are hosting."""
        return {
            "id": self.session.game_id,
            "name": self.session.local_name,
            "level": self.parent.last_level,
            "players": len(self.session.lobby()),
            "port": self.portSpin.value(),
            "host": socket.gethostname()[:24],
            "ready": self.session.peer_ready,
        }

    # -- play by mail -------------------------------------------------------

    def _browse_mail_folder(self):
        start = self.mailFolder.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the shared folder for this game", start)
        if chosen:
            self.mailFolder.setText(chosen)

    def _mail_folder(self, generate=False):
        """Validate the folder and name, complaining politely when they are off.

        ``generate`` is for the player who creates the game: an empty name
        becomes a fresh code.  The joining player never gets one, so a mistyped
        or missing code cannot silently land them in somebody else's game.
        """
        folder = self.mailFolder.text().strip()
        if not folder:
            QMessageBox.information(self, "Play by mail",
                                    "Choose the shared folder first: the one both "
                                    "players can see.")
            return None
        name = self.mailName.text().strip()
        if not name and generate:
            name = new_game_code(self.nameEdit.text())
            self.mailName.setText(name)
        if not name:
            QMessageBox.information(self, "Play by mail",
                                    "Type the game code your partner gave you. "
                                    "(If you are the one starting the game, press "
                                    "Create game and a code is made for you.)")
            return None
        return folder, name

    def _do_mail_open(self):
        picked = self._mail_folder()
        if not picked:
            return
        folder, name = picked
        side = self._selected_side()
        try:
            # Normalise first ("game 1" -> "game-1"): the progress marker is
            # named after the code, and must be the same one every time.
            raw = name
            name = normalize_game_code(name)
            self.mail.open(folder, name, side,
                           marker_path=default_marker_path(name, side, folder),
                           interval_ms=DEFAULT_POLL_MS,
                           # Markers of the previous build had no folder hash.
                           legacy_markers=legacy_marker_paths(side, raw, name))
        except MailError as exc:
            QMessageBox.warning(self, "Play by mail", str(exc))
            return
        self._mail_status = {}
        # Show the code as it will really be used (spaces become "-").
        self.mailName.setText(self.mail.session.game_id)
        name = self.mail.session.game_id
        self._append_chat(None, "Watching %s for game \u201c%s\u201d as %s."
                          % (folder, name,
                             "USA" if side == SIDE_USA else "USSR"))
        self._refresh_mail_status()

    def _do_mail_create(self):
        """Publish the opening position, then keep the first turn."""
        world = getattr(self.parent, "world", None)
        if world is not None and (world.winFlag or world.ANWFlag or world.NWFlag):
            # After start-up the loaded world can be the finished 1990 autosave;
            # exporting it would make the end of one game "move 1" of another.
            QMessageBox.information(
                self, "Play by mail",
                "The game that is loaded has finished, so it cannot be the start "
                "of a new mail game. Start a New game first (File > New game), "
                "then open Multiplayer again and press Create game.")
            return
        picked = self._mail_folder(generate=True)
        if not picked:
            return
        if self.mail.session is None:
            self._do_mail_open()
            if self.mail.session is None:
                return
        side = self.mail.session.local_side
        if world is not None and side in (0, 1) and int(world.human) != int(side):
            # The creator chose the other superpower than the one on the board:
            # the file says that side is to move, so the position must agree.
            world.changeSides()
            self.parent.local_side = int(side)
        state = self._export_state()
        try:
            move = self.mail.session.start_game(
                state, turn=getattr(self.parent, "turn_counter", None),
                game_name=self.mailName.text().strip())
        except Exception as exc:
            QMessageBox.warning(self, "Play by mail", "%s" % exc)
            return
        self._enter_mail_mode()
        try:
            self.parent.setStatus(-1)
            self.parent.refresh_ui()
        except AttributeError:
            pass
        code = self.mail.session.game_id
        self.mailCode.setText("Game code to give your partner: <b>%s</b>"
                              % html.escape(code))
        self._append_chat(None, "Opening position written as %s. Tell your partner "
                               "the game code %s. Play your turn, then press "
                               "\u201cSend my turn\u201d." % (move.name, code))
        self._refresh_mail_status()

    def _export_state(self):
        """The live world as a snapshot document (no session needed)."""
        return world_to_state(self.parent.world)

    def _do_mail_send(self):
        if self.mail.session is None:
            QMessageBox.information(self, "Play by mail", "Open a mailbox first.")
            return
        try:
            move = self.mail.submit(self._export_state(),
                                    turn=getattr(self.parent, "turn_counter", None),
                                    game_name=self.mailName.text().strip())
        except MailError as exc:
            QMessageBox.warning(self, "Play by mail", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Play by mail",
                                "The turn could not be written: %s" % exc)
            return
        self._enter_mail_mode()
        if getattr(move, "game_over", False):
            self._append_chat(None, "Sent %s: the final move. The game is over; "
                                    "your opponent will see the result when they "
                                    "load it." % move.name)
        else:
            self._append_chat(None, "Sent %s. It is now %s's turn."
                              % (move.name, move.to_move or "your opponent"))
        # Do not wait for the next poll to learn that the move went out: the
        # stale status still says "your turn" and would keep Send enabled for a
        # second click.  (Sending the same position twice is harmless anyway --
        # Net.MailGame returns the move that is already there.)
        self._mail_status = dict(self._mail_status or {}, my_turn=False)
        self._refresh_mail_status()

    def _do_mail_load(self):
        if self.mail.session is None:
            QMessageBox.information(self, "Play by mail", "Open a mailbox first.")
            return
        from Dialog.GameTransfer import resync_window
        world = getattr(self.parent, "world", None)
        try:
            try:
                move = self.mail.apply_next(world)
            except MailForkError as exc:
                # Both of you moved from the same position.  Loading theirs
                # discards the move already made here: only on a clear yes.
                answer = QMessageBox.question(
                    self, "Play by mail",
                    "%s\n\nLoad their move and discard yours?" % exc,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                self._append_chat(None, "Mailbox: %s" % exc)
                if answer != QMessageBox.Yes:
                    return
                move = self.mail.apply_next(world, replace_own=True)
        except MailError as exc:
            QMessageBox.information(self, "Play by mail", str(exc))
            self._append_chat(None, "Mailbox: %s" % exc)
            return
        except Exception as exc:
            QMessageBox.warning(self, "Play by mail",
                                "That move could not be read: %s" % exc)
            return
        # The position was applied in place (so the map keeps its polygons);
        # the window's own bookkeeping still has to catch up with it.
        # Mail mode first: the refresh inside resync_window must already know
        # this is play by mail (no "Pass to ..." hot-seat button, turn gating).
        self._enter_mail_mode()
        resync_window(self.parent, world, self.mail.session.local_side)
        self._append_chat(None, "Loaded %s. You are %s; it is %s's turn."
                          % (move.name, self.mail.session.local_name,
                             move.to_move or "?"))
        self._refresh_mail_status()

    def _enter_mail_mode(self):
        """Tell the main window this is a play-by-mail game (no crisis duels)."""
        try:
            self.parent.mail_mode = True
            # Kept in the world too, so a mail game resumed with Continue (the
            # autosave) is still one, not a hot-seat game.
            self.parent.world.mailGame = True
            # And which side this machine plays: after a move the world is
            # handed to the opponent (``world.human`` flips), so Continue cannot
            # tell from the position alone who is sitting here.
            if self.mail.session is not None and self.mail.session.local_side in (0, 1):
                self.parent.world.mailSide = int(self.mail.session.local_side)
        except AttributeError:
            pass

    def _on_mail_status(self, status):
        if self.mail.session is None:
            return                      # a late answer from a closed mailbox
        self._mail_status = status
        for problem in status.get("new_problems") or ():
            self._append_chat(None, "Mailbox problem: %s" % problem.describe())
        conflict = status.get("conflict")
        if conflict and conflict.get("message") != getattr(self, "_mail_conflict", None):
            self._mail_conflict = conflict.get("message")
            self._append_chat(None, "Conflict: %s" % conflict["message"])
        self._refresh_mail_status()

    def _refresh_mail_status(self):
        status = self._mail_status
        if not status or self.mail.session is None:
            self.mailStatus.setText("No mailbox is open.")
        elif not status.get("ok"):
            self.mailStatus.setText("<b>Mailbox unavailable:</b> %s"
                                    % html.escape(str(status.get("message", "?"))))
        else:
            to_move = html.escape(str(status.get("to_move") or "nobody yet"))
            mine = status.get("my_turn")
            colour = Palette.ACCENT.name() if mine else Palette.TEXT_MUTED.name()
            lines = []
            if not status.get("latest_seq"):
                lines.append("No game with this code is in this folder yet. "
                             "Check the code and the folder with your partner.")
            lines += ["<b>The folder holds move %s</b>; you have loaded move %s. "
                     "<span style='color:%s'><b>%s to move</b></span>."
                     % (status.get("latest_seq", 0), status.get("applied_seq", 0),
                        colour, to_move)]
            if status.get("game_over"):
                if status.get("pending"):
                    lines.append("<b>The game is over.</b> The last move is in "
                                 "the folder; load it to see the result. No "
                                 "further move can be sent.")
                else:
                    lines.append("<b>The game is over.</b> No further move can "
                                 "be sent.")
            theirs = status.get("theirs")
            if theirs is not None:
                lines.append("Your opponent last moved on %s (%s)."
                             % (html.escape(str(status.get("theirs_when") or "?")),
                                html.escape(theirs.name)))
            if status.get("pending"):
                count = status.get("pending_count", 0)
                if count == 1:
                    lines.append("1 move waiting to be loaded.")
                else:
                    lines.append("%d moves waiting to be loaded." % count)
            self.mailStatus.setText("<br>".join(lines))
        self._update_controls()

    # -- diagnostics --------------------------------------------------------

    def _do_test_connection(self):
        """Run the checks off the GUI thread and report them in the log.

        ``run_blocking`` keeps the event loop turning while the worker waits on
        sockets, so the window keeps painting and the button can be disabled for
        the duration instead of the whole interface freezing.
        """
        if self._diagnosing:
            return
        self._diagnosing = True
        self.testButton.setEnabled(False)
        self.testHint.setText("Testing\u2026")
        session = self.session
        if self.session.is_online:
            port = self.session.port
        else:
            port = self.portSpin.value()
        peer = self.addressEdit.text().strip()
        if not peer and getattr(session, "is_connected", False):
            peer = getattr(session, "peer_address", "")
        expect_beacon = self.beacon.running
        try:
            report = run_blocking(
                lambda: diagnose(port, peer=peer, session=session,
                                 expect_beacon=expect_beacon),
                timeout=12.0, parent=self)
        except Exception as exc:
            self._append_chat(None, "Connection test failed to run: %s" % exc)
            self.testHint.setText("could not run")
            return
        finally:
            self._diagnosing = False
            self.testButton.setEnabled(True)
        for line in report.lines():
            self._append_chat(None, line)
        self._append_chat(None, report.summary())
        self.testHint.setText(report.summary())

    # -- session callbacks --------------------------------------------------

    def _on_game_found(self, game):
        # Keyed by where the game can be joined, never by its self-reported id:
        # two hosts with the same defaults used to share one row.
        key = game.get("key") or game_key(game)
        if not key:
            return
        self._games[key] = game
        self._rebuild_game_list()

    def _on_game_lost(self, key):
        self._games.pop(key, None)
        self._rebuild_game_list()

    def _rebuild_game_list(self):
        # Discovery answers every 2 s; keep the player's pick across rebuilds.
        current = self.gameList.currentItem()
        selected = current.data(Qt.UserRole + 2) if current is not None else None
        self.gameList.clear()
        for key, game in self._games.items():
            host = str(game.get("host") or "")
            label = "%s%s  %s:%d  (%d/2)" % (
                game.get("name") or "?", "  [%s]" % host if host else "",
                game.get("address"), game.get("port", DEFAULT_PORT),
                game.get("players", 1))
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, game.get("address"))
            item.setData(Qt.UserRole + 1, game.get("port", DEFAULT_PORT))
            item.setData(Qt.UserRole + 2, key)
            self.gameList.addItem(item)
            if key == selected:
                self.gameList.setCurrentItem(item)

    def _on_lobby(self, players):
        strings = Local.strings[Local.MULTIPLAYER]
        lines = []
        for entry in players:
            side = Local.strings[Local.DATA_COUNTRIES + entry["side"]][Local.CTRY_NAME]
            mark = "\u2714" if entry["ready"] else "\u2026"
            tag = "(you)" if entry["local"] else ""
            lines.append("%s <b>%s</b>: %s %s" % (mark, html.escape(str(entry["name"])),
                                                  html.escape(side), tag))
        self.lobbyLabel.setText("<br>".join(lines) or strings[50])
        self._update_controls()

    def _on_peer_connected(self, info):
        self._on_lobby(self.session.lobby())
        if self.session.is_client:
            # The host answered the handshake: only now is it true.
            self._append_chat(None, Local.strings[Local.MULTIPLAYER][11]
                              % ("%s (%s:%d)" % (info.get("name", "?"),
                                                 self.session.host_address,
                                                 self.session.host_port)))
            return
        self._append_chat(None, Local.strings[Local.MULTIPLAYER][24] % info.get("name", "?"))

    def _on_peer_reconnected(self, info):
        self._on_lobby(self.session.lobby())
        # A reconnect is deliberately *not* treated as a new player: the game
        # kept running, and the host has just re-sent the current position.
        self._append_chat(None, "%s is back. The game continued from the "
                                "turn it was on." % info.get("name", "?"))

    def _on_peer_disconnected(self, reason):
        self._on_lobby(self.session.lobby())
        if self.session.reconnecting:
            self._append_chat(None, "%s (%s). Waiting for them to come back."
                              % (Local.strings[Local.MULTIPLAYER][25], reason))
        else:
            self._append_chat(None, "%s (%s)"
                              % (Local.strings[Local.MULTIPLAYER][25], reason))
        self._update_controls()

    def _on_chat(self, name, text):
        self._append_chat(name, text)

    def _on_status(self, text):
        self._append_chat(None, text)

    def _on_error(self, text):
        self._append_chat(None, Local.strings[Local.MULTIPLAYER][32] % text)
        if not self.session.is_online:
            # A join that failed must not leave the last roster on screen.
            self._on_lobby(self.session.lobby())

    def _on_game_started(self, settings):
        # The main window owns the actual start-up; the lobby just gets out of
        # the way.  (Its own signal handler runs after the main window's.)
        self.beacon.stop()
        self.browser.stop()
        self.accept()

    def _append_chat(self, name, text):
        if not text:
            return
        # Names and messages come from the other machine: never markup.
        text = html.escape(str(text))
        if name:
            self.chatLog.append("<b style='color:%s'>%s:</b> %s"
                                % (Palette.ACCENT.name(), html.escape(str(name)), text))
        else:
            self.chatLog.append("<i style='color:%s'>%s</i>"
                                % (Palette.TEXT_MUTED.name(), text))

    # -- state --------------------------------------------------------------

    def _update_controls(self):
        session = self.session
        online = session.is_online
        # ``is_connected`` includes the reconnect grace window on purpose (so
        # the game does not fork into a local one); the lobby, which must not
        # claim a peer it cannot see, asks the honest question instead.
        connected = session.peer_online
        hosting = session.is_host
        self.hostButton.setEnabled(not online)
        self.portSpin.setEnabled(not online and not self.relayCheck.isChecked())
        self.relayCheck.setEnabled(not online)
        self.relayEdit.setEnabled(not online and self.relayCheck.isChecked())
        self.joinButton.setEnabled(not online)
        self.gameList.setEnabled(not online)
        self.addressEdit.setEnabled(not online)
        self.joinPortSpin.setEnabled(not online)
        self.refreshButton.setEnabled(not online)
        self.nameEdit.setEnabled(not online)
        self.sideUSA.setEnabled(not online)
        self.sideUSSR.setEnabled(not online)
        self.readyButton.setEnabled(connected)
        self.readyButton.setChecked(session.local_ready)
        self.readyButton.setText(Local.strings[Local.MULTIPLAYER][9] if session.local_ready
                                 else Local.strings[Local.MULTIPLAYER][29])
        self.startButton.setEnabled(hosting and session.peer_ready)
        self.chatSend.setEnabled(connected)
        self.chatEdit.setEnabled(connected)
        self.leaveButton.setEnabled(online)
        if session.reconnecting:
            self.leaveButton.setToolTip("Give up on the reconnection and end the "
                                        "game")
        else:
            self.leaveButton.setToolTip("")
        self._update_mail_controls()

    def _update_mail_controls(self):
        """Enable the mail buttons for the state the folder is actually in."""
        session = self.mail.session
        status = self._mail_status or {}
        open_mailbox = session is not None
        pending = bool(status.get("pending"))
        # Two competing moves are a decision only a human can make… except when
        # the fork is *ours*: one of the two files is the move already made on
        # this machine, so loading the other one is the way out, not a guess.
        ambiguous = bool(status.get("conflict")) and status.get("pending_count", 0) > 1
        self.mailOpen.setEnabled(True)
        # Before a mailbox is open, "Create game" opens one itself (and makes up
        # the game code if the field is empty), so it must be available then.
        self.mailCreate.setEnabled(not open_mailbox
                                   or status.get("latest_seq", 0) == 0)
        self.mailSend.setEnabled(open_mailbox and bool(status.get("my_turn"))
                                 and not status.get("conflict"))
        self.mailLoad.setEnabled(open_mailbox and pending and not ambiguous)
        self.mailStatus.setToolTip(status.get("folder", ""))

    # -- lifecycle ----------------------------------------------------------

    def closeEvent(self, event):
        self.browser.stop()
        self.mail.close()
        self._mail_status = {}
        if not self.session.is_connected:
            self.beacon.stop()
        self._disconnect_session()
        event.accept()

    def reject(self):
        self.browser.stop()
        self.mail.close()
        self._mail_status = {}
        if not self.session.is_connected:
            self.beacon.stop()
        self._disconnect_session()
        super().reject()
