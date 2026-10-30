"""
Zero-configuration LAN discovery.

A host broadcasts nothing; a player looking for a game sends a small UDP probe
to the broadcast address and every host on the subnet answers with a one-line
description of its game.  That is enough for two people on the same Wi-Fi to
find each other without typing an IP address, while the manual "connect to
address" field remains available for routed or unusual networks.
"""

import json
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QHostAddress, QUdpSocket

from Net import DISCOVERY_MAGIC, DISCOVERY_PORT

#: How often a browsing client repeats its probe.
PROBE_INTERVAL_MS = 2000
#: A host is dropped from the list if it has not answered for this long.
GAME_TIMEOUT_S = 7.0


def game_key(game):
    """Identity of a listed game: where it can be joined, ``"address:port"``.

    Not the game's self-reported id.  Every student's PC used to answer with
    the same default id, so two hosts collapsed into one row and the list
    showed whichever answered last.  Two machines can never share an
    address and port, which makes this the one key that cannot collide.
    """
    try:
        port = int(game.get("port"))
    except (TypeError, ValueError):
        return ""
    address = game.get("address")
    return "%s:%d" % (address, port) if address else ""


class DiscoveryBeacon(QObject):
    """Answers discovery probes so other players can find this host."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._socket = QUdpSocket(self)
        self._info_provider = None
        self._running = False
        #: Why the last start() failed, in words for the lobby.
        self.error = ""
        self._socket.readyRead.connect(self._on_ready_read)

    def start(self, info_provider):
        """``info_provider`` returns a JSON-able dict describing the game."""
        self._info_provider = info_provider
        if self._running:
            return True
        ok = self._socket.bind(QHostAddress.AnyIPv4, DISCOVERY_PORT,
                               QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint)
        if not ok:
            # Another instance on this machine already owns the port; the game
            # is still perfectly playable through a typed-in address.  The
            # caller must say so: otherwise the host waits for a guest who
            # cannot see the game in their list.
            self.error = self._socket.errorString()
            return False
        self.error = ""
        self._running = True
        return True

    @property
    def running(self):
        """True while this beacon is answering probes (for diagnostics)."""
        return self._running

    def stop(self):
        if self._running:
            self._socket.close()
            self._running = False

    def _on_ready_read(self):
        while self._socket.hasPendingDatagrams():
            datagram, sender, sender_port = self._socket.readDatagram(
                self._socket.pendingDatagramSize())
            try:
                message = json.loads(bytes(datagram).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                continue
            if not isinstance(message, dict):
                continue
            if message.get("magic") != DISCOVERY_MAGIC or not message.get("probe"):
                continue
            if self._info_provider is None:
                continue
            reply = {"magic": DISCOVERY_MAGIC, "probe": False,
                     "game": self._info_provider()}
            payload = json.dumps(reply).encode("utf-8")
            self._socket.writeDatagram(payload, sender, sender_port)


class DiscoveryBrowser(QObject):
    """Finds games on the local network."""

    gameFound = pyqtSignal(dict)
    gameLost = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._socket = QUdpSocket(self)
        self._known = {}
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(PROBE_INTERVAL_MS)
        self._timer.timeout.connect(self._probe)
        self._socket.readyRead.connect(self._on_ready_read)

    def start(self):
        if self._running:
            return True
        ok = self._socket.bind(QHostAddress.AnyIPv4, 0,
                               QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint)
        if not ok:
            return False
        self._running = True
        self._probe()
        self._timer.start()
        return True

    def stop(self):
        self._timer.stop()
        if self._running:
            self._socket.close()
            self._running = False
        self._known.clear()

    def _probe(self):
        self._expire()
        payload = json.dumps({"magic": DISCOVERY_MAGIC, "probe": True}).encode("utf-8")
        self._socket.writeDatagram(payload, QHostAddress.Broadcast, DISCOVERY_PORT)

    def _expire(self):
        now = time.monotonic()
        for key in [k for k, v in self._known.items()
                    if now - v["seen"] > GAME_TIMEOUT_S]:
            del self._known[key]
            self.gameLost.emit(key)

    def _on_ready_read(self):
        while self._socket.hasPendingDatagrams():
            datagram, sender, _ = self._socket.readDatagram(
                self._socket.pendingDatagramSize())
            try:
                message = json.loads(bytes(datagram).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                continue
            if not isinstance(message, dict):
                continue
            if message.get("magic") != DISCOVERY_MAGIC or message.get("probe", True):
                continue
            game = message.get("game")
            if not isinstance(game, dict):
                continue
            # Trust the datagram source over the self-reported address: a host
            # with several interfaces may not know which one reached us.
            sender_text = sender.toString()
            if sender_text.startswith("::ffff:"):
                sender_text = sender_text[7:]
            game["address"] = sender_text
            key = game_key(game)
            if not key:
                continue
            game["key"] = key
            game["seen"] = time.monotonic()
            self._known[key] = game
            self.gameFound.emit(dict(game))
