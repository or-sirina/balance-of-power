"""
The network session: sockets, the lobby, and replication of world state.

Only two players are supported, which matches the game: the two superpowers.
The host is authoritative — it owns the ``World`` and runs every rule — and the
guest holds a mirror that it refreshes from the host's snapshots.  That choice
removes a whole class of desynchronisation bugs (the game leans heavily on
``random``) and lets somebody join a game already in progress.

The session deliberately knows nothing about widgets.  It emits signals and
offers a few ``send_*`` methods; :class:`MainWindow.MainWindow` decides what
those mean for the game.

A dropped connection does not end the game any more.  Both ends enter a bounded
grace window: the guest redials, the host keeps its listening socket and waits.
Because the host is authoritative it can rebuild the guest from scratch, so the
last broadcast snapshot (and an unanswered crisis prompt) are kept and replayed
to whoever comes back.  The turn marker travels with the snapshot, which is what
lets a guest that reconnects mid-resolution wait for the turn it already asked
for instead of ending a second one.  ``Session.auto_reconnect = False`` restores
the old behaviour of ending the session on a drop.
"""

import collections
import hmac
import sys
import time
import traceback
import uuid

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

from Net import PROTOCOL_VERSION
from Net.Protocol import Action, FrameReader, Message, ProtocolError, encode_message

SIDE_USA = 0
SIDE_USSR = 1
DEFAULT_PORT = 45454
#: How long a socket may sit without a byte from the peer before we give up.
KEEPALIVE_INTERVAL_MS = 4000
#: A peer that has been silent this long (it answers every PING within
#: milliseconds, so this is generous) is treated as gone.  Without it a pulled
#: cable or a closed laptop lid is only noticed when the operating system
#: gives up on the connection, which is minutes to hours.
PEER_SILENCE_S = 30.0

#: A guest redials this often after losing the host…
CLIENT_RECONNECT_MS = 2500
#: …and gives up after this long, which is long enough to survive a Wi-Fi roam
#: or a switch port bouncing, and short enough that a dead host is reported
#: rather than waited on forever.
CLIENT_RECONNECT_GRACE_S = 30.0
#: The host keeps the game and its listening socket alive this long.  It is the
#: longer of the two on purpose: the whole point is that the guest comes back.
HOST_RECONNECT_MS = 5000
HOST_RECONNECT_GRACE_S = 120.0

#: How long a TCP connect may take before we say so.  The operating system's
#: own limit is ~21 s on Windows and minutes elsewhere; a firewall that silently
#: drops the SYN looks exactly like a slow network for that whole time.  A LAN
#: connect completes in milliseconds, so 8 s is already generous.
CONNECT_TIMEOUT_MS = 8000
#: A socket that is connected but whose peer has not completed the handshake
#: (for example a guest waiting in the relay for a host that has not started).
HANDSHAKE_NOTICE_MS = 8000
#: A host that cannot reach (or has lost) the relay tries again this often.
RELAY_REDIAL_MS = 3000
#: A connection to a listening host that has not produced a valid HELLO this
#: soon is not a player (a port probe, an antivirus scan, a browser).  Without a
#: limit such a connection held the only seat for the full silence limit, and
#: the real guest was told "the game is full".
UNIDENTIFIED_TIMEOUT_MS = 4000
#: The host's socket to its guest counts as dead for the purposes of a
#: token-less seat claim after this long without a byte (both ends ping every
#: 4 s, so a live guest is never this quiet).
STALE_SOCKET_S = 12.0
#: Bounds applied to a guest's policy request before the host looks at it.
MAX_POLICY = 8
MAX_POLICY_VALUE = 5
MAX_COUNTRY_INDEX = 255
#: The first bytes a host sends to a relay, so that the relay can tell a host
#: from a guest (whose first bytes are a HELLO frame) and from a stranger.  The
#: relay consumes the line; it is never forwarded.
RELAY_HOST_PREAMBLE = b"BOPR host\n"



def side_name(side):
    return "USA" if side == SIDE_USA else "USSR"


class Session(QObject):
    """A connection (or the absence of one) between two players."""

    MODE_OFFLINE = "offline"
    MODE_HOST = "host"
    MODE_CLIENT = "client"

    #: Emitted whenever the lobby contents change; payload is a list of dicts.
    lobbyChanged = pyqtSignal(list)
    #: A peer completed the handshake.  Payload: {"name", "side"}.
    peerConnected = pyqtSignal(dict)
    #: The peer went away.  Payload: a human-readable reason.
    peerDisconnected = pyqtSignal(str)
    #: The host started the game.  Payload: game settings.
    gameStarted = pyqtSignal(dict)
    #: A player who had been here before came back.  Payload: {"name", "side"}.
    peerReconnected = pyqtSignal(dict)
    #: The session lost its peer and is trying to get it back.  Payload: bool.
    reconnectingChanged = pyqtSignal(bool)
    #: Host -> guest world snapshot.
    snapshotReceived = pyqtSignal(dict)
    #: Guest -> host intent.
    actionReceived = pyqtSignal(dict)
    #: Host asks the guest to answer a crisis.  Payload: crisis description.
    crisisPrompted = pyqtSignal(dict)
    #: Free-form chat line.
    chatReceived = pyqtSignal(str, str)
    #: Transient status text for the UI.
    statusMessage = pyqtSignal(str)
    #: Something went wrong; the payload is meant for the user.
    errorOccurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = self.MODE_OFFLINE
        self.local_name = "Player"
        self.local_side = SIDE_USA
        self.peer_name = ""
        self.peer_side = SIDE_USSR
        self.local_ready = False
        self.peer_ready = False
        self.game_id = ""
        self.settings = {}

        self._server = None
        self._socket = None
        #: ``(address, port)`` when this host dials out to a relay instead of
        #: listening (see ``tools/bop_relay.py``); ``None`` in a normal game.
        self._relay = None
        #: True once the relay has accepted us at least once, so that a later
        #: failure is "the relay blinked" rather than "the address was wrong".
        self._relay_seen = False
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)
        self._handshake_timer = QTimer(self)
        self._handshake_timer.setSingleShot(True)
        self._handshake_timer.timeout.connect(self._on_handshake_timeout)
        self._reader = FrameReader()
        self._keepalive = QTimer(self)
        self._keepalive.setInterval(KEEPALIVE_INTERVAL_MS)
        self._keepalive.timeout.connect(self._on_keepalive)
        self._closing = False
        self._last_rx = time.monotonic()

        # --- reconnection ---------------------------------------------------
        #: Set while a peer socket exists but we have not given up on a lost one.
        self._awaiting_peer = False
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._on_reconnect_timer)
        self._reconnect_deadline = 0.0
        self._reconnect_attempts = 0
        #: True when this session is dialling the host again (as opposed to the
        #: host waiting by its listening socket).
        self._rejoined = False
        self._host_address = ""
        self._host_port = DEFAULT_PORT
        #: The last snapshot the host broadcast, kept so that a guest who comes
        #: back — or one who joins a game already under way — can be handed the
        #: current position instead of an empty mirror.
        self._last_snapshot = None
        #: An outbound crisis prompt the guest has not answered yet.
        self._last_crisis = None
        self._crisis_marker = None
        self._out_turn = None
        #: Guest bookkeeping: an end-of-turn request may have been lost with the
        #: connection, and only a *newer* turn marker proves it was consumed.
        self._turn_marker = None
        self._end_turn_sent = False
        #: A second connection that has arrived but not yet said who it is.
        self._pending_socket = None
        self._pending_reader = FrameReader()
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._on_pending_timeout)
        #: True once the current socket's HELLO has been accepted (host side).
        self._identified = False
        self._hello_timer = QTimer(self)
        self._hello_timer.setSingleShot(True)
        self._hello_timer.timeout.connect(self._on_hello_timeout)
        #: Secret issued in WELCOME.  The guest keeps it in memory and shows it
        #: when it comes back; nobody else knows it.
        self._rejoin_token = ""
        #: Everything the sockets report is queued here and handed to the
        #: application from a zero-length timer, never from inside a socket's
        #: own signal (see :meth:`_post`).
        self._inbox = collections.deque()
        self._inbox_scheduled = False
        self._draining = False
        self._in_read = False
        #: Sockets that have been let go of but not yet destroyed.
        self._graveyard = set()
        #: Whether a dropped connection is worth waiting for.  On by default —
        #: a Wi-Fi roam should not cost anybody a game — and off restores the
        #: old behaviour, where a drop simply ended the session.
        self.auto_reconnect = True

    def _reset_reconnect(self):
        """Forget every trace of a previous connection (host()/join())."""
        self._reconnect_timer.stop()
        self._connect_timer.stop()
        self._handshake_timer.stop()
        self._awaiting_peer = False
        self._rejoined = False
        self._reconnect_attempts = 0
        self._reconnect_deadline = 0.0
        self._last_snapshot = None
        self._last_crisis = None
        self._crisis_marker = None
        self._out_turn = None
        self._turn_marker = None
        self._end_turn_sent = False
        self._identified = False
        self._rejoin_token = ""
        self._hello_timer.stop()
        self._drop_pending()

    # -- state --------------------------------------------------------------

    @property
    def is_online(self):
        return self.mode != self.MODE_OFFLINE

    @property
    def is_host(self):
        return self.mode == self.MODE_HOST

    @property
    def is_client(self):
        return self.mode == self.MODE_CLIENT

    @property
    def reconnecting(self):
        """True while a lost peer is still being waited for (or dialled)."""
        return self._awaiting_peer

    @property
    def peer_online(self):
        """The honest socket-level answer: is there a live connection?

        ``is_connected`` deliberately stays true through the grace window, so
        anything that must report the truth (the lobby, the diagnostics button)
        asks this instead.
        """
        if self._socket is None:
            return False
        if self.mode == self.MODE_CLIENT:
            return self._socket.state() == QAbstractSocket.ConnectedState
        if self._relay is not None:
            # Connected to the relay is not the same as having an opponent.
            return (self._socket.state() == QAbstractSocket.ConnectedState
                    and bool(self.peer_name))
        # A connection that has not said HELLO yet is not an opponent.
        return self._identified

    @property
    def is_connected(self):
        """True while a peer belongs to this session.

        That includes the reconnect grace window, in which the socket is gone
        but the session has not given up on it.  The distinction is not
        cosmetic: ``MainWindow`` treats a session that is not connected as
        *absent* and then happily lets the local player resolve a turn against a
        mirror nobody else has.  Reporting the grace window as connected makes
        the surviving side wait for the turn it is actually waiting on, which is
        what should happen while the line is being re-established.
        """
        if self._awaiting_peer:
            return True
        if self.mode == self.MODE_HOST:
            if self._relay is not None:
                return self.peer_online
            # ``peer_name`` is set once somebody has been identified; a socket
            # that has not said HELLO yet (a probe, a scanner) does not count,
            # but neither does a returning guest's brand-new connection make
            # the game look abandoned in the instant before its HELLO is read.
            return self._socket is not None and bool(self.peer_name)
        if self.mode == self.MODE_CLIENT:
            return self._socket is not None and self._socket.state() == QAbstractSocket.ConnectedState
        return False

    @property
    def is_listening(self):
        """True when this session's own TCP server is accepting connections.

        A host that dials out to a relay has no server and needs none; it is
        "listening" in the only sense that matters while the relay holds its
        connection.
        """
        if self._relay is not None:
            return (self._socket is not None
                    and self._socket.state() == QAbstractSocket.ConnectedState)
        return self._server is not None and self._server.isListening()

    @property
    def relay(self):
        """``(address, port)`` of the relay this host dials, else ``None``."""
        return self._relay

    @property
    def port(self):
        """The port this session listens on, or dialled."""
        if self._server is not None:
            return int(self._server.serverPort())
        return int(self._host_port)

    @property
    def host_address(self):
        return self._host_address

    @property
    def host_port(self):
        return int(self._host_port)

    @property
    def peer_address(self):
        """Where the peer's socket comes from, for the diagnostics report."""
        socket = self._socket
        if socket is None:
            return ""
        try:
            return str(socket.peerAddress().toString())
        except (AttributeError, RuntimeError):
            return ""

    def lobby(self):
        """The lobby as the UI wants to display it."""
        entries = [{
            "id": 0 if self.is_host else 1,
            "name": self.local_name,
            "side": self.local_side,
            "ready": self.local_ready,
            "local": True,
        }]
        if self.is_connected:
            entries.append({
                "id": 1 if self.is_host else 0,
                "name": self.peer_name or "?",
                "side": self.peer_side,
                "ready": self.peer_ready,
                "local": False,
            })
        return entries

    def _emit_lobby(self):
        self.lobbyChanged.emit(self.lobby())

    # -- hosting ------------------------------------------------------------

    def host(self, port=DEFAULT_PORT, name="Player", side=SIDE_USA, game_name=""):
        self.close()
        self.mode = self.MODE_HOST
        self.local_name = name or "Player"
        self.local_side = int(side)
        self.peer_side = 1 - self.local_side
        self.peer_name = ""
        self.peer_ready = False
        self.local_ready = False
        self.game_id = game_name or self._new_game_id(self.local_name, port)
        self._closing = False
        self._reset_reconnect()
        self._rejoin_token = uuid.uuid4().hex
        self._relay = None
        self._host_address = "0.0.0.0"
        self._host_port = int(port)

        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(QHostAddress.AnyIPv4, int(port)):
            message = self._server.errorString()
            self._server = None
            self.mode = self.MODE_OFFLINE
            self.errorOccurred.emit("Could not listen on port %d: %s" % (int(port), message))
            return False
        self._emit_lobby()
        return True

    @staticmethod
    def _new_game_id(name, port):
        """An id no other host instance shares.

        ``"Player@45454"`` is what every student gets by default, so two hosts
        on a lab network used to look like one game to anything keyed on it.  A
        short random suffix makes each hosting instance distinct.
        """
        return "%s@%d#%s" % (name, int(port), uuid.uuid4().hex[:6])

    def host_via_relay(self, address, port, name="Player", side=SIDE_USA,
                       game_name=""):
        """Host without listening: dial OUT to a relay and wait there.

        For networks where students cannot accept inbound connections from each
        other but can all reach the teacher's PC.  The guest joins the relay's
        address and room port exactly as it would join a host.
        """
        self.close()
        self.mode = self.MODE_HOST
        self.local_name = name or "Player"
        self.local_side = int(side)
        self.peer_side = 1 - self.local_side
        self.peer_name = ""
        self.peer_ready = False
        self.local_ready = False
        self.game_id = game_name or self._new_game_id(self.local_name, port)
        self._closing = False
        self._reset_reconnect()
        self._rejoin_token = uuid.uuid4().hex
        self._relay = (str(address), int(port))
        self._relay_seen = False
        self._host_address = str(address)
        self._host_port = int(port)
        self._emit_lobby()
        self.statusMessage.emit("Connecting to the relay at %s:%d\u2026"
                                % self._relay)
        self._dial()
        return True

    def _dial(self):
        """Open (another) outbound connection to the relay."""
        if self._relay is None or self._closing or self.mode != self.MODE_HOST:
            return
        socket = QTcpSocket(self)
        self._adopt_socket(socket)
        self._connect_timer.start(CONNECT_TIMEOUT_MS)
        socket.connectToHost(*self._relay)

    def _on_new_connection(self):
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        if self._socket is not None \
                and self._socket.state() != QAbstractSocket.ConnectedState:
            # The connection we hold is already dead (its "disconnected" is still
            # waiting in the queue): a returning guest got here first.  Treat it
            # as the drop it is, so the newcomer is handled like any other
            # return and the dead socket is released properly.
            if self._identified and not self._awaiting_peer and self.auto_reconnect:
                self._begin_reconnect("the connection to the other player was lost")
            else:
                self._drop_socket()
                self._reader.reset()
        if self._socket is not None and not self._identified:
            # The connection we are holding never said who it is (a port probe, a
            # scanner, a half-open attempt).  It must not keep the seat from the
            # next one: the newcomer replaces it.
            self._drop_socket()
            self._reader.reset()
        if self._socket is not None and self._socket.state() == QAbstractSocket.ConnectedState:
            # Hold the connection aside until its HELLO says who it is.  A guest
            # whose machine was unplugged comes back while our end of its old
            # socket still looks perfectly connected — TCP has no idea — and
            # refusing that as "the game is full" would lock the guest out until
            # the operating system's keepalive expired, if ever.
            if self._pending_socket is not None:
                self._refuse(self._pending_socket, "game is full")
            self._pending_socket = socket
            self._pending_reader = FrameReader()
            self._attach_socket(socket, pending=True)
            self._pending_timer.start(UNIDENTIFIED_TIMEOUT_MS)
            self.statusMessage.emit("A player is connecting\u2026")
            return
        self._adopt_socket(socket)
        self.statusMessage.emit("A player is connecting\u2026")

    # -- joining ------------------------------------------------------------

    def join(self, address, port=DEFAULT_PORT, name="Player", side=SIDE_USSR):
        self.close()
        self.mode = self.MODE_CLIENT
        self.local_name = name or "Player"
        self.local_side = int(side)
        self.peer_side = 1 - self.local_side
        self.peer_name = ""
        self.peer_ready = False
        self.local_ready = False
        self._closing = False
        self._reset_reconnect()
        self._relay = None
        self._host_address = str(address)
        self._host_port = int(port)

        self.statusMessage.emit("Connecting to %s:%d\u2026" % (address, int(port)))
        socket = QTcpSocket(self)
        self._adopt_socket(socket)
        self._connect_timer.start(CONNECT_TIMEOUT_MS)
        socket.connectToHost(address, int(port))
        return True

    # -- socket plumbing ----------------------------------------------------
    #
    # Nothing a socket reports reaches the application from inside that
    # socket's own signal.  The slots below only read bytes, cut them into
    # frames and *queue* what they found; a zero-length timer then delivers the
    # queue in order (see :meth:`_post`).  This matters because the application
    # is free to spin the event loop while it handles a message (MainWindow's
    # ``setStatus`` calls ``processEvents`` many times while a turn resolves),
    # and a nested loop that delivers "disconnected" for the very socket whose
    # ``readyRead`` is still on the stack used to destroy that socket
    # underneath Qt: a segmentation fault in ``QIODevice::channelReadyRead``.

    def _attach_socket(self, socket, pending=False):
        """Connect one socket's signals to this session."""
        if pending:
            socket.readyRead.connect(self._on_pending_ready_read)
            socket.disconnected.connect(self._on_pending_gone)
            socket.errorOccurred.connect(self._on_pending_error)
            return
        socket.readyRead.connect(self._on_ready_read)
        socket.disconnected.connect(self._on_disconnected)
        socket.errorOccurred.connect(self._on_socket_error)
        if self.mode == self.MODE_CLIENT:
            socket.connected.connect(self._on_connected)

    @staticmethod
    def _detach_socket(socket, pending=False):
        """Undo :meth:`_attach_socket` (all slots at once).

        ``disconnect()`` with no slot raises when nothing is connected, which is
        the normal case for a socket that never reached the state that would
        have connected the other end.
        """
        signals = [socket.readyRead, socket.disconnected, socket.errorOccurred]
        if not pending:
            signals.append(socket.connected)
        for signal in signals:
            try:
                signal.disconnect()
            except TypeError:
                pass

    def _post(self, socket, func, *args):
        """Queue ``func(socket, *args)`` for delivery outside any socket signal."""
        self._inbox.append((socket, func, args))
        if not self._inbox_scheduled:
            self._inbox_scheduled = True
            QTimer.singleShot(0, self._drain)

    def _drain(self):
        """Deliver queued socket events, in order, one at a time.

        Re-entrancy is refused rather than handled: a handler that spins the
        event loop can cause this to fire again, and the inner call simply
        returns — the outer loop is still running and will pick up whatever
        arrived, in the right order, as soon as the handler returns.  A message
        therefore never starts before the previous one has finished.
        """
        self._inbox_scheduled = False
        if self._draining:
            return
        self._draining = True
        try:
            while self._inbox:
                socket, func, args = self._inbox.popleft()
                try:
                    func(socket, *args)
                except Exception as exc:        # never let a slot kill the process
                    traceback.print_exc(file=sys.stderr)
                    try:
                        self.errorOccurred.emit("Internal error: %s" % exc)
                    except Exception:
                        pass
        finally:
            self._draining = False

    def _retire(self, socket, graceful=False):
        """Let go of a socket without destroying it where it stands.

        Its signals are already disconnected.  It is aborted and scheduled for
        deletion from a timer, which is never inside one of its own signals, so
        nothing Qt is still executing on its behalf can be left holding a
        deleted object.
        """
        self._graveyard.add(socket)
        if graceful and socket.state() == QAbstractSocket.ConnectedState:
            # ``abort()`` sends an RST, and an RST makes the receiving TCP stack
            # throw away everything it has not delivered yet — including the BYE
            # that was just written.  The other player then sees "the line died"
            # instead of "your opponent left the game", and sits in the
            # reconnect window for nothing.  A normal FIN flushes first.
            socket.disconnected.connect(
                lambda: QTimer.singleShot(0, lambda: self._bury(socket)))
            socket.disconnectFromHost()
            QTimer.singleShot(3000, lambda: self._bury(socket))
            return
        QTimer.singleShot(0, lambda: self._bury(socket))

    def _bury(self, socket):
        if socket not in self._graveyard:
            return
        self._graveyard.discard(socket)
        try:
            socket.abort()
            socket.deleteLater()
        except RuntimeError:
            pass                          # already deleted with its parent

    def _adopt_socket(self, socket):
        self._socket = socket
        self._identified = False
        self._reader = FrameReader()
        self._last_rx = time.monotonic()
        self._attach_socket(socket)
        if self.mode == self.MODE_HOST:
            if self._relay is not None:
                # Dialling out: the connection is not there yet.
                socket.connected.connect(self._on_relay_connected)
            else:
                # QTcpServer hands us an already-connected socket.  It has a few
                # seconds to say who it is.  The host says nothing first: the
                # guest speaks, and a HELLO sent to an unknown caller would only
                # tell a stranger things it has no business knowing.
                self._hello_timer.start(UNIDENTIFIED_TIMEOUT_MS)
        self._keepalive.start()

    def _on_relay_connected(self):
        self._post(self.sender(), self._relay_connected)

    def _relay_connected(self, socket):
        if socket is not self._socket:
            return
        self._connect_timer.stop()
        self._relay_seen = True
        # The relay tells a host from a guest by the first bytes: a guest speaks
        # first with a HELLO frame, a host introduces itself with this line (it
        # is consumed by the relay, never passed on).  Without it the relay
        # could not tell a waiting host from a connection that merely sits
        # there.
        self._send_raw_bytes(socket, RELAY_HOST_PREAMBLE)
        if not self._awaiting_peer and not self.peer_name:
            self.statusMessage.emit("Connected to the relay at %s:%d. Waiting "
                                    "for your opponent to join it." % self._relay)

    def _on_connected(self):
        self._post(self.sender(), self._connected)

    def _connected(self, socket):
        if socket is not self._socket:
            return
        self._connect_timer.stop()
        self.statusMessage.emit("Reached %s:%d; waiting for the host to answer…"
                                % (self._host_address, self._host_port))
        self._handshake_timer.start(HANDSHAKE_NOTICE_MS)
        self._start_session()

    def _on_handshake_timeout(self):
        if self.mode != self.MODE_CLIENT or self.peer_name or self._socket is None:
            return
        if self._socket.state() == QAbstractSocket.ConnectedState:
            self.statusMessage.emit(
                "%s:%d accepted the connection but the game has not answered "
                "yet. If this is a relay, the host has not joined that room "
                "yet; otherwise something other than Balance of Power is "
                "listening on this port." % (self._host_address, self._host_port))

    def _on_hello_timeout(self):
        """A connection to the listening host never introduced itself."""
        if self._identified or self._socket is None or self.mode != self.MODE_HOST \
                or self._relay is not None:
            return
        self._drop_socket()
        self._reader.reset()
        self._emit_lobby()

    def _start_session(self):
        self.send({Message.HELLO: True,
                   "protocol": PROTOCOL_VERSION,
                   "name": self.local_name,
                   "side": self.local_side,
                   # ``rejoin`` says "I am the player who was here": the host may
                   # be holding a stale socket for us and must prefer this one.
                   "rejoin": bool(self._rejoined),
                   # The secret the host gave this guest in WELCOME; it is what
                   # proves a returning guest is the guest.
                   "token": self._rejoin_token if self.mode == self.MODE_CLIENT else "",
                   "game_id": self.game_id})

    def _on_ready_read(self):
        socket = self.sender()
        if socket is None or socket is not self._socket:
            # Bytes from a socket we have already replaced must not be parsed
            # with the new connection's framing state.
            return
        if self._in_read:
            # Cannot happen while this slot only parses and queues; if it ever
            # does, the outer call reads again before it returns.
            self._read_again = True
            return
        self._in_read = True
        try:
            while True:
                self._read_again = False
                self._last_rx = time.monotonic()
                try:
                    messages = self._reader.feed(bytes(socket.readAll()))
                except ProtocolError as exc:
                    self._post(socket, self._rx_garbage, "Protocol error: %s" % exc)
                    return
                for message in messages:
                    self._post(socket, self._rx_message, message)
                if not self._read_again:
                    break
        finally:
            self._in_read = False

    _read_again = False

    def _rx_garbage(self, socket, text):
        if socket is not self._socket:
            return
        self.errorOccurred.emit(text)
        self._on_garbage(socket)

    def _rx_message(self, socket, message):
        if socket is not self._socket:
            return                       # replaced or dropped since it arrived
        if not isinstance(message, dict):
            self.errorOccurred.emit("Protocol error: a frame is not an object")
            self._on_garbage(socket)
            return
        try:
            self._handle(message)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            # A well-framed but malformed message: one bad peer message
            # must not be able to end the host's session.
            self.errorOccurred.emit("Protocol error: bad message (%s)" % exc)
            self._on_garbage(socket)

    def _on_garbage(self, socket):
        """A peer sent bytes that are not our protocol.

        A host that has not yet got a player (a browser, a port scanner, a
        classmate with a different build) just drops that one socket and keeps
        listening; anywhere else the old behaviour (end the session) stands.
        """
        if self.is_host and (not self._identified or self._awaiting_peer):
            self._drop_socket()
            self._reader.reset()
            self._relay_redial_soon()
            self._emit_lobby()
            return
        self._teardown("protocol error")

    # -- a connection that has not introduced itself yet ---------------------

    def _on_pending_ready_read(self):
        socket = self.sender()
        if socket is None or socket is not self._pending_socket:
            return
        try:
            messages = self._pending_reader.feed(bytes(socket.readAll()))
        except ProtocolError:
            self._post(socket, self._pending_bad_frame)
            return
        for message in messages:
            self._post(socket, self._pending_message, message)

    def _pending_bad_frame(self, socket):
        if socket is self._pending_socket:
            self._refuse(socket, "bad frame")

    def _pending_message(self, socket, message):
        if socket is not self._pending_socket or not isinstance(message, dict):
            return
        self._handle_pending(message)

    def _on_pending_gone(self):
        self._post(self.sender(), self._pending_gone)

    def _on_pending_error(self, _error):
        self._post(self.sender(), self._pending_gone)

    def _pending_gone(self, socket):
        if socket is self._pending_socket:
            self._drop_pending()

    def _on_pending_timeout(self):
        # A second connection that never said HELLO is not the returning guest.
        self._drop_pending()

    def _handle_pending(self, message):
        """Decide what to do with a second connection.

        Only HELLO is meaningful before a player has been identified.  The seat
        is already held by a connection that looks alive, so the newcomer gets
        it only if it can show it is the same player: it holds the game's
        secret rejoin token, or it names the same player and side *and* the old
        connection has been silent for long enough to be dead (the unplugged
        laptop).  Everybody else is a third player and is turned away.
        """
        if Message.HELLO not in message:
            return
        if not self._pending_may_take_over(message):
            self._refuse(self._pending_socket, "game is full")
            return
        self._promote_pending()
        self._handle_hello(message)

    def _has_token(self, message):
        token = message.get("token")
        if not isinstance(token, str) or not token or not self._rejoin_token:
            return False
        return hmac.compare_digest(token.encode("utf-8"),
                                   self._rejoin_token.encode("utf-8"))

    def _same_seat(self, message):
        """Does this HELLO name the player whose seat it is, on the same side?"""
        return (bool(self.peer_name)
                and str(message.get("name") or "") == self.peer_name
                and self._negotiate_side(message.get("side")) == self.peer_side)

    def _pending_may_take_over(self, message):
        if not self._identified:
            return True
        if self._has_token(message):
            return True
        silent = time.monotonic() - self._last_rx > STALE_SOCKET_S
        return silent and self._same_seat(message)

    def _hello_is_returning(self, message):
        """May this HELLO take the seat of a guest who is away (no live socket)?

        The secret token is the proof.  A restarted process has lost it, so a
        HELLO that names the same player on the same side is accepted too: the
        seat is empty, and nobody else is being displaced.
        """
        return self._has_token(message) or self._same_seat(message)

    def _promote_pending(self):
        """Promote the new connection to be *the* connection."""
        old, self._socket = self._socket, self._pending_socket
        self._pending_timer.stop()
        self._hello_timer.stop()
        self._identified = False
        self._detach_socket(self._pending_socket, pending=True)
        # Take the pending parser with us: it may already hold the tail of a
        # frame that arrived in the same packet as HELLO.
        self._reader = self._pending_reader
        self._pending_socket = None
        self._pending_reader = FrameReader()
        self._last_rx = time.monotonic()
        if old is not None:
            self._detach_socket(old)
            self._retire(old)
        self._attach_socket(self._socket)
        self._keepalive.start()
        self.statusMessage.emit("The other player is back; restoring the game…")

    def _drop_pending(self, graceful=False):
        socket, self._pending_socket = self._pending_socket, None
        self._pending_reader = FrameReader()
        self._pending_timer.stop()
        if socket is not None:
            self._detach_socket(socket, pending=True)
            self._retire(socket, graceful)

    def _refuse(self, socket, reason):
        """Politely turn a socket away (the game already has two players)."""
        if socket is None:
            return
        self._send_raw(socket, {Message.BYE: True, "reason": reason})
        socket.flush()
        if socket is self._pending_socket:
            self._drop_pending(graceful=True)
        else:
            socket.disconnectFromHost()

    def _reject_current(self, reason):
        """Turn away the socket that just introduced itself, and keep waiting.

        Unlike a drop, this must not open a reconnect window (nobody who
        belongs to the game left) and must not end the session: the BYE goes
        out first and the socket is closed with a FIN so that it arrives.
        """
        socket = self._socket
        if socket is None:
            return
        self._send_raw(socket, {Message.BYE: True, "reason": reason})
        socket.flush()
        self._drop_socket(graceful=True)
        self._reader.reset()
        self._relay_redial_soon()
        self._emit_lobby()

    def _relay_redial_soon(self):
        """A relay host that dropped a stranger goes back to waiting in its room."""
        if self._relay is not None and self.mode == self.MODE_HOST \
                and not self._closing and self._socket is None:
            self._reconnect_timer.start(1000)

    # -- losing and regaining the peer --------------------------------------

    def _grace_seconds(self):
        return (CLIENT_RECONNECT_GRACE_S if self.mode == self.MODE_CLIENT
                else HOST_RECONNECT_GRACE_S)

    def _begin_reconnect(self, reason):
        """Keep the session alive after a drop, for a bounded while.

        Both ends do this.  The host keeps its listening socket and its whole
        game; the guest starts dialling again.  The game is *not* torn down:
        ``mode`` stays host/client, so ``is_online`` stays true and
        ``MainWindow`` — which only clears its turn bookkeeping when the session
        really ends — keeps the half-finished turn it is waiting on.

        Being called again while the window is open (a retry that connected and
        then died before the handshake finished) must still release that socket
        and arm the next attempt; only the announcement is made once.

        A drop from a socket that has already been replaced never reaches here:
        ``_on_disconnected`` ignores anything whose sender is not the current
        socket.  (A ``peer_online`` test was tried here instead and was wrong —
        at the moment a drop is reported the socket can still look connected, so
        the host missed the window it was supposed to open.)
        """
        announce = not self._awaiting_peer
        self._keepalive.stop()
        self._drop_socket()
        self._reader.reset()
        if announce:
            self._awaiting_peer = True
            self._reconnect_attempts = 0
            self._reconnect_deadline = time.monotonic() + self._grace_seconds()
            if self.mode == self.MODE_CLIENT:
                self._rejoined = True
            self.peerDisconnected.emit(reason)
            self.reconnectingChanged.emit(True)
            self.statusMessage.emit(self._reconnect_text())
            self._emit_lobby()
        self._schedule_reconnect(0)

    def _reconnect_text(self):
        if self.mode == self.MODE_CLIENT:
            return ("Connection to %s:%d lost; reconnecting for up to %.0f s\u2026"
                    % (self._host_address, self._host_port, CLIENT_RECONNECT_GRACE_S))
        return ("The other player dropped out. Waiting up to %.0f s for them to "
                "come back. The game is unchanged."
                % HOST_RECONNECT_GRACE_S)

    def _schedule_reconnect(self, delay_ms=None):
        if self._closing or not self._awaiting_peer:
            return
        remaining = self._reconnect_deadline - time.monotonic()
        if remaining <= 0:
            self._give_up("the other player did not come back")
            return
        if delay_ms is None:
            delay_ms = (CLIENT_RECONNECT_MS if self.mode == self.MODE_CLIENT
                        else HOST_RECONNECT_MS)
        delay_ms = int(min(delay_ms, remaining * 1000.0))
        if delay_ms <= 0:
            delay_ms = 1
        self._reconnect_timer.start(delay_ms)

    def _on_reconnect_timer(self):
        if self._closing:
            return
        if self._relay is not None and self.mode == self.MODE_HOST:
            # No listening socket to wait by: the way back is to dial the relay
            # again (the relay closes our end whenever the pairing ends).
            if self._socket is None:
                self._dial()
            if self._awaiting_peer:
                self.statusMessage.emit(self._reconnect_text())
                self._schedule_reconnect()
            return
        if not self._awaiting_peer:
            return
        if self.mode == self.MODE_CLIENT:
            if self._socket is not None:
                return                       # an attempt is already in flight
            self._attempt_reconnect()
        else:
            # Nothing to dial while hosting: the listening socket is still open
            # and the next connection will find us.
            self.statusMessage.emit(self._reconnect_text())
            self._schedule_reconnect()

    def _attempt_reconnect(self):
        self._reconnect_attempts += 1
        limit = max(1, int(self._grace_seconds() * 1000.0 / CLIENT_RECONNECT_MS))
        self.statusMessage.emit(
            "Reconnecting to %s:%d (attempt %d of about %d)\u2026"
            % (self._host_address, self._host_port, self._reconnect_attempts, limit))
        socket = QTcpSocket(self)
        self._adopt_socket(socket)
        self._connect_timer.start(CONNECT_TIMEOUT_MS)
        socket.connectToHost(self._host_address, self._host_port)

    def _give_up(self, reason):
        self._reconnect_timer.stop()
        self._awaiting_peer = False
        self._rejoined = False
        self.reconnectingChanged.emit(False)
        # Now the session really ends, and MainWindow is told so: this is the
        # emission that clears the turn it was waiting on.
        self._teardown(reason)

    def _restore_peer_state(self, rejoined, restarted=False):
        """Hand a (re)connecting guest everything it needs to be current.

        The host is authoritative, so this is all it takes: the position, the
        turn marker that says whether an end-of-turn request was consumed, and
        an unanswered crisis, in that order.  It also means a guest that joins a
        game already in progress is immediately useful rather than empty.
        """
        if restarted and self.settings and self._last_snapshot is not None:
            self.send({Message.START: True, "settings": dict(self.settings)})
        if self._last_snapshot is not None:
            state, turn = self._last_snapshot
            self.send({Message.SNAPSHOT: True, "state": state, "turn": turn})
        if self._last_crisis is not None:
            self.send({Message.CRISIS: True, "crisis": self._last_crisis})
        if rejoined:
            self.statusMessage.emit(
                "The other player reconnected; the game has been restored to "
                "the current turn." if self._last_snapshot is not None
                else "The other player reconnected.")
            self.peerReconnected.emit({"name": self.peer_name, "side": self.peer_side})

    def _connect_error_text(self, error, message):
        """Say what a failed outbound connect means, in words a student can act on.

        The operating system's own wording ("Connection refused", "Network
        error") is accurate and no help.  What matters is the difference
        between *refused* (the PC answered: it is reachable and the firewall is
        open, but nobody is listening there) and *no answer* (something is
        dropping the packets, which on a managed network is usually a firewall).
        """
        if self._relay is not None and self.mode == self.MODE_HOST:
            where = "the relay at %s:%d" % self._relay
        else:
            where = "%s:%d" % (self._host_address, self._host_port)
        if error == QAbstractSocket.ConnectionRefusedError:
            if self._relay is not None and self.mode == self.MODE_HOST:
                return ("%s answered 'refused': that PC is reachable but the "
                        "relay is not running on this port. Ask your teacher "
                        "to start it, and check the port number." % where)
            return ("%s answered 'refused': that PC is reachable, but nobody is "
                    "hosting on this port. Check the port number and that the "
                    "host has pressed Host." % where)
        if error == QAbstractSocket.HostNotFoundError:
            return ("%s: the host name is unknown. Type the IP address instead."
                    % where)
        if error == QAbstractSocket.SocketTimeoutError:
            return ("%s did not answer within %d s. A firewall is probably "
                    "dropping the connection silently (Windows Defender "
                    "Firewall on the host PC?), or the address is wrong. Ask "
                    "the host to run Test connection, or use Play by mail or "
                    "the teacher's relay instead."
                    % (where, CONNECT_TIMEOUT_MS // 1000))
        if error == QAbstractSocket.NetworkError:
            return ("%s cannot be reached (%s). Check the address and that both "
                    "PCs are on the same network." % (where, message))
        return "%s: %s" % (where, message)

    def _fail_connect(self, error, message=""):
        """An outbound connect that never completed.  Decide: retry, or report."""
        self._connect_timer.stop()
        text = self._connect_error_text(error, message)
        relay_host = self._relay is not None and self.mode == self.MODE_HOST
        if self._awaiting_peer:
            self._drop_socket()
            self.statusMessage.emit("%s %s" % (self._reconnect_text(), text))
            self._schedule_reconnect()
            return
        if relay_host and self._relay_seen:
            # The relay worked a minute ago: assume it blinked and keep trying.
            self._drop_socket()
            self.statusMessage.emit("Lost the relay (%s). Trying again\u2026" % text)
            self._reconnect_timer.start(RELAY_REDIAL_MS)
            return
        self.errorOccurred.emit(text)
        self._teardown(text, announce=False)

    def _on_connect_timeout(self):
        socket = self._socket
        if socket is None or self._closing:
            return
        if socket.state() == QAbstractSocket.ConnectedState:
            return
        self._fail_connect(QAbstractSocket.SocketTimeoutError)

    def _on_socket_error(self, error):
        socket = self.sender()
        # Read now: the text describes *this* failure, not whatever follows.
        message = socket.errorString() if socket is not None else ""
        self._post(socket, self._socket_error, error, message)

    def _socket_error(self, socket, error, message):
        if self._closing or socket is not self._socket:
            return
        if socket.state() != QAbstractSocket.ConnectedState \
                and self._connect_timer.isActive():
            # The connect itself failed (refused, unreachable, unknown name).
            self._fail_connect(error, message)
            return
        if self._awaiting_peer:
            # A refused connection never emits ``disconnected``, so this is the
            # only place the next attempt can be scheduled from.
            self._drop_socket()
            self.statusMessage.emit("%s %s" % (self._reconnect_text(), message))
            self._schedule_reconnect()
            return
        if self.mode == self.MODE_CLIENT and not self.peer_online:
            self.errorOccurred.emit(self._connect_error_text(error, message))
        else:
            self.statusMessage.emit(message)

    def _on_disconnected(self):
        self._post(self.sender(), self._disconnected)

    def _disconnected(self, socket):
        if self._closing or socket is not self._socket:
            return
        if self.is_host and not self._identified and not self._awaiting_peer:
            # A connection that never said who it was (a port probe, an
            # antivirus scan, netcheck, a student who typed the wrong port and
            # closed) is not a player who left.  No grace window, no "waiting
            # for them to come back", and above all the listening socket stays
            # open.
            self._drop_socket()
            self._reader.reset()
            if self._relay is not None:
                # The relay closed us before anybody had joined (it restarted,
                # or paired us with something that was not a player).
                self.statusMessage.emit("The relay closed the connection; "
                                        "reconnecting\u2026")
                self._reconnect_timer.start(RELAY_REDIAL_MS)
            self._emit_lobby()
            return
        if not self.auto_reconnect:
            self._teardown("the other player disconnected")
            return
        self._begin_reconnect("the connection to the other player was lost")

    def _on_keepalive(self):
        if self._draining:
            # A message is being handled and may be spinning the event loop (a
            # turn resolving); do not change the connection's state under it.
            return
        if self.peer_online:
            silent = time.monotonic() - self._last_rx > PEER_SILENCE_S
            if silent and self.mode == self.MODE_CLIENT and not self.peer_name \
                    and not self._awaiting_peer:
                # Connected, but the handshake never finished: this is not a
                # drop, it is a join that did not work.
                text = ("%s:%d accepted the connection but never answered the "
                        "handshake. It is either not Balance of Power, or (for "
                        "a relay) the host has not joined that room."
                        % (self._host_address, self._host_port))
                self.errorOccurred.emit(text)
                self._teardown(text, announce=False)
                return
            if silent and self.is_host and not self._identified \
                    and not self._awaiting_peer:
                # A connection that never introduced itself (a scanner or an
                # antivirus probe holding the port open) is not a player who
                # left: drop it and keep the lobby open.
                self._on_garbage(self._socket)
                return
            if silent:
                if self.auto_reconnect:
                    self._begin_reconnect("the other player stopped responding")
                else:
                    self._teardown("the other player stopped responding")
                return
            self.send({Message.PING: True})

    def _drop_socket(self, graceful=False):
        socket, self._socket = self._socket, None
        self._identified = False
        self._hello_timer.stop()
        if socket is None:
            return
        self._detach_socket(socket)
        self._retire(socket, graceful)

    def _teardown(self, reason, graceful=False, announce=True):
        self._keepalive.stop()
        self._reconnect_timer.stop()
        self._connect_timer.stop()
        self._handshake_timer.stop()
        self._relay = None
        self._relay_seen = False
        self._drop_socket(graceful=graceful)
        self._drop_pending()
        self._awaiting_peer = False
        self._rejoined = False
        self._end_turn_sent = False
        self._rejoin_token = ""
        self._inbox.clear()
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        self.peer_name = ""
        self.peer_ready = False
        self.local_ready = False
        self._reader.reset()
        was_online = self.mode != self.MODE_OFFLINE
        self.mode = self.MODE_OFFLINE
        if was_online and announce:
            self.peerDisconnected.emit(reason)
        self._emit_lobby()

    def close(self):
        self._closing = True
        try:
            if self._socket is not None:
                self.send({Message.BYE: True, "reason": "closing"})
                self._socket.flush()
        except Exception:
            pass
        self._teardown("closed", graceful=True)
        self._closing = False

    # -- sending ------------------------------------------------------------

    def send(self, message):
        return self._send_raw(self._socket, message)

    @staticmethod
    def _send_raw_bytes(socket, data):
        if socket is None:
            return False
        try:
            socket.write(data)
            return True
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def _send_raw(socket, message):
        if socket is None:
            return False
        try:
            socket.write(encode_message(message))
            return True
        except (OSError, RuntimeError):
            return False

    def send_action(self, action, **payload):
        payload["action"] = action
        if action == Action.END_TURN:
            # Remembered so that a guest which reconnects can repeat a request
            # that died with the connection: without that, the guest's End Turn
            # button stays disabled waiting for a turn the host never started.
            self._end_turn_sent = True
        return self.send({Message.ACTION: payload})

    def send_chat(self, text):
        return self.send({Message.CHAT: text, "name": self.local_name})

    def set_ready(self, ready=True):
        self.local_ready = bool(ready)
        self.send({Message.READY: self.local_ready})
        if self.is_host:
            self._emit_lobby()

    def start_game(self, settings):
        """Host only: announce the settings and begin."""
        self.settings = dict(settings)
        self.local_ready = True
        self.send({Message.START: True, "settings": self.settings})
        self.gameStarted.emit(dict(self.settings))

    def broadcast_snapshot(self, state, turn=None):
        """Host only: push authoritative state to the guest.

        ``turn`` is the host's completed-turn counter.  The guest uses it to
        decide when its own end-of-turn request has actually been consumed,
        rather than guessing from the year — snapshots broadcast *during* a
        crisis already carry the new year, which used to re-arm the guest's
        End Turn button in the middle of the host's resolution.

        The frame is also kept: that is the whole of what a guest needs to be
        restored, whether it was dropped mid-turn or has just arrived.
        """
        self._last_snapshot = (state, turn)
        if turn is not None:
            try:
                turn = int(turn)
            except (TypeError, ValueError):
                turn = None
            if turn is not None:
                # A completed turn cannot still be waiting for a crisis answer,
                # so a stored prompt from an earlier turn number is stale.
                if self._last_crisis is not None and self._crisis_marker is not None \
                        and turn != self._crisis_marker:
                    self._last_crisis = None
                self._out_turn = turn
        self.send({Message.SNAPSHOT: True, "state": state, "turn": turn})

    def send_crisis(self, payload):
        # Kept so that a guest which reconnects mid-duel is asked the question
        # again, instead of the host waiting for an answer that never arrived.
        self._last_crisis = dict(payload)
        self._crisis_marker = self._out_turn
        self.send({Message.CRISIS: True, "crisis": payload})

    def send_event(self, kind, text):
        self.send({Message.EVENT: True, "kind": kind, "text": text})

    # -- receiving ----------------------------------------------------------

    def _handle(self, message):
        if Message.HELLO in message:
            self._handle_hello(message)
        elif Message.WELCOME in message:
            self._handle_welcome(message)
        elif Message.LOBBY in message:
            if self.is_client:
                self._apply_lobby(message.get("players") or [])
        elif Message.READY in message:
            self.peer_ready = bool(message[Message.READY])
            self._emit_lobby()
        elif Message.START in message:
            # Only the host starts a game; a guest that sends this is ignored.
            if self.is_client:
                self.settings = dict(message.get("settings") or {})
                self.gameStarted.emit(dict(self.settings))
        elif Message.SNAPSHOT in message:
            if not self.is_client:
                return
            # Forward the whole frame: the world, plus the host's completed-turn
            # marker.  Emitting only the state silently dropped the marker, and
            # the guest then never learned that its end-turn request had been
            # consumed.
            self._note_turn_marker(message.get("turn"))
            self.snapshotReceived.emit({
                "state": message.get("state") or {},
                "turn": message.get("turn"),
            })
            self._resend_lost_end_turn()
        elif Message.ACTION in message:
            # Intents flow guest -> host only.  The frame key is the message
            # type; the value is the intent itself.
            if not self.is_host:
                return
            payload = self._sanitize_action(message[Message.ACTION])
            if payload is None:
                self.statusMessage.emit("Ignored a malformed request from the "
                                        "other player.")
                return
            if payload.get("action") == Action.CRISIS:
                # The answer arrived, so the stored prompt is no longer waiting.
                self._last_crisis = None
            self.actionReceived.emit(payload)
        elif Message.CRISIS in message:
            if self.is_client:
                crisis = message.get("crisis")
                self.crisisPrompted.emit(crisis if isinstance(crisis, dict) else {})
        elif Message.CHAT in message:
            text = message.get(Message.CHAT)
            name = message.get("name")
            self.chatReceived.emit(str(name) if name else self.peer_name,
                                   "" if text is None else str(text)[:2000])
        elif Message.EVENT in message:
            if self.is_client:
                self.statusMessage.emit(str(message.get("text", "")))
        elif Message.PING in message:
            self.send({Message.PONG: True})
        elif Message.PONG in message:
            pass
        elif Message.BYE in message:
            self._teardown(str(message.get("reason") or "the other player left"))

    @staticmethod
    def _int_field(value, low, high):
        """``value`` as an int in ``[low, high]``, or ``None`` (bools are not ints)."""
        if isinstance(value, bool):
            return None
        if isinstance(value, float) and value == int(value):
            value = int(value)
        if not isinstance(value, int) or not low <= value <= high:
            return None
        return value

    def _sanitize_action(self, payload):
        """Return the guest's request in a form the host may act on, or ``None``.

        The guest is not trusted.  Who is acting is a fact about the
        *connection*, not a claim in the message, so ``actor`` is overwritten
        with the side this guest was given; the numbers are checked here, so that
        nothing downstream can be made to raise (or to index outside the world)
        by a hand-built frame.  MainWindow still checks the country index
        against the size of the actual world.
        """
        if not isinstance(payload, dict):
            return None
        kind = payload.get("action")
        clean = {"action": kind, "actor": int(self.peer_side)}
        if kind == Action.POLICY:
            target = self._int_field(payload.get("target"), 0, MAX_COUNTRY_INDEX)
            policy = self._int_field(payload.get("policy"), 0, MAX_POLICY)
            value = self._int_field(payload.get("value"), 0, MAX_POLICY_VALUE)
            if target is None or policy is None or value is None:
                return None
            clean.update(target=target, policy=policy, value=value)
        elif kind == Action.END_TURN:
            pass
        elif kind == Action.CRISIS:
            choice = payload.get("choice")
            if choice is not None:
                if not isinstance(choice, str) or len(choice) > 32:
                    return None
                clean["choice"] = choice
            tough = payload.get("tough")
            if tough is not None:
                clean["tough"] = bool(tough)
        elif kind in (Action.READY, Action.CHAT):
            pass
        else:
            return None
        return clean

    def _note_turn_marker(self, turn):
        """Track the host's completed-turn counter.

        A *newer* marker is the only proof that an end-of-turn request was
        consumed; the year cannot be used for this (see
        :meth:`broadcast_snapshot`).
        """
        if turn is None:
            return
        try:
            marker = int(turn)
        except (TypeError, ValueError):
            return
        if marker != self._turn_marker:
            self._turn_marker = marker
            self._end_turn_sent = False

    def _resend_lost_end_turn(self):
        """Repeat an end-of-turn request that the drop may have swallowed.

        Runs once per reconnection, and only while ``_end_turn_sent`` survived:
        the turn marker has not moved since the request went out, so the host
        never confirmed it.  Without this, a guest whose request died with the
        connection is stuck for good — its End Turn button stays disabled
        waiting for a turn the host is not resolving.
        """
        if not self._rejoined:
            return
        self._rejoined = False
        if not self._end_turn_sent:
            return
        self.statusMessage.emit("Re-sending the end-of-turn request\u2026")
        self.send_action(Action.END_TURN, actor=self.local_side)

    def _handle_hello(self, message):
        if self.mode != self.MODE_HOST:
            return
        if self._identified and not self._awaiting_peer:
            return                        # a second HELLO on a settled connection
        if self._awaiting_peer and self._last_snapshot is not None \
                and not self._hello_is_returning(message):
            # A game is under way and its guest is only temporarily away: the
            # seat is theirs.  Anybody else (a classmate who typed the wrong
            # address) is turned away instead of being handed the position.
            self._reject_current("game in progress (the seat is kept for %s)"
                                 % (self.peer_name or "the other player"))
            return
        try:
            protocol = int(message.get("protocol", -1))
        except (TypeError, ValueError):
            protocol = -1
        if protocol != PROTOCOL_VERSION:
            # Refuse this one connection politely; do not tear the host down.
            # (A FIN, not an RST: the BYE must reach the guest.)
            self._reject_current("protocol version mismatch (host %d, you %s)"
                                 % (PROTOCOL_VERSION, message.get("protocol")))
            return
        self._identified = True
        self._hello_timer.stop()
        self.peer_name = str(message.get("name") or "Player")[:64]
        requested = message.get("side")
        self.peer_side = self._negotiate_side(requested)
        self.send({Message.WELCOME: True,
                   "protocol": PROTOCOL_VERSION,
                   "game_id": self.game_id,
                   "side": self.peer_side,
                   "token": self._rejoin_token,
                   "host_name": self.local_name})
        self._send_lobby()
        # "Rejoined" means somebody who was in the game came back to it.  A bare
        # connection that dropped before saying HELLO never opened a grace
        # window, so it can no longer turn the next ordinary join into a
        # "the game has been restored" message.
        rejoined = self._awaiting_peer or (bool(message.get("rejoin"))
                                           and self._last_snapshot is not None)
        if self._awaiting_peer:
            self._awaiting_peer = False
            self._reconnect_timer.stop()
            self.reconnectingChanged.emit(False)
        self.peerConnected.emit({"name": self.peer_name, "side": self.peer_side})
        # Hand over the position *after* the lobby, so a returning guest has the
        # right side and the right turn marker before it applies anything.
        # A guest that comes back without the rejoin token is a restarted
        # program: it never saw START, so it does not know the game's settings
        # or even which superpower it plays.
        self._restore_peer_state(rejoined, restarted=rejoined
                                 and not self._has_token(message))

    def _handle_welcome(self, message):
        if self.mode != self.MODE_CLIENT:
            return
        self._handshake_timer.stop()
        self.game_id = message.get("game_id") or self.game_id
        token = message.get("token")
        if isinstance(token, str) and token:
            self._rejoin_token = token
        assigned = message.get("side")
        if assigned in (0, 1):
            self.local_side = int(assigned)
            self.peer_side = 1 - self.local_side
        self.peer_name = str(message.get("host_name") or "Host")
        self.peerConnected.emit({"name": self.peer_name, "side": self.peer_side})
        self._reconnect_attempts = 0
        was_reconnecting = self._awaiting_peer
        if was_reconnecting:
            # The line is back.  ``_rejoined`` stays true until the snapshot
            # arrives, which is what lets a lost end-of-turn request be repeated
            # (see ``_resend_lost_end_turn``); the grace window itself is over,
            # so a second drop starts a fresh one instead of being ignored.
            self._awaiting_peer = False
            self._reconnect_timer.stop()
            self._reconnect_deadline = 0.0
            self.reconnectingChanged.emit(False)
            self.peerReconnected.emit({"name": self.peer_name,
                                       "side": self.peer_side})
            self.statusMessage.emit("Reconnected to the host; restoring the "
                                    "current turn\u2026")

    def _negotiate_side(self, requested):
        """Honour the guest's side request unless the host already took it."""
        try:
            requested = int(requested)
        except (TypeError, ValueError):
            requested = 1 - self.local_side
        if requested not in (0, 1):
            requested = 1 - self.local_side
        if requested == self.local_side:
            return 1 - self.local_side
        return requested

    def _send_lobby(self):
        self.send({Message.LOBBY: True, "players": self.lobby()})

    def _apply_lobby(self, players):
        """Absorb the host's view of the lobby.

        ``lobby()`` numbers the host as slot 0 and the guest as slot 1, so the
        peer is simply the entry that is not our own slot.  The ``local`` flag
        is the *host's* idea of local and must not be reused here; the UI is
        re-rendered from our own point of view instead.
        """
        my_slot = 0 if self.is_host else 1
        for entry in players:
            try:
                slot = int(entry.get("id", -1))
            except (TypeError, ValueError):
                continue
            if slot == my_slot:
                continue
            self.peer_name = str(entry.get("name") or self.peer_name)
            self.peer_ready = bool(entry.get("ready"))
            if entry.get("side") is not None:
                self.peer_side = int(entry["side"])
        self._emit_lobby()
