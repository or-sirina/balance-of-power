"""
Network diagnostics: answer "can these two machines talk?" in the interface.

Every fact a player needs when a connection fails is already learned by the
code — whether the listening socket came up, whether the peer answered, whether
anybody replied to a discovery probe — but it only ever appeared in the session
log, which is exactly where nobody looks.  This module turns those questions
into a small, bounded, reportable set of checks:

* is the port being listened on at all, and if not, is it free or is somebody
  else on this machine holding it;
* is the peer visible: does a TCP connection to ``host:port`` complete;
* does UDP discovery work: does anything answer a probe.

Everything is bounded by a timeout and uses the standard library only, so the
report can also be produced from a test with no event loop.  No check ever
raises: a failure is a result, not an exception, because the whole point is to
be usable when things are broken.
"""

import json
import select
import socket
import time

from Net import DISCOVERY_MAGIC, DISCOVERY_PORT

#: Default patience per check.  Short on purpose: this runs from a button, and
#: a diagnostic that takes half a minute is a diagnostic nobody presses twice.
TCP_TIMEOUT = 1.5
DISCOVERY_TIMEOUT = 2.0

#: Sentinel for "this check could not be made", as opposed to failing.
UNKNOWN = None


class Check:
    """One question and its answer."""

    def __init__(self, name, ok, detail):
        #: ``True`` passed, ``False`` failed, ``None`` not applicable.
        self.name = name
        self.ok = ok
        self.detail = detail

    def line(self):
        mark = {True: "PASS", False: "FAIL", UNKNOWN: "SKIP"}[self.ok]
        return "[%s] %s: %s" % (mark, self.name, self.detail)

    def as_dict(self):
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


class Report:
    """The result of a whole diagnostic run."""

    def __init__(self, checks=None):
        self.checks = list(checks or [])
        self.started = time.time()
        self.elapsed = 0.0
        self.games = []

    def add(self, name, ok, detail):
        check = Check(name, ok, detail)
        self.checks.append(check)
        return check

    @property
    def ok(self):
        """Overall verdict: False only when a check actually failed."""
        return all(check.ok is not False for check in self.checks)

    @property
    def failures(self):
        return [check for check in self.checks if check.ok is False]

    def lines(self):
        return [check.line() for check in self.checks]

    def summary(self):
        if not self.checks:
            return "nothing was checked"
        failed = len(self.failures)
        if failed:
            return "%d of %d checks failed" % (failed, len(self.checks))
        skipped = len([c for c in self.checks if c.ok is UNKNOWN])
        if skipped:
            return "no failures (%d checks skipped)" % skipped
        return "all %d checks passed" % len(self.checks)

    def as_dict(self):
        return {
            "ok": self.ok,
            "summary": self.summary(),
            "elapsed": self.elapsed,
            "games": list(self.games),
            "checks": [check.as_dict() for check in self.checks],
        }

    def as_text(self):
        return "\n".join(self.lines() + ["", self.summary()])


# --- individual checks ------------------------------------------------------

def _connect_kind(host, port, timeout):
    """One bounded TCP connect attempt.  Returns ``(ok, kind, detail)``.

    ``kind`` is ``"ok"``, ``"refused"`` (the machine answered: it is reachable
    and nothing is listening there), ``"timeout"`` (nothing answered: packets
    are being dropped), or ``"error"`` (no route, unknown name, ...).  The
    difference matters: a refusal is proof the firewall is *not* the problem.
    """
    started = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        elapsed = (time.monotonic() - started) * 1000.0
        return True, "ok", "connected in %.0f ms" % elapsed
    except socket.timeout:
        return False, "timeout", (
            "no answer within %.1f s. A firewall is dropping the connection "
            "rather than refusing it." % timeout)
    except ConnectionRefusedError as exc:
        return False, "refused", "%s" % (exc.strerror or exc,)
    except OSError as exc:
        return False, "error", "%s" % (exc.strerror or exc,)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _connect(host, port, timeout):
    """One bounded TCP connect attempt.  Returns (ok, detail)."""
    ok, _kind, detail = _connect_kind(host, port, timeout)
    return ok, detail


def check_local_port(port, session=None, timeout=TCP_TIMEOUT):
    """Is anything listening on ``port`` on this machine?

    A port nobody listens on is only a *fault* when this game is supposed to be
    hosting: a player who has simply not pressed Host yet gets the same fact as
    a note, not as a failure, because otherwise every look at this report before
    the game starts reads as broken.
    """
    check_port = int(port)
    hosting = bool(session is not None and getattr(session, "is_host", False))
    marker = False if hosting else UNKNOWN
    ok, detail = _connect("127.0.0.1", check_port, timeout)
    if ok:
        who = ""
        if hosting:
            who = " (this game's server)" if getattr(session, "is_listening", False) \
                else " (not this game's server: it is not listening)"
        return Check("Port %d listening" % check_port, True,
                     "something accepts connections on 127.0.0.1:%d%s"
                     % (check_port, who))
    # Nothing answered locally.  Distinguish "free to host on" from "taken by a
    # program that only answers on another interface", which is the difference
    # between a working host button and "Could not listen on port".
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", check_port))
        if hosting:
            return Check("Port %d listening" % check_port, marker,
                         "this game is hosting on port %d but nothing is "
                         "listening on it. Stop hosting and start again."
                         % check_port)
        return Check("Port %d listening" % check_port, marker,
                     "nothing is listening on 127.0.0.1:%d, and the port is free "
                     "on this machine, so Host will work." % check_port)
    except OSError as exc:
        if hosting:
            return Check("Port %d listening" % check_port, marker,
                         "this game is hosting on port %d and the port cannot be "
                         "bound either (%s): another program on this machine owns "
                         "it." % (check_port, getattr(exc, "strerror", exc)))
        return Check("Port %d listening" % check_port, marker,
                     "nothing is listening on 127.0.0.1:%d and the port cannot be "
                     "bound either (%s): another program on this machine owns it."
                     % (check_port, getattr(exc, "strerror", exc)))
    finally:
        try:
            probe.close()
        except OSError:
            pass


def check_peer(host, port, timeout=TCP_TIMEOUT):
    """Can we open a TCP connection to the other player?"""
    if not host:
        return Check("Peer visible", UNKNOWN,
                     "no address to test. Type the host's address in the box "
                     "above.")
    ok, kind, detail = _connect_kind(host, int(port), timeout)
    if ok:
        return Check("Peer visible", True,
                     "%s:%d accepted a connection (%s)" % (host, port, detail))
    if kind == "refused":
        # The machine answered, so the network and its firewall are fine.
        return Check("Peer visible", False,
                     "%s:%d is reachable but refused the connection: nobody is "
                     "hosting on port %d there. Check the port number and that "
                     "the host has pressed Host. (This is not a firewall "
                     "problem.)" % (host, port, int(port)))
    if kind == "timeout":
        return Check("Peer visible", False,
                     "%s:%d did not answer (%s). A firewall on the host (or "
                     "switch port isolation) is probably dropping the "
                     "connection, or the address is wrong. The host must allow "
                     "inbound TCP %d; otherwise use Play by mail or the "
                     "teacher's relay."
                     % (host, port, detail, int(port)))
    return Check("Peer visible", False,
                 "could not reach %s:%d (%s). Check the address, and that both "
                 "PCs are on the same network." % (host, port, detail))


def check_session_peer(session):
    """What the live session knows about its peer (the cheapest real check)."""
    if session is None:
        return Check("Session", UNKNOWN, "Not connected yet.")
    if not getattr(session, "is_online", False):
        return Check("Session", UNKNOWN, "Not connected yet.")
    if getattr(session, "is_connected", False):
        address = getattr(session, "peer_address", "") or "?"
        return Check("Session", True,
                     "connected to %s at %s (%s)"
                     % (getattr(session, "peer_name", "") or "?", address,
                        session.mode))
    if getattr(session, "reconnecting", False):
        return Check("Session", False,
                     "the connection dropped and this game is trying to "
                     "reconnect to %s:%s. Leave the game open and wait."
                     % (getattr(session, "host_address", "") or "?",
                        getattr(session, "host_port", "") or "?"))
    if getattr(session, "is_host", False):
        return Check("Session", UNKNOWN,
                     "hosting on port %s, waiting for a player to connect"
                     % (getattr(session, "port", "") or "?"))
    return Check("Session", UNKNOWN, "No one is connected.")


def udp_discovery(timeout=DISCOVERY_TIMEOUT, port=DISCOVERY_PORT, targets=None,
                  broadcast=True):
    """Send discovery probes and collect the answers.

    Returns ``(games, notes)``; a note is a sentence about a target that could
    not be used (no broadcast address, no network, and so on).  Loopback is
    probed first on purpose: a host on this very machine answers there, which
    separates "discovery is broken" from "nobody is hosting on this subnet".
    ``broadcast=False`` keeps the probe strictly local, which is what the tests
    want and what a player on a metered or watched network may prefer.
    """
    if targets is None:
        targets = [("127.0.0.1", int(port))]
        if broadcast:
            targets.append(("255.255.255.255", int(port)))
    games = []
    notes = []
    payload = json.dumps({"magic": DISCOVERY_MAGIC, "probe": True}).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        sock.setblocking(False)
        sent = False
        for host, target_port in targets:
            try:
                sock.sendto(payload, (host, int(target_port)))
                sent = True
            except OSError as exc:
                notes.append("could not probe %s:%s (%s)"
                             % (host, target_port, getattr(exc, "strerror", exc)))
        if not sent:
            return games, notes
        deadline = time.monotonic() + timeout
        seen = set()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _w, _x = select.select([sock], [], [], min(remaining, 0.25))
            if not ready:
                continue
            try:
                data, sender = sock.recvfrom(65535)
            except OSError as exc:
                notes.append("the search could not be completed: %s"
                             % getattr(exc, "strerror", exc))
                break
            try:
                message = json.loads(bytes(data).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                continue
            if not isinstance(message, dict):
                continue
            if message.get("magic") != DISCOVERY_MAGIC or message.get("probe", True):
                continue
            try:
                game = dict(message.get("game") or {})
            except (TypeError, ValueError):
                continue
            game["address"] = sender[0]
            key = (game.get("id"), game.get("address"), game.get("port"))
            if key in seen:
                continue
            seen.add(key)
            games.append(game)
    except OSError as exc:
        notes.append("UDP discovery could not run: %s"
                     % getattr(exc, "strerror", exc))
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return games, notes


def check_discovery(timeout=DISCOVERY_TIMEOUT, expect_beacon=False,
                    broadcast=True):
    """Does UDP discovery find anything?"""
    games, notes = udp_discovery(timeout=timeout, broadcast=broadcast)
    described = ", ".join(
        "%s at %s:%s" % (game.get("name") or "?", game.get("address"),
                         game.get("port", DISCOVERY_PORT)) for game in games)
    if games:
        check = Check("UDP discovery", True,
                      "%d game(s) answered: %s" % (len(games), described))
    elif expect_beacon:
        check = Check("UDP discovery", False,
                      "your own game did not answer a search on 127.0.0.1:%d "
                      "within %.1f s, so discovery replies are not getting "
                      "through, even locally." % (DISCOVERY_PORT, timeout))
    else:
        check = Check("UDP discovery", UNKNOWN,
                      "nothing answered within %.1f s. Nobody may be hosting, "
                      "or the network may block broadcast. Type the host's "
                      "address in the box above."
                      % timeout)
    if notes:
        check.detail = check.detail + " (" + "; ".join(notes) + ")"
    return check, games


# --- this machine's own addresses -------------------------------------------

#: Substrings of an interface name that mark it as not "the cable in the wall".
_VIRTUAL_HINTS = ("vethernet", "hyper-v", "wsl", "docker", "virtualbox",
                  "vbox", "vmware", "vmnet", "vpn", "anyconnect",
                  "globalprotect", "wireguard", "tailscale", "zerotier",
                  "bluetooth", "loopback", "virbr", "podman", "pseudo")
#: Prefixes (Linux/macOS style names) of the same kind.
_VIRTUAL_PREFIXES = ("veth", "br-", "tun", "tap", "wg", "utun", "lxc", "vnet",
                     "docker", "virbr", "ham", "zt")


def _is_virtual_name(name):
    lowered = str(name or "").lower()
    return (any(hint in lowered for hint in _VIRTUAL_HINTS)
            or lowered.startswith(_VIRTUAL_PREFIXES))


def classify_address(ip, name="", default_route=False):
    """Describe one IPv4 address of this machine: ``dict`` with a ``rank``.

    Lower rank is a better thing to read out to a classmate: 0 a private
    (RFC 1918) address on a real adapter, 1 any other address on a real
    adapter, 2 something virtual (VPN, Hyper-V/WSL, Docker, VirtualBox,
    Bluetooth) or carrier-grade NAT, 3 link-local (no DHCP lease: nobody else
    can reach it).
    """
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return {"ip": ip, "name": name, "virtual": True, "rank": 9,
                "default": default_route, "link_local": False}
    virtual = _is_virtual_name(name)
    link_local = addr.is_link_local
    cgnat = addr in ipaddress.ip_network("100.64.0.0/10")
    if link_local:
        rank = 3
    elif virtual or cgnat:
        rank = 2
    elif addr.is_private:
        rank = 0
    else:
        rank = 1
    return {"ip": ip, "name": name, "virtual": virtual or cgnat, "rank": rank,
            "default": bool(default_route), "link_local": link_local}


def _default_route_address():
    """The address the OS would use to reach the outside; nothing is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))      # TEST-NET-1: UDP connect sends no packet
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _interface_addresses():
    """``[(ip, interface name)]`` for every up, non-loopback IPv4 address."""
    found = []
    try:
        from PyQt5.QtNetwork import QAbstractSocket, QNetworkInterface
        for itf in QNetworkInterface.allInterfaces():
            flags = itf.flags()
            if not (flags & QNetworkInterface.IsUp
                    and flags & QNetworkInterface.IsRunning) \
                    or flags & QNetworkInterface.IsLoopBack:
                continue
            for entry in itf.addressEntries():
                address = entry.ip()
                if address.protocol() != QAbstractSocket.IPv4Protocol:
                    continue
                found.append((address.toString(), itf.humanReadableName()))
    except Exception:                         # no Qt, or Qt refused: fall back
        pass
    if not found:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None,
                                           socket.AF_INET):
                found.append((info[4][0], ""))
        except OSError:
            pass
    return found


def local_addresses():
    """This machine's IPv4 addresses, best candidate first.

    Returns a list of dicts (see :func:`classify_address`).  Loopback is never
    included.  The address of the default route breaks ties inside a rank, so
    when a laptop has both Ethernet and a VPN adapter the Ethernet one leads.
    """
    default_ip = _default_route_address()
    seen = set()
    result = []
    for ip, name in _interface_addresses():
        if ip.startswith("127.") or ip in seen:
            continue
        seen.add(ip)
        result.append(classify_address(ip, name, default_route=(ip == default_ip)))
    if default_ip and default_ip not in seen and not default_ip.startswith("127."):
        result.append(classify_address(default_ip, "", default_route=True))
    result.sort(key=lambda item: (item["rank"], not item["default"], item["ip"]))
    return result


def address_summary(addresses=None):
    """What to show a player: ``(ips_to_read_out, plain_text, warning)``.

    One clear candidate is shown alone.  When it is ambiguous (several real
    adapters, or only virtual ones) every candidate is listed with its adapter
    name so the player can pick the one on the lab network.  Link-local
    (169.254.x.x) addresses are never offered; if they are all there is, the
    warning says the PC has no DHCP lease.
    """
    if addresses is None:
        addresses = local_addresses()
    usable = [a for a in addresses if a["rank"] < 3]
    if not usable:
        if addresses:
            return [], "", ("Only a 169.254.x.x address was found: this PC got "
                            "no address from DHCP. Check the network cable.")
        return [], "", "No network address was found. Is the cable plugged in?"
    best = usable[0]["rank"]
    real = [a for a in usable if a["rank"] <= 1]
    if real:
        shown = [a for a in real if a["rank"] == real[0]["rank"]]
    else:
        shown = usable
    ambiguous = len(shown) > 1
    ips = [a["ip"] for a in shown]
    if ambiguous:
        text = ", ".join("%s (%s)" % (a["ip"], a["name"] or "adapter")
                         for a in shown)
        warning = ("This PC has several addresses. Use the one on the lab "
                   "network (usually the Ethernet adapter).")
    else:
        only = shown[0]
        text = only["ip"] + (" (%s)" % only["name"] if only["name"] else "")
        warning = ""
    if best >= 2:
        warning = ("Only virtual adapters (VPN, virtual machine) were found; "
                   "these may not be reachable by your classmates. " + warning).strip()
    return ips, text, warning


def check_relay_session(session):
    """Report on a relay host without opening a second connection to the room.

    A probe connection to a relay room would be paired with whoever is waiting
    there, so the relay is judged from the live session instead.
    """
    relay = getattr(session, "relay", None)
    where = "%s:%s" % tuple(relay)
    if getattr(session, "is_listening", False):
        return Check("Relay", True, "connected to the relay at %s" % where)
    if getattr(session, "reconnecting", False):
        return Check("Relay", False, "the relay at %s is not reachable right "
                     "now; this game keeps trying" % where)
    return Check("Relay", False, "not connected to the relay at %s" % where)


def check_address_choice(host, port):
    """A reminder that always applies, and the most common real cause of failure."""
    if str(host).strip() in ("", "127.0.0.1", "localhost", "::1"):
        return Check("Address", UNKNOWN,
                     "127.0.0.1 only reaches this machine. To play against "
                     "somebody else, use the address their machine answers on.")
    return Check("Address", True, "%s:%s" % (host, port))


def diagnose(port, peer=None, session=None, timeout=TCP_TIMEOUT,
             discovery_timeout=DISCOVERY_TIMEOUT, expect_beacon=False,
             discovery_port=DISCOVERY_PORT, broadcast=True):
    """Run the whole set of checks and return a :class:`Report`.

    ``peer`` is the address to test for reachability; it defaults to the live
    session's peer and to ``127.0.0.1`` when hosting, so pressing the button
    without typing anything still says something useful.
    """
    started = time.monotonic()
    report = Report()

    report.checks.append(check_session_peer(session))
    if getattr(session, "relay", None):
        # Hosting through the relay: there is no local port to look at.
        report.checks.append(check_relay_session(session))
    else:
        report.checks.append(check_local_port(port, session=session,
                                              timeout=timeout))

    address = (peer or "").strip()
    if not address:
        if session is not None and getattr(session, "is_connected", False):
            address = getattr(session, "peer_address", "") or ""
        elif session is not None and getattr(session, "is_host", False):
            address = "127.0.0.1"
    session_check = report.checks[0]
    connected = bool(session is not None and getattr(session, "is_connected", False))
    hosting_alone = bool(session is not None and getattr(session, "is_host", False)
                         and not connected)
    if connected:
        # A live session is the strongest possible "the peer is visible", and it
        # says so without opening a second connection just to confirm it.
        report.checks.append(Check(
            "Peer visible", True,
            "already connected to %s (%s); nothing to test"
            % (getattr(session, "peer_address", "") or "the peer",
               getattr(session, "mode", "?"))))
    elif getattr(session, "relay", None):
        pass                      # judged from the session; see check_relay_session
    elif address:
        check = check_peer(address, port, timeout=timeout)
        report.checks.append(check)
        if not check.ok and hosting_alone and address == "127.0.0.1":
            # Hosting and nobody has connected yet: "peer not visible" is the
            # expected state, not a fault, so it must not fail the report.
            check.ok = UNKNOWN
            check.detail = ("nobody is connected yet on 127.0.0.1:%d, which is "
                            "normal while hosting alone" % int(port))
    if not getattr(session, "relay", None):
        report.checks.append(check_address_choice(address or "127.0.0.1", port))

    discovery, games = check_discovery(timeout=discovery_timeout,
                                       expect_beacon=expect_beacon,
                                       broadcast=broadcast)
    report.checks.append(discovery)
    report.games = games
    report.elapsed = time.monotonic() - started
    return report
