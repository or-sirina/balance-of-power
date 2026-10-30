#!/usr/bin/env python3
"""
Balance of Power - network self-check.  Standard library only, Python 3.8+.

    python netcheck.py                      # this PC only
    python main.py --netcheck [options]     # the same thing

    --peer IP[:PORT]   connect to a host's game (default port 45454)
    --relay IP         probe the teacher's relay, TCP ports 46000-46019
    --share PATH       test a shared folder (e.g. \\\\TEACHER\\bop-mail)
    --llm [URL]        HTTPS test of the model endpoint (no key is sent)
    --pypi             HTTPS test of pypi.org (needed only for installing)
    --port N           game port to test (default 45454)

Every line is PASS, WARN, FAIL or INFO.  A WARN or FAIL is followed by one line
saying what to do about it.  The exit code is 1 when anything failed.
Output is plain ASCII so it survives any Windows console code page.
"""

import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PORT = 45454
BEACON_PORT = 45455
RELAY_FIRST = 46000
RELAY_COUNT = 20

COUNTS = {"PASS": 0, "WARN": 0, "FAIL": 0}


def report(tag, name, detail="", fix=""):
    """Print one result line (and its fix line for WARN/FAIL)."""
    if tag in COUNTS:
        COUNTS[tag] += 1
    print("[%s] %-18s %s" % (tag, name, detail))
    if fix and tag in ("WARN", "FAIL"):
        print("       fix: %s" % fix)
    sys.stdout.flush()


def _err(exc):
    return getattr(exc, "strerror", None) or str(exc)


# -- this PC ---------------------------------------------------------------

def check_python():
    import struct
    version = sys.version_info
    bits = struct.calcsize("P") * 8
    text = "Python %d.%d.%d, %d-bit, %s" % (version[0], version[1], version[2],
                                           bits, sys.platform)
    if version < (3, 8):
        report("FAIL", "python", text, "install Python 3.8 - 3.12 (64-bit) from python.org")
    elif bits != 64 and sys.platform.startswith("win"):
        report("FAIL", "python", text,
               "PyQt5 has no wheels for 32-bit Python 3.9+; install 64-bit Python")
    elif version >= (3, 13):
        report("PASS", "python", text + " (3.13+: the game relaxes the strict CA "
               "check itself; 3.12 is still the safest)")
    else:
        report("PASS", "python", text)


def _launcher_libs():
    """Where start-windows.bat put PyQt5 (pip --target); see main.launcher_libs."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    tag = "py3%d-%s" % (sys.version_info[1], sys.maxsize > 2 ** 32)
    path = os.path.join(base, "balance-of-power", "libs", tag)
    return path if os.path.isdir(path) else None


def check_pyqt():
    libs = _launcher_libs()
    if libs and libs not in sys.path:
        sys.path.append(libs)
    try:
        from PyQt5 import QtCore
    except ImportError as exc:
        report("FAIL", "PyQt5", "cannot import: %s" % exc,
               "run start-windows.bat once (it installs PyQt5), or "
               "'python -m pip install PyQt5'")
        return
    report("PASS", "PyQt5", "PyQt %s / Qt %s" % (QtCore.PYQT_VERSION_STR, QtCore.QT_VERSION_STR))


def check_user_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import Paths
    except ImportError:
        report("INFO", "save folder", "Paths module not found (netcheck run outside the game folder)")
        return
    path = Paths.user_dir()
    warning = Paths.take_warning()
    if warning:
        report("WARN", "save folder", warning,
               "ask IT for a writable %LOCALAPPDATA%, or set BOP_USER_DIR to a folder you can write to")
    else:
        report("PASS", "save folder", path)


def own_addresses():
    """Primary IPv4 (route-based, nothing is sent) plus every other non-loopback IPv4."""
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))
        found.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return found


def check_addresses():
    ips = own_addresses()
    host = socket.gethostname()
    if not ips:
        report("FAIL", "own address", "no IPv4 address found",
               "is the network cable plugged in? check the adapter in Windows Network settings")
        return
    if all(ip.startswith("169.254.") for ip in ips):
        report("FAIL", "own address", "only %s (169.254.x.x = no DHCP lease)" % ", ".join(ips),
               "no address was handed out: check the cable/switch port, ask IT")
        return
    report("PASS", "own address", "%s  (first = default route; computer name %s)"
           % (", ".join(ips), host))


def check_bind(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
        sock.listen(1)
        report("PASS", "bind TCP %d" % port,
               "can listen (this does not prove the firewall lets other PCs in)")
    except OSError as exc:
        in_use = getattr(exc, "errno", None) in (98, 48, 10048)
        if in_use:
            report("WARN", "bind TCP %d" % port, "already in use",
                   "is the game (or another copy) already running? close it and retry")
        else:
            report("FAIL", "bind TCP %d" % port, _err(exc),
                   "a security product may forbid listening; use the teacher's relay instead")
    finally:
        sock.close()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp.bind(("0.0.0.0", BEACON_PORT))
        report("PASS", "bind UDP %d" % BEACON_PORT, "can receive game announcements")
    except OSError as exc:
        report("WARN", "bind UDP %d" % BEACON_PORT, _err(exc),
               "the game list will not fill in; players can type the host's address instead")
    finally:
        udp.close()


def check_broadcast():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(b"bop-netcheck", ("255.255.255.255", BEACON_PORT))
        report("PASS", "UDP broadcast", "send ok (arrival on another PC cannot be proven from here)")
    except OSError as exc:
        report("WARN", "UDP broadcast", _err(exc),
               "the game list will not fill in; players can type the host's address instead")
    finally:
        sock.close()


# -- other machines --------------------------------------------------------

def tcp_probe(host, port, timeout=5.0):
    """('open'|'refused'|'timeout'|'error', milliseconds, text)."""
    started = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return "open", int((time.time() - started) * 1000), ""
    except ConnectionRefusedError:
        return "refused", int((time.time() - started) * 1000), ""
    except socket.timeout:
        return "timeout", int((time.time() - started) * 1000), ""
    except socket.gaierror as exc:
        return "error", 0, "cannot resolve %s (%s)" % (host, _err(exc))
    except OverflowError:
        return "error", 0, "port %s is not valid (use 1-65535)" % port
    except OSError as exc:
        return "error", 0, _err(exc)
    finally:
        sock.close()


def check_peer(spec):
    host, port = spec, DEFAULT_PORT
    if spec.count(":") == 1:
        host, text = spec.split(":")
        try:
            port = int(text)
        except ValueError:
            report("FAIL", "peer", "bad port in %r" % spec, "use IP or IP:PORT")
            return
        if not 1 <= port <= 65535:
            report("FAIL", "peer", "port %d is not valid in %r" % (port, spec),
                   "ports run from 1 to 65535")
            return
    name = "peer %s:%d" % (host, port)
    kind, ms, text = tcp_probe(host, port)
    if kind == "open":
        report("PASS", name, "connected in %d ms" % ms)
    elif kind == "refused":
        report("WARN", name, "REFUSED: that PC is reachable and its firewall is open, but "
               "nobody is hosting on this port",
               "the host must press Host first; check the port number")
    elif kind == "timeout":
        report("FAIL", name, "TIMEOUT: no answer at all",
               "the host's firewall is silently dropping it (Windows Defender inbound rule?), "
               "the IP is wrong, or the PC is off. Use the teacher's relay or play by mail")
    else:
        report("FAIL", name, text, "check the address and the cable")


def relay_probe(host, port, timeout=5.0):
    """Ask one relay room how it is, without joining it.

    ``('open'|'refused'|'timeout'|'error', ms, text, state)``.  The relay
    answers the line ``BOPR probe`` with ``BOPR ok <free|host|guest|busy>`` and
    closes, and never treats the probe as a player: a connect-and-close (what
    this used to do) briefly looked like a guest arriving and leaving to a host
    waiting in that room.  ``state`` is empty if nothing answered the probe
    (an older relay, or not a relay at all).
    """
    started = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        ms = int((time.time() - started) * 1000)
        state = ""
        try:
            sock.sendall(b"BOPR probe\n")
            sock.settimeout(3.0)
            data = b""
            while b"\n" not in data and len(data) < 200:
                chunk = sock.recv(200)
                if not chunk:
                    break
                data += chunk
            words = data.decode("ascii", "replace").split()
            if len(words) >= 3 and words[0] == "BOPR" and words[1] == "ok":
                state = words[2]
        except (OSError, socket.timeout):
            pass
        return "open", ms, "", state
    except ConnectionRefusedError:
        return "refused", int((time.time() - started) * 1000), "", ""
    except socket.timeout:
        return "timeout", int((time.time() - started) * 1000), "", ""
    except socket.gaierror as exc:
        return "error", 0, "cannot resolve %s (%s)" % (host, _err(exc)), ""
    except OSError as exc:
        return "error", 0, _err(exc), ""
    finally:
        sock.close()


def check_relay(host):
    results = {}

    def probe(port):
        results[port] = relay_probe(host, port, timeout=5.0)

    threads = [threading.Thread(target=probe, args=(RELAY_FIRST + i,))
               for i in range(RELAY_COUNT)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    name = "relay %s" % host
    last = RELAY_FIRST + RELAY_COUNT - 1
    kinds = [results[p][0] for p in sorted(results)]
    states = [results[p][3] for p in sorted(results)]
    opened = kinds.count("open")
    if opened:
        answered = [s for s in states if s]
        if answered:
            free = answered.count("free")
            report("PASS", name, "%d of %d ports %d-%d answer; %d room(s) free, %d "
                   "with somebody waiting or playing (probing does not disturb them)"
                   % (opened, RELAY_COUNT, RELAY_FIRST, last, free,
                      len(answered) - free))
        else:
            report("WARN", name, "%d of %d ports %d-%d accept connections but none "
                   "answered the relay probe" % (opened, RELAY_COUNT, RELAY_FIRST, last),
                   "something other than this version of relay.py is listening "
                   "there; restart the relay from this folder")
    elif kinds.count("refused") == RELAY_COUNT:
        report("WARN", name, "all ports answered 'refused': PC reachable, firewall open, "
               "relay not running", "start the relay on the teacher PC: py relay.py")
    elif kinds.count("timeout"):
        report("FAIL", name, "no answer on ports %d-%d (%d timed out)"
               % (RELAY_FIRST, last, kinds.count("timeout")),
               "the teacher PC needs ONE inbound firewall rule for TCP %d-%d "
               "(docs/INSTRUCTOR_CHECKLIST.md), or the IP is wrong" % (RELAY_FIRST, last))
    else:
        texts = sorted(set(r[2] for r in results.values() if r[2]))
        report("FAIL", name, "; ".join(texts) or "unreachable", "check the address and the cable")


# -- shared folder ---------------------------------------------------------

def check_share(path):
    """Write, rename, replace, list, read and delete: the play-by-mail sequence."""
    low = path.replace("/", "\\").lower()
    if low.startswith("\\\\") and low[2:3].isdigit():
        report("WARN", "share name", "UNC path uses an IP address",
               "use \\\\HOSTNAME\\share, not \\\\IP\\share: an IP forces NTLM and often "
               "asks for a password or is blocked")
    folder = os.path.join(path, "_bop_netcheck_%s" % socket.gethostname())
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        report("FAIL", "share", "cannot create a folder in %s: %s" % (path, _err(exc)),
               "check the path and that your account may write there (share needs Modify)")
        return
    final = os.path.join(folder, "probe.bopg")
    leftovers = []
    try:
        started = time.time()
        fd, tmp = tempfile.mkstemp(prefix=".bopg-tmp-", suffix=".part", dir=folder)
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"x" * 20000)
            handle.flush()
            os.fsync(handle.fileno())
        report("PASS", "share write", "20000 bytes in %d ms" % ((time.time() - started) * 1000))
        try:
            os.replace(tmp, final)
            report("PASS", "share rename", "write-then-rename works")
        except OSError as exc:
            report("FAIL", "share rename", "rename denied (%s)" % _err(exc),
                   "grant Modify (not just Write) on the share AND the NTFS folder")
            final = tmp
        # Replacing an existing file needs the Delete right; without it the
        # second move of a game in the same folder fails.
        fd, tmp2 = tempfile.mkstemp(prefix=".bopg-tmp-", suffix=".part", dir=folder)
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"y" * 20000)
        try:
            os.replace(tmp2, final)
            report("PASS", "share overwrite", "replacing an existing file works")
        except OSError as exc:
            report("FAIL", "share overwrite", "cannot replace an existing file (%s): "
                   "Write without Delete" % _err(exc),
                   "grant Modify, not Write: students must be able to overwrite their own files")
            leftovers.append(tmp2)
        started = time.time()
        seen = None
        while time.time() - started < 15:
            if os.path.basename(final) in os.listdir(folder):
                seen = time.time() - started
                break
            time.sleep(0.25)
        if seen is None:
            report("FAIL", "share listing", "own file not visible after 15 s",
                   "the share is slow or cached; use a different server/path")
        else:
            report("PASS" if seen < 5 else "WARN", "share listing",
                   "own file visible after %.1f s" % seen,
                   "slow directory refresh: play-by-mail will lag a few seconds" if seen >= 5 else "")
        with open(final, "rb") as handle:
            size = len(handle.read())
        report("PASS" if size == 20000 else "FAIL", "share read-back", "%d bytes" % size,
               "the file changed on the way: antivirus or sync software on the share?"
               if size != 20000 else "")
        try:
            os.remove(final)
            report("PASS", "share delete", "ok")
        except OSError as exc:
            report("WARN", "share delete", "denied (%s)" % _err(exc),
                   "leftover files will pile up; ask for Modify rights")
            leftovers.append(final)
    except OSError as exc:
        report("FAIL", "share", _err(exc), "check the path and your rights")
    finally:
        for name in leftovers + [final]:
            try:
                os.remove(name)
            except OSError:
                pass
        try:
            for name in os.listdir(folder):
                os.remove(os.path.join(folder, name))
            os.rmdir(folder)
        except OSError:
            pass


# -- HTTPS -----------------------------------------------------------------

def _ssl_context():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        from GameLogic.LLMClient import _make_ssl_context
        return _make_ssl_context()
    except Exception:
        return ssl.create_default_context(), ""


def _llm_url():
    """The configured model endpoint, without importing anything heavy."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        from GameLogic.LLMClient import LLMConfig
        return LLMConfig().base_url + "/models"
    except Exception:
        return os.environ.get("BOP_LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/models"


def check_https(url, label, expect_json=False):
    """GET ``url`` (no credentials) through the system proxy settings."""
    host = urllib.parse.urlsplit(url).hostname or url
    name = "%s" % label
    context, note = _ssl_context()
    if not COUNTS.get("proxy_shown"):
        COUNTS["proxy_shown"] = 1
        proxies = urllib.request.getproxies()
        report("INFO", "proxy settings", json.dumps(proxies) if proxies else
               "none visible to Python (a PAC/WPAD script would NOT be seen)")
    started = time.time()
    request = urllib.request.Request(url, headers={"User-Agent": "bop-netcheck"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(),
                                         urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read(4096)
            ctype = response.headers.get("Content-Type", "")
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read(4096)
        except Exception:
            body = b""
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        if status == 407:
            report("FAIL", name, "proxy wants a login (HTTP 407)",
                   "set HTTPS_PROXY=http://user:pass@proxy:port; NTLM/Kerberos-only "
                   "proxies cannot be used: ask IT to allow %s" % host)
            return
        if _html(body, ctype):
            report("FAIL", name, "HTTP %d, but the answer is a web page (a web filter blocked %s)"
                   % (status, host), "ask IT to allow %s" % host)
            return
        report("PASS", name, "server answered HTTP %d in %d ms" % (status, (time.time() - started) * 1000))
        return
    except urllib.error.URLError as exc:
        reason = exc.reason
        text = str(reason)
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = getattr(reason, "verify_message", "") or text
            fix = ("the network inspects HTTPS: set SSL_CERT_FILE to your organisation's "
                   "root CA .pem file")
            if note:
                fix += " (" + note + ")"
            report("FAIL", name, "certificate not trusted: %s" % detail, fix)
        elif isinstance(reason, socket.gaierror):
            report("FAIL", name, "DNS cannot resolve %s" % host,
                   "the name is blocked or there is no DNS; ask IT to allow it")
        elif "Tunnel connection failed: 407" in text:
            report("FAIL", name, "proxy wants a login (407)",
                   "set HTTPS_PROXY=http://user:pass@proxy:port; NTLM/Kerberos-only proxies are not supported")
        elif "Tunnel connection failed: 403" in text:
            report("FAIL", name, "proxy forbids %s (403 on CONNECT)" % host, "ask IT to allow it")
        elif isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in text:
            report("FAIL", name, "no answer in 10 s",
                   "packets are being dropped (firewall) or a proxy is needed: set HTTPS_PROXY")
        elif isinstance(reason, ConnectionRefusedError):
            report("FAIL", name, "connection refused", "wrong proxy address, or the port is blocked")
        else:
            report("FAIL", name, text, "check the network and proxy settings")
        return
    except Exception as exc:
        report("FAIL", name, "%s: %s" % (type(exc).__name__, exc), "check the network")
        return
    ms = (time.time() - started) * 1000
    if expect_json and _html(body, ctype):
        report("FAIL", name, "HTTP %d, but the answer is a web page, not the API (a web filter "
               "blocked %s?)" % (status, host), "ask IT to allow %s" % host)
    elif note:
        report("WARN", name, "HTTP %d in %d ms" % (status, ms), note)
    else:
        report("PASS", name, "HTTP %d in %d ms" % (status, ms))


def _html(body, ctype):
    head = body.lstrip()[:200].lower()
    return "html" in (ctype or "").lower() or head.startswith((b"<html", b"<!doctype", b"<head", b"<body"))


# -- command line ----------------------------------------------------------

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="netcheck.py", description="Balance of Power network self-check.",
        epilog="Run on the teacher PC and on one student PC the day before.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="game TCP port (default 45454)")
    parser.add_argument("--peer", metavar="IP[:PORT]", help="connect to a host's game")
    parser.add_argument("--relay", metavar="IP", help="probe the teacher's relay (TCP 46000-46019)")
    parser.add_argument("--share", metavar="PATH", help="test a shared folder, e.g. \\\\TEACHER\\bop-mail")
    parser.add_argument("--llm", nargs="?", const="", default=None, metavar="URL",
                        help="HTTPS test of the model endpoint (default: the configured one); no key is sent")
    parser.add_argument("--pypi", action="store_true", help="HTTPS test of pypi.org")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be a port number from 1 to 65535 (got %d)" % args.port)

    print("Balance of Power network check - %s" % time.strftime("%Y-%m-%d %H:%M"))
    check_python()
    check_pyqt()
    check_user_dir()
    check_addresses()
    check_bind(args.port)
    check_broadcast()
    if args.peer:
        check_peer(args.peer)
    if args.relay:
        check_relay(args.relay)
    if args.share:
        check_share(args.share)
    if args.llm is not None:
        check_https(args.llm or _llm_url(), "model endpoint", expect_json=True)
    if args.pypi:
        check_https("https://pypi.org/simple/pyqt5/", "pypi.org")
    print("\nSummary: %d passed, %d warnings, %d failed"
          % (COUNTS["PASS"], COUNTS["WARN"], COUNTS["FAIL"]))
    return 1 if COUNTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
