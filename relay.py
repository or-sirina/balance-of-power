#!/usr/bin/env python3
"""
Balance of Power relay: an OPTIONAL meeting point on the teacher's PC.

When to use it
--------------
Normally one student hosts and the other connects straight to them.  On a
managed network that can fail: Windows Defender Firewall on the host's PC drops
the incoming connection, and students cannot (or must not) change that.  Every
student PC can usually still reach the TEACHER's PC, so the teacher runs this
program and both students make OUTBOUND connections to it:

* the HOST ticks "Host through the teacher's relay" in the multiplayer lobby and
  types ``teacher-address:port``;
* the GUEST presses Join and types the same teacher address and the same port.

The relay pairs the two connections and copies bytes between them.  It never
looks inside the game traffic (the game's own handshake, snapshots and reconnect
logic run unchanged, end to end), so a pair that drops can reconnect through it.

It does look at the very first bytes of a connection, to know who is who:

* the HOST starts with the line ``BOPR host`` (consumed here, not passed on);
* the GUEST starts with the game's own first frame (``BOP1...``, a HELLO);
* a PROBE (``netcheck.py --relay``) sends ``BOPR probe`` and gets a one-line
  answer ``BOPR ok <state>`` without disturbing anybody waiting;
* anything else, or nothing at all within a few seconds, is dropped.

So an idle connection (a port scan, somebody who connected and went to lunch)
can never squat on a room or be paired with the host, and a waiting host or
guest that goes away is noticed at once instead of when somebody is paired
with it.

Usage (teacher's PC, Python 3.8 or newer, nothing to install)::

    python relay.py                       # rooms on ports 46000-46019
    python relay.py --first 47000 --count 30
    python relay.py --idle 120            # tolerate longer silences

Each room is one TCP port; give each pair of students its own.  Press Ctrl+C to
stop.  The relay needs to accept inbound TCP connections on ONE machine (this
one): the first time, Windows asks whether to allow Python through the firewall
-- choose "Private networks" (or have IT open the room ports).

Standard library only.  The same file is shipped as ``tools/bop_relay.py`` and
``relay.py``; a test keeps the two identical.
"""

import argparse
import asyncio
import ipaddress
import logging
import socket
import sys
import threading
import time

LOG = logging.getLogger("bop-relay")

DEFAULT_FIRST_PORT = 46000
DEFAULT_COUNT = 20
#: A pairing in which nothing moves in one direction for this long is closed.
#: The game pings every 4 s in both directions, so a healthy pair is never idle.
DEFAULT_IDLE_S = 60.0
#: How long a lone connection may wait in a room for its partner.
MAX_WAIT_S = 600.0
#: A new connection must show what it is (see above) within this long.
CLASSIFY_S = 5.0
#: Bytes a waiting guest may have sent before its host arrives (a HELLO and a
#: few pings); more than this is not a game client.
MAX_EARLY = 256 * 1024
PREAMBLE = b"BOPR"
FRAME_MAGIC = b"BOP1"


def _tune(writer):
    """Low latency and dead-peer detection on one connection."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    for level, option, value in ((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
                                 (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)):
        try:
            sock.setsockopt(level, option, value)
        except (OSError, AttributeError):
            pass
    # The operating system's default keepalive is two hours, which would let a
    # waiter whose PC lost power hold its room that long.  Ask for ~1 minute.
    try:
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):                  # Windows
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
        else:
            for name, value in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10),
                                ("TCP_KEEPCNT", 3)):
                if hasattr(socket, name):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)
    except (OSError, AttributeError, ValueError):
        pass


def _close(writer):
    try:
        writer.close()
    except Exception:
        pass


async def _pipe(reader, writer, idle):
    """Copy bytes one way until EOF, an error, or ``idle`` seconds of silence."""
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), idle)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        _close(writer)


class _Conn:
    """One accepted connection and what the relay has learned about it."""

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.role = None            # "host" or "guest" once classified
        self.early = bytearray()    # bytes it sent before it was paired
        self.paired = False
        self.dead = False
        self.watcher = None
        self.expiry = None
        self.done = asyncio.Event()

    def alive(self):
        return (not self.dead and not self.paired
                and not self.writer.transport.is_closing())


class _Room:
    def __init__(self, number, port):
        self.number = number
        self.port = port
        self.host = None            # the waiting host, if any
        self.guests = []            # guests waiting for a host, oldest first
        self.active = 0             # pairings in progress
        self.pairs = 0

    @property
    def waiting(self):
        """The longest-waiting unpaired connection (kept for diagnostics)."""
        if self.host is not None:
            return self.host
        return self.guests[0] if self.guests else None

    def state(self):
        if self.active:
            return "busy"
        if self.host is not None and self.host.alive():
            return "host"
        if any(g.alive() for g in self.guests):
            return "guest"
        return "free"

    def discard(self, conn):
        if self.host is conn:
            self.host = None
        if conn in self.guests:
            self.guests.remove(conn)


def _peer(writer):
    name = writer.get_extra_info("peername")
    return "%s:%s" % (name[0], name[1]) if name else "?"


async def _classify(conn):
    """Read just enough to tell a host, a guest, a probe, or nothing."""
    reader = conn.reader
    try:
        head = await asyncio.wait_for(reader.readexactly(4), CLASSIFY_S)
        if head == PREAMBLE:
            line = await asyncio.wait_for(reader.readuntil(b"\n"), CLASSIFY_S)
            words = line.decode("ascii", "replace").split()
            return words[0] if words and words[0] in ("host", "probe") else None
        if head == FRAME_MAGIC:
            conn.early += head
            return "guest"
    except (asyncio.TimeoutError, asyncio.IncompleteReadError,
            asyncio.LimitOverrunError, ConnectionError, OSError):
        pass
    return None


async def _watch(conn, room):
    """While unpaired: keep what the connection says, and notice when it leaves."""
    try:
        while True:
            data = await conn.reader.read(65536)
            if not data:
                break
            if len(conn.early) + len(data) > MAX_EARLY:
                break
            conn.early += data
    except (ConnectionError, OSError):
        pass
    except asyncio.CancelledError:
        return                    # it is being paired; the pairing owns it now
    conn.dead = True
    room.discard(conn)
    _close(conn.writer)
    conn.done.set()
    LOG.info("room %d (port %d): %s left before anybody joined", room.number,
             room.port, _peer(conn.writer))


def _try_pair(room, idle):
    """Pair the waiting host with the oldest live waiting guest, if both exist."""
    host = room.host
    if host is None or not host.alive():
        return
    guest = None
    for candidate in list(room.guests):
        if candidate.alive():
            guest = candidate
            break
        room.guests.remove(candidate)
    if guest is None:
        return
    room.host = None
    room.guests.remove(guest)
    host.paired = guest.paired = True
    room.active += 1
    room.pairs += 1
    asyncio.ensure_future(_run_pair(room, host, guest, idle))


async def _run_pair(room, host, guest, idle):
    LOG.info("room %d (port %d): paired %s <-> %s", room.number, room.port,
             _peer(host.writer), _peer(guest.writer))
    try:
        for conn in (host, guest):
            if conn.expiry is not None:
                conn.expiry.cancel()
            conn.watcher.cancel()
        await asyncio.gather(host.watcher, guest.watcher, return_exceptions=True)
        if host.writer.transport.is_closing() or guest.writer.transport.is_closing():
            return
        # What the guest said before the pairing (its HELLO) goes first.
        if guest.early:
            host.writer.write(bytes(guest.early))
        if host.early:
            guest.writer.write(bytes(host.early))
        one = asyncio.ensure_future(_pipe(guest.reader, host.writer, idle))
        two = asyncio.ensure_future(_pipe(host.reader, guest.writer, idle))
        await asyncio.wait([one, two], return_when=asyncio.FIRST_COMPLETED)
        for task in (one, two):
            task.cancel()
    finally:
        _close(host.writer)
        _close(guest.writer)
        room.active -= 1
        host.done.set()
        guest.done.set()
        LOG.info("room %d (port %d): pairing ended", room.number, room.port)


def _handler(room, idle):
    async def handle(reader, writer):
        _tune(writer)
        conn = _Conn(reader, writer)
        role = await _classify(conn)
        if role is None:
            LOG.info("room %d (port %d): %s sent nothing recognisable; dropped",
                     room.number, room.port, _peer(writer))
            _close(writer)
            return
        if role == "probe":
            try:
                writer.write(("BOPR ok %s\n" % room.state()).encode("ascii"))
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            _close(writer)
            return
        conn.role = role
        if role == "host":
            if room.host is not None and room.host.alive():
                LOG.info("room %d (port %d): a second host (%s) was turned away",
                         room.number, room.port, _peer(writer))
                _close(writer)
                return
            room.host = conn
        else:
            room.guests.append(conn)
        LOG.info("room %d (port %d): %s %s is waiting", room.number, room.port,
                 role, _peer(writer))
        loop = asyncio.get_event_loop()
        conn.watcher = asyncio.ensure_future(_watch(conn, room))
        conn.expiry = loop.call_later(MAX_WAIT_S, _close, writer)
        _try_pair(room, idle)
        await conn.done.wait()
        if conn.expiry is not None:
            conn.expiry.cancel()
    return handle


class RelayServer:
    """The relay, runnable from a script or from a test (in its own thread).

    ``first=0`` binds ``count`` ephemeral ports (for tests); the ports actually
    bound are in :attr:`ports`.
    """

    def __init__(self, bind="0.0.0.0", first=DEFAULT_FIRST_PORT,
                 count=DEFAULT_COUNT, idle=DEFAULT_IDLE_S):
        self.bind = bind
        self.first = int(first)
        self.count = int(count)
        self.idle = float(idle)
        self.ports = []
        self.failed = []            # [(port, reason)]
        self.rooms = []
        self._loop = None
        self._thread = None
        self._servers = []
        self._ready = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    def start(self, timeout=10.0):
        self._thread = threading.Thread(target=self._run, name="bop-relay",
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("the relay did not start")
        return self

    def stop(self):
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._shutdown)
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(5.0)

    def _shutdown(self):
        for server in self._servers:
            server.close()
        for task in asyncio.all_tasks(self._loop):
            task.cancel()
        self._loop.call_later(0.2, self._loop.stop)

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._open())
            self._ready.set()
            loop.run_forever()
        finally:
            self._ready.set()
            try:
                loop.run_until_complete(asyncio.sleep(0))
            except Exception:
                pass
            loop.close()

    async def _open(self):
        for index in range(self.count):
            port = self.first + index if self.first else 0
            room = _Room(index + 1, port)
            try:
                server = await asyncio.start_server(
                    _handler(room, self.idle), self.bind, port)
            except OSError as exc:
                self.failed.append((port, getattr(exc, "strerror", None) or str(exc)))
                continue
            room.port = server.sockets[0].getsockname()[1]
            self._servers.append(server)
            self.ports.append(room.port)
            self.rooms.append(room)


# --- the teacher's addresses -------------------------------------------------

def local_addresses():
    """``[(ip, note)]`` for this PC's IPv4 addresses, most likely first."""
    found = []
    default_ip = ""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))        # sends nothing; picks the route
        default_ip = probe.getsockname()[0]
    except OSError:
        pass
    finally:
        probe.close()
    names = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            names.append(info[4][0])
    except OSError:
        pass
    for ip in [default_ip] + names:
        if not ip or ip.startswith("127.") or ip in [f[0] for f in found]:
            continue
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if address.is_link_local:
            continue
        note = []
        if ip == default_ip:
            note.append("default route: probably the one")
        if address.is_private:
            note.append("private")
        found.append((ip, ", ".join(note)))
    found.sort(key=lambda item: (not item[1].startswith("default"), item[0]))
    return found


def banner(server):
    lines = ["", "Balance of Power relay", "=" * 22, ""]
    addresses = local_addresses()
    lines.append("This PC's addresses (give students the one on the lab network):")
    if addresses:
        for ip, note in addresses:
            lines.append("    %-16s %s" % (ip, "(%s)" % note if note else ""))
    else:
        lines.append("    (none found: is the network cable plugged in?)")
    lines += ["", "Rooms: one per pair of students.  Both students use the same "
              "address and port.", "",
              "    Room   Port", "    ----   -----"]
    for room in server.rooms:
        lines.append("    %4d   %5d" % (room.number, room.port))
    for port, reason in server.failed:
        lines.append("    (port %d unavailable: %s)" % (port, reason))
    first = addresses[0][0] if addresses else "<this PC's address>"
    if server.rooms:
        example = server.rooms[0].port
        lines += ["",
                  "Tell the pair using room 1:",
                  "    HOST : Multiplayer > tick \"Host through the teacher's relay\","
                  " type  %s:%d  > Host" % (first, example),
                  "    GUEST: Multiplayer > address  %s  port  %d  > Join"
                  % (first, example)]
    lines += ["",
              "If Windows asks to allow Python through the firewall, choose "
              "\"Private networks\".",
              "To open the ports from an administrator prompt instead:",
              "    netsh advfirewall firewall add rule name=\"BoP relay\" dir=in "
              "action=allow protocol=TCP localport=%d-%d"
              % (server.ports[0] if server.ports else server.first,
                 server.ports[-1] if server.ports else server.first),
              "", "Press Ctrl+C to stop.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Balance of Power relay for the teacher's PC.")
    parser.add_argument("--bind", default="0.0.0.0",
                        help="address to listen on (default: all IPv4)")
    parser.add_argument("--first", type=int, default=DEFAULT_FIRST_PORT,
                        help="port of room 1 (default %(default)s)")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT,
                        help="number of rooms (default %(default)s)")
    parser.add_argument("--idle", type=float, default=DEFAULT_IDLE_S,
                        help="close a pairing silent for this many seconds "
                             "(default %(default)s)")
    args = parser.parse_args(argv)
    if not 1 <= args.first <= 65535:
        parser.error("--first must be a port number from 1 to 65535 (got %d)"
                     % args.first)
    if args.count < 1:
        parser.error("--count must be at least 1 (got %d)" % args.count)
    if args.first + args.count - 1 > 65535:
        parser.error("--first %d with --count %d runs past port 65535; "
                     "use a lower --first or a smaller --count"
                     % (args.first, args.count))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    server = RelayServer(args.bind, args.first, args.count, args.idle)
    server.start()
    if not server.ports:
        print("Could not open any room port: %s" % (server.failed,),
              file=sys.stderr)
        return 1
    print(banner(server))
    try:
        # The main thread only waits; sleeping in short slices is what lets
        # Ctrl+C interrupt it promptly on Windows too.
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping the relay.")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
