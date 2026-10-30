"""
Talking to an OpenAI-compatible chat-completions endpoint.

The game only needs one shape of request — a system prompt, a user prompt, and
a JSON answer back — so this is deliberately small and dependency-free: it uses
``urllib`` from the standard library rather than pulling in ``requests``.  That
matters for the corporate deployments this port targets, where adding a
dependency is a procurement question and the proxy is already configured for the
browser but not for a fresh virtualenv.

Configuration is resolved in this order, first match wins:

1. explicit constructor arguments;
2. environment variables (``BOP_LLM_BASE_URL``, ``BOP_LLM_MODEL``,
   ``BOP_LLM_API_KEY``, ``OPENROUTER_API_KEY``, and the standard proxy variables);
3. ``llm.json`` in the per-user data directory.

The API key is never written to the log and never included in an exception
message.
"""

import http.client
import json
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import Paths

#: OpenRouter's public endpoint.  Any OpenAI-compatible service works.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
#: The model the fifth difficulty level uses by default.
#:
#: ``typesafe/jev-1.13`` is an *unlisted* OpenRouter model: the page exists, but
#: it is absent from the public ``/api/v1/models`` catalogue and returns 404 to
#: an unauthenticated request, so it only resolves for an account that has been
#: granted access.  That is exactly why the id is a setting rather than a
#: constant: point it at anything OpenAI-compatible, including an internal
#: corporate model, with ``BOP_LLM_MODEL``.
DEFAULT_MODEL = "typesafe/jev-1.13"
#: Local, deterministic stand-in used when there is no network or no key.
MOCK_MODEL = "mock/heuristic"

CONFIG_FILENAME = "llm.json"
DEFAULT_TIMEOUT = 30.0
#: The most a provider may send back.  A chat answer is a few kilobytes; a
#: misbehaving proxy or endpoint streaming gigabytes must not be read into memory.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_RETRIES = 2
#: Model calls allowed per game before falling back to the built-in AI.
DEFAULT_MAX_REQUESTS = 80
#: Decision models answer at a different endpoint and cannot write prose.
#: The advisors need a text model, so one is named separately.
#: The advisor model.  Deliberately not the opponent model: the fifth-level
#: opponent is a *decisions* model and cannot write prose at all.  Qwen 3.8 27B
#: is cheap, follows a character brief closely, and - importantly - can be told
#: to skip its reasoning pass (see ``disable_reasoning``).
DEFAULT_CHAT_MODEL = "qwen/qwen3.8-27b"
#: Model ids that are decision models rather than chat models.
_DECISION_MARKERS = ("jev", "systemone", "system-one", "typesafe/")


def is_decision_model(model_id):
    """True when this id must go to the Decisions API, not chat/completions."""
    if not model_id:
        return False
    lowered = model_id.lower()
    return any(marker in lowered for marker in _DECISION_MARKERS)


class LLMError(Exception):
    """Any failure while talking to the model."""


class LLMNotConfigured(LLMError):
    """No API key and no reachable local backend."""


class LLMTimeout(LLMError):
    """The request did not complete inside the timeout."""


#: Anything shaped like a credential: an OpenRouter/OpenAI key, or a bearer token.
#: One regex pass cannot loop, which a find-and-replace-until-gone loop does as
#: soon as the replacement ("sk-***") still contains the marker it searched for.
_KEY_RE = re.compile(r"(?<![A-Za-z0-9])(sk-or-|sk-|Bearer\s+)[^\s\"',]*")


def _redact(text, secret=None):
    """Strip anything that looks like a key out of a message we are about to log.

    ``secret`` is the configured key itself: a key without the ``sk-`` prefix
    (an internal gateway token, say) is invisible to the pattern, so it is
    removed by value as well.
    """
    if not text:
        return text
    out = str(text)
    if secret and len(secret) >= 4:
        out = out.replace(secret, "***")
    return _KEY_RE.sub(
        lambda m: "Bearer ***" if m.group(1).startswith("Bearer") else m.group(1) + "***",
        out)


# ---------------------------------------------------------------------------
# One clock for one unit of work, a failure vocabulary, and shared limits
# ---------------------------------------------------------------------------

class Deadline(object):
    """A wall-clock allowance shared by every call that makes up one unit of work.

    A turn of the Adaptive opponent is several sequential requests, each with
    its own retries.  Giving each of them its own timeout multiplied the wait
    the player was promised; one ``Deadline`` per turn is handed to all of them
    and each clamps itself to what is left.  ``cancel`` is how the UI thread
    tells an abandoned worker to stop trying further attempts and models.
    """

    def __init__(self, seconds, parent=None):
        self.seconds = float(seconds)
        self.expires = time.monotonic() + self.seconds
        self._cancelled = threading.Event()
        #: A larger allowance this one lives inside: never later than it, and
        #: cancelled with it.
        self.parent = parent
        if parent is not None:
            self.expires = min(self.expires, parent.expires)

    def remaining(self):
        return self.expires - time.monotonic()

    def cancel(self):
        self._cancelled.set()

    @property
    def cancelled(self):
        return self._cancelled.is_set() or (
            self.parent is not None and self.parent.cancelled)

    def expired(self):
        return self.cancelled or self.remaining() <= 0.0


def parse_retry_after(value, now=None):
    """Seconds a ``Retry-After`` header asks us to wait, or ``None``.

    The header is either a number of seconds or an HTTP date.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
        return seconds if seconds >= 0 and seconds == seconds else None
    except ValueError:
        pass
    try:
        import email.utils
        when = email.utils.parsedate_to_datetime(text)
        if when is None:
            return None
        if when.tzinfo is None:
            import datetime
            when = when.replace(tzinfo=datetime.timezone.utc)
        import datetime
        current = datetime.datetime.now(datetime.timezone.utc) if now is None else now
        return max(0.0, (when - current).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


#: What went wrong, in the six ways a player can act on.  ``failure_kind`` maps
#: any exception onto one of them; the opponent log and the one-time notice use
#: ``failure_phrase``.  The phrases are fixed text and never contain the
#: exception's own message, so nothing that looks like a key can reach the UI.
FAILURE_PHRASES = {
    "unreachable": "could not be reached",
    "unusable": "answered with something unusable",
    "key": "rejected the API key",
    "filter": "was blocked by a web filter or proxy",
    "certificate": "could not be reached because its certificate is not trusted",
    "model": "is not available from this provider",
    "busy": "is rate-limited and asked us to wait",
    "budget": "has used up its call budget",
}
#: Failures that are the line's fault, repeat identically, and justify giving up.
TRANSPORT_KINDS = ("unreachable", "key", "filter", "certificate", "model", "busy")


def failure_kind(exc):
    """Classify a failure as one of :data:`FAILURE_PHRASES`' keys."""
    if isinstance(exc, LLMNotConfigured):
        return "key"
    text = str(exc).lower()
    if "certificate" in text:
        return "certificate"
    if "api key was rejected" in text:
        return "key"
    if ("web filter" in text or "proxy wants a login" in text
            or "proxy forbids" in text or "proxy refused" in text):
        return "filter"
    if "answer budget" in text:
        return "unusable"
    if "budget" in text and "used up" in text:
        return "budget"
    if "not found at" in text or "is not available at the decisions" in text:
        return "model"
    if text.startswith("http 429") or "asked us to wait" in text:
        return "busy"
    for marker in ("not json", "empty answer", "unexpected response shape",
                   "no json object", "malformed", "did not return",
                   "returned no answers", "was not a list", "did not answer",
                   "could not read the response", "request was rejected",
                   "larger than", "not an object", "no usable", "nothing usable"):
        if marker in text:
            return "unusable"
    return "unreachable"


def failure_phrase(exc):
    return FAILURE_PHRASES[failure_kind(exc)]


class SharedBudget(object):
    """One count of model calls for the whole game, whoever makes them.

    The opponent and the advisors use different models through different
    clients; with a budget each, the cap the player set was really twice that.
    The opponent creates one per game and hangs it on the configuration, so a
    client made later for the advisors (from a copy of that configuration)
    counts against the same total.  Held by weak reference to its owner: once
    the game that made it is gone, a stale count must not follow the player
    into the next game.
    """

    def __init__(self, owner=None):
        import weakref
        self._lock = threading.Lock()
        self.used = 0
        self._owner = weakref.ref(owner) if owner is not None else None

    @property
    def alive(self):
        return self._owner is None or self._owner() is not None

    def add(self, amount=1):
        with self._lock:
            self.used += amount


class FailureBreaker(object):
    """Stops asking a model that keeps failing at the transport level.

    Used by the advisors, whose every use would otherwise block for the full
    retries against a dead endpoint.  ``limit`` consecutive transport failures
    trip it; it stays tripped until the player changes the settings.
    """

    def __init__(self, limit=2):
        self.limit = limit
        self.failures = 0
        self.tripped = False
        self.reason = ""
        self.announced = False
        self._fingerprint = None

    def sync(self, config):
        """Close the breaker again when the endpoint, key or model changed."""
        fingerprint = (getattr(config, "base_url", None), getattr(config, "api_key", None),
                       getattr(config, "model", None))
        if self._fingerprint is not None and fingerprint != self._fingerprint:
            self.reset()
        self._fingerprint = fingerprint

    def success(self):
        self.failures = 0

    def reset(self):
        self.failures = 0
        self.tripped = False
        self.reason = ""
        self.announced = False

    def failure(self, exc):
        """Record a failure; returns True if this one tripped the breaker."""
        kind = failure_kind(exc)
        if kind not in TRANSPORT_KINDS:
            return False
        self.failures += 1
        if self.failures >= self.limit and not self.tripped:
            self.tripped = True
            self.reason = FAILURE_PHRASES[kind]
            return True
        return False

    def take_notice(self):
        """True exactly once after the breaker trips."""
        if self.tripped and not self.announced:
            self.announced = True
            return True
        return False


# ---------------------------------------------------------------------------
# Network failure classification (shared with JevClient)
#
# On a managed network the usual causes of "the model does not answer" are not
# the model's: a TLS-inspecting proxy, a proxy that wants a login, a web filter
# that answers with an HTML block page, DNS that is sinkholed, or packets that
# are silently dropped.  Each needs a different one-line fix, and none of them
# is cured by retrying, so each is named once and raised without a retry.
# ---------------------------------------------------------------------------

def _host_of(base_url):
    """The host name of a URL, for messages."""
    try:
        return urllib.parse.urlsplit(base_url).hostname or base_url
    except ValueError:
        return base_url


def _looks_html(data, content_type=""):
    """True when a body is a web page rather than an API answer."""
    if "html" in (content_type or "").lower():
        return True
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    if not isinstance(data, str):
        return False
    head = (data or "").lstrip()[:200].lower()
    return head.startswith(("<html", "<!doctype", "<head", "<body", "<?xml")) \
        or "<html" in head


def _block_error(host, code):
    return LLMError("a web filter blocked %s (it answered with a web page, HTTP %s "
                    "- not the API); ask IT to allow %s" % (host, code, host))


def _proxy_login_error(host):
    return LLMError("the proxy wants a login (HTTP 407); set "
                    "HTTPS_PROXY=http://user:pass@proxy:port. Proxies that accept "
                    "only NTLM/Kerberos are not supported: ask IT to allow %s" % host)


def _classify_http_error(code, body, content_type, host):
    """An :class:`LLMError` for an HTTP error that is the network's doing, else None.

    A 403 whose body is an HTML page is a web filter, not "API key rejected".
    """
    if code == 407:
        return _proxy_login_error(host)
    if _looks_html(body, content_type) and code not in (429,) \
            and not 500 <= code < 600:
        return _block_error(host, code)
    return None


def _classify_network_error(exc, base_url, secret=None, tls_note=""):
    """Turn a urllib/socket failure into ``(LLMError, retryable)``.

    Only genuinely transient failures (a reset connection, a 5xx handled by the
    caller) are retryable.  TLS, DNS, proxy and dropped-packet failures repeat
    identically, so retrying them only makes the player wait.
    """
    host = _host_of(base_url)
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    if isinstance(reason, ssl.SSLCertVerificationError):
        detail = (getattr(reason, "verify_message", "") or text)
        low = detail.lower()
        if "hostname mismatch" in low or "ip address mismatch" in low:
            msg = ("the certificate of %s is for a different name (%s); a web "
                   "filter or login page is intercepting HTTPS" % (host, detail))
        elif "expired" in low or "not yet valid" in low:
            msg = ("the certificate of %s is outside its dates (%s); check the "
                   "PC's date and time" % (host, detail))
        else:
            msg = ("the network inspects HTTPS and its certificate is not trusted "
                   "(%s); set SSL_CERT_FILE to your organisation's root CA .pem "
                   "file" % detail)
            if any(k in low for k in ("key usage", "not marked critical",
                                      "authority key", "subject key")):
                msg += (" (this CA looks old-style; unset BOP_TLS_STRICT, "
                        "or use Python 3.12)")
        if tls_note:
            msg += ". NOTE: " + tls_note
        return LLMError(_redact(msg, secret)), False
    if isinstance(reason, ssl.SSLError):
        if "timed out" in text.lower():
            return LLMTimeout(_timeout_text(host)), False
        return LLMError("the TLS handshake with %s failed (%s); a proxy or filter "
                        "may be interfering" % (host, _redact(text, secret))), False
    if isinstance(reason, socket.gaierror):
        return LLMError("DNS cannot resolve %s (the name is blocked or there is "
                        "no DNS); ask IT to allow it" % host), False
    if "Tunnel connection failed: 407" in text:
        return _proxy_login_error(host), False
    if "Tunnel connection failed: 403" in text:
        return LLMError("the proxy forbids %s (HTTP 403 on CONNECT); ask IT to "
                        "allow it" % host), False
    if "Tunnel connection failed" in text:
        return LLMError("the proxy refused to connect to %s (%s)"
                        % (host, _redact(text, secret))), False
    if isinstance(reason, ConnectionRefusedError):
        return LLMError("connection to %s was refused (nothing is listening, or "
                        "the proxy address is wrong)" % host), False
    if isinstance(reason, (socket.timeout, TimeoutError)) \
            or "timed out" in text.lower():
        return LLMTimeout(_timeout_text(host)), False
    return LLMError("could not reach %s (%s)" % (host, _short_reason(reason, secret))), True


def _short_reason(reason, secret=None):
    """A few words for a transient failure, in English and not the OS locale.

    ``str(ConnectionResetError)`` is the operating system's own text, in the
    operating system's own language; the exception class says the same thing in
    a way every reader can use.
    """
    names = (
        (ConnectionResetError, "the connection was reset"),
        (BrokenPipeError, "the connection was cut"),
        (ConnectionAbortedError, "the connection was aborted"),
        (ConnectionRefusedError, "the connection was refused"),
        (ConnectionError, "the connection failed"),
        (http.client.RemoteDisconnected, "the server hung up without answering"),
    )
    for kind, words in names:
        if isinstance(reason, kind):
            return words
    text = _redact(str(reason), secret)
    if text and text.isascii() and len(text) <= 80:
        return text
    return type(reason).__name__


def _timeout_text(host):
    return ("no answer from %s: the network may be silently dropping the "
            "traffic (a firewall), or the service is very slow" % host)


def _make_ssl_context():
    """A TLS context that honours a corporate CA bundle: ``(context, note)``.

    ``create_default_context(cafile=...)`` *replaces* the trust store rather
    than adding to it, so pointing REQUESTS_CA_BUNDLE at a corporate-only
    bundle would break every public endpoint.  Load the system store first,
    then add the extra roots on top.  On Windows ``load_default_certs`` reads the
    OS ROOT store, so a normally-installed interception root needs no
    configuration at all.

    ``note`` is empty, or says that a bundle named by an environment variable
    is missing or unreadable (it used to be ignored silently, leaving only a
    baffling "certificate verify failed").

    VERIFY_X509_STRICT: Python 3.13 turned this flag on by default, and it
    rejects many older corporate root CAs (no Subject Key Identifier, basic
    constraints not marked critical) that every browser accepts.  We clear it
    **by default**.  That is safe to do because the flag only enforces extra
    RFC 5280 conformance rules on the certificates; the chain is still verified
    to a trusted root, signatures, validity dates and the host name are still
    checked, and verification stays on (CERT_REQUIRED, check_hostname).  A
    classroom game gains nothing from refusing a CA that Windows itself trusts.
    ``BOP_TLS_STRICT=1`` restores the stricter behaviour.
    """
    context = ssl.create_default_context()
    if not os.environ.get("BOP_TLS_STRICT") and hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    note = ""
    for var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        cafile = os.environ.get(var)
        if not cafile:
            continue
        if not os.path.isfile(cafile):
            note = "%s points to a file that does not exist (%s)" % (var, cafile)
        else:
            try:
                context.load_verify_locations(cafile=cafile)
            except (OSError, ssl.SSLError):
                # The system store is still loaded, so public endpoints keep
                # working; just say why the extra roots did not take effect.
                note = "%s points to a file that is not a valid .pem (%s)" % (var, cafile)
        break
    return context, note


def _read_limited(response, limit=MAX_RESPONSE_BYTES, deadline=None):
    """Read a response body, refusing one that is larger than ``limit``.

    With a ``deadline`` the body is read in pieces and the clock is checked
    between them: the socket timeout only limits the silence between two
    packets, so an endpoint that dribbles one byte a second would otherwise
    hold the caller for as long as it likes.
    """
    if deadline is None:
        data = response.read(limit + 1)
    else:
        chunks = []
        size = 0
        reader = getattr(response, "read1", None) or response.read
        while True:
            if deadline.expired():
                raise LLMTimeout("the answer was still arriving when the time "
                                 "allowed ran out")
            chunk = reader(65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                break
        data = b"".join(chunks)
    if len(data) > limit:
        raise LLMError("the response was larger than %d MB; ignoring it"
                       % (limit // (1024 * 1024)))
    return data


def _number(value, default, cast):
    """``cast(value)``, or ``default`` when a hand-edited file holds nonsense."""
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _clean(value):
    """A configuration string without surrounding whitespace / CR / LF."""
    return value.strip() if isinstance(value, str) else value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would re-send the Authorization header to the
    new host (a captive portal or web filter), leaking the API key."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LLMConfig(object):
    """Where to send requests, and how."""

    def __init__(self, base_url=None, model=None, api_key=None, temperature=None,
                 max_tokens=None, timeout=None, offline=None,
                 fallback_models=None, max_requests=None, backend=None,
                 chat_model=None, disable_reasoning=None):
        # Every numeric and boolean default is ``None`` meaning "use the saved
        # value, else the built-in one".  A concrete default here would always
        # win over ``llm.json`` and the settings window would save values that
        # the next launch silently ignored.
        stored = self._load_stored()
        # Values pasted from a .bat/.ps1 file or a web page often carry a
        # trailing CR/LF or space, which breaks the URL or the header.
        self.base_url = _clean(base_url or os.environ.get("BOP_LLM_BASE_URL")
                               or stored.get("base_url") or DEFAULT_BASE_URL
                               ).rstrip("/")
        self.model = _clean(model or os.environ.get("BOP_LLM_MODEL")
                            or stored.get("model") or DEFAULT_MODEL)
        #: A key that came from the environment.  ``save`` must not copy it into
        #: ``llm.json``: the file outlives the shell session that exported it.
        self._env_key = _clean(os.environ.get("BOP_LLM_API_KEY")
                               or os.environ.get("OPENROUTER_API_KEY") or "")
        self.api_key = _clean(api_key or self._env_key or stored.get("api_key") or "")
        self.temperature = _number(
            temperature if temperature is not None else stored.get("temperature", 0.7),
            0.7, float)
        self.max_tokens = _number(
            max_tokens if max_tokens is not None else stored.get("max_tokens", 1200),
            1200, int)
        self.timeout = _number(
            timeout if timeout is not None else stored.get("timeout", DEFAULT_TIMEOUT),
            DEFAULT_TIMEOUT, float)
        self.offline = bool(offline if offline is not None
                            else stored.get("offline", False))
        #: Models to try when the first one is unavailable.  An unlisted model
        #: (like typesafe/jev-1.13) returns 404 the moment access lapses, and a
        #: game should not stall because of it.
        if fallback_models is None:
            fallback_models = stored.get("fallback_models") or []
        self.fallback_models = [m for m in fallback_models if m and m != self.model]
        #: Hard ceiling on model calls per game, so a long session cannot run up
        #: a bill nobody agreed to.  ``None`` means "use the stored value or the
        #: default"; pass ``0`` for genuinely unlimited, which is what the
        #: settings window offers as "no limit".
        if max_requests is None:
            max_requests = stored.get("max_requests", DEFAULT_MAX_REQUESTS)
        try:
            max_requests = int(max_requests)
        except (TypeError, ValueError):
            max_requests = DEFAULT_MAX_REQUESTS
        self.max_requests = max_requests if max_requests > 0 else None
        #: "decisions" for a decision model (Jev), "chat" for a text model, or
        #: "auto" to pick from the model id.  They are different APIs with
        #: different payloads; guessing wrong is a 400 from the provider.
        self.backend = (backend or stored.get("backend") or "auto").lower()
        #: A text model for the advisor chat.  The opponent may be Jev, which
        #: cannot write prose at all, so the two roles need separate models.
        self.chat_model = (chat_model or os.environ.get("BOP_LLM_CHAT_MODEL")
                           or stored.get("chat_model") or DEFAULT_CHAT_MODEL)
        #: Ask the provider not to run a reasoning pass.  Hybrid "thinking"
        #: models put their scratchpad in ``message.reasoning`` and the answer in
        #: ``message.content``; under a modest token budget the scratchpad eats
        #: the whole allowance and the answer comes back empty.  Turning it off
        #: is both more reliable and - measured on qwen3.8-27b - about three
        #: times cheaper, and nothing here is a maths problem.
        self.disable_reasoning = bool(
            disable_reasoning if disable_reasoning is not None
            else stored.get("disable_reasoning", True))
        #: The game's shared call count (see :class:`SharedBudget`), or None.
        #: Set by the opponent at the start of a game; copied to the advisors'
        #: configuration so the cap is a total, not one cap per model.
        self.game_budget = None

    def active_budget(self):
        """The shared count for the game in progress, or None."""
        budget = self.game_budget
        return budget if budget is not None and budget.alive else None

    def resolved_backend(self):
        """Which API this configuration actually talks to."""
        if self.backend in ("decisions", "chat"):
            return self.backend
        return "decisions" if is_decision_model(self.model) else "chat"

    def adversarial_config(self):
        """A copy pointed at the text model, for the advisors."""
        # ``max_requests=None`` would mean "use the default", so an unlimited
        # budget (None here) is passed as the explicit 0.  The fallbacks are the
        # opponent's; a decisions model among them cannot answer a chat request.
        clone = LLMConfig(base_url=self.base_url, model=self.chat_model,
                          api_key=self.api_key, temperature=self.temperature,
                          max_tokens=self.max_tokens, timeout=self.timeout,
                          offline=self.offline, max_requests=self.max_requests or 0,
                          fallback_models=[m for m in self.fallback_models
                                           if not is_decision_model(m)],
                          chat_model=self.chat_model,
                          disable_reasoning=self.disable_reasoning)
        clone.backend = "chat"
        clone.game_budget = self.game_budget
        return clone

    @staticmethod
    def _load_stored():
        try:
            with open(Paths.user_file(CONFIG_FILENAME), encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self):
        """Persist the settings (including the key) under the user data dir."""
        key = self.api_key
        if self._env_key and key == self._env_key:
            # Supplied by the environment: keep whatever was saved before (the
            # user's own stored key, or nothing) rather than writing a secret
            # to disk that they only ever exported for one shell.
            key = self._load_stored().get("api_key") or ""
        payload = {
            "base_url": self.base_url,
            "model": self.model,
            "api_key": key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "offline": self.offline,
            "fallback_models": self.fallback_models,
            "max_requests": self.max_requests or 0,
            "backend": self.backend,
            "chat_model": self.chat_model,
            "disable_reasoning": bool(self.disable_reasoning),
        }
        path = Paths.user_file(CONFIG_FILENAME)
        # Created owner-only from the first byte: writing with the default mode
        # and tightening afterwards leaves the key world-readable in between.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        try:
            os.chmod(path, 0o600)       # a file that already existed keeps its mode
        except OSError:
            pass
        return path

    @property
    def usable(self):
        """True when we have enough to make a real request."""
        return bool(self.api_key) and not self.offline

    def model_chain(self):
        """The models to try, in order."""
        return [self.model] + list(self.fallback_models)

    def describe(self):
        if self.fallback_models:
            return "%s (+%d fallback) @ %s" % (self.model, len(self.fallback_models),
                                               self.base_url)
        return "%s @ %s" % (self.model, self.base_url)


#: The shape the opponent's answer must have, as a JSON schema.
#:
#: Sending this instead of the loose ``{"type": "json_object"}`` makes providers
#: that support structured outputs guarantee the shape, which removes a whole
#: class of failure: a model that wraps its JSON in prose, or omits ``actions``,
#: or nests the list a level deeper than asked.  Providers that do not support
#: it reject the request, so the client falls back to the loose form the first
#: time that happens and remembers not to try again this game.
POLICY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "policy_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "target": {"type": "integer"},
                            "level": {"type": "integer"},
                        },
                        "required": ["action", "target", "level"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["reasoning", "actions"],
            "additionalProperties": False,
        },
    },
}

#: What to fall back to when the provider refuses the schema above.
LOOSE_JSON = {"type": "json_object"}


def uses_schema(response_format):
    """Whether this response_format asks for a strict schema."""
    return bool(response_format) and response_format.get("type") == "json_schema"


class LLMClient(object):
    """One chat-completions call, with retries, caching and honest errors."""

    def __init__(self, config=None):
        self.config = config or LLMConfig()
        #: Guards the counters: the request runs on a worker thread while the
        #: settings window and the status bar read them on the GUI thread.
        self._lock = threading.Lock()
        #: What this game has spent so far.
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "total_tokens": 0, "cache_hits": 0, "failures": 0}
        #: None until the provider has shown whether it accepts a JSON schema.
        self._schema_supported = None
        #: A human-readable note about a downgrade, for the settings window.
        self.schema_note = ""
        #: None until the provider has shown whether it accepts ``reasoning``.
        self._reasoning_supported = None
        #: Whether the request currently being built should carry the field.
        self._send_reasoning = False
        #: Answers already paid for, keyed by model + messages.  Off by default:
        #: silently returning an old answer is a surprising thing for a caller to
        #: get, and only the advisor chat actually benefits.
        self.cache = {}
        #: Why a CA bundle named in the environment was ignored, if it was.
        self.tls_note = ""
        #: Used by the advisors (see AdvisorChat.guarded_chat); the opponent has
        #: its own breaker and never reads this one.
        self.advisor_breaker = FailureBreaker()

    # -- transport ----------------------------------------------------------

    def _ssl_context(self):
        """See :func:`_make_ssl_context`; remembers why a bundle was ignored."""
        context, self.tls_note = _make_ssl_context()
        return context

    def _build_request(self, messages, response_format, model=None):
        body = {
            "model": model or self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if response_format:
            body["response_format"] = response_format
        if getattr(self, "_send_reasoning", False):
            # An OpenRouter extension.  A provider that does not know the field
            # may reject the whole request, so this is sent optimistically and
            # dropped for the rest of the game the first time that happens.
            body["reasoning"] = {"enabled": False}
        request = urllib.request.Request(
            self.config.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % self.config.api_key,
                # OpenRouter uses these for attribution; harmless elsewhere.
                "HTTP-Referer": "https://localhost/balance-of-power",
                "X-Title": "Balance of Power",
                "User-Agent": "BalanceOfPower/1.0",
            },
            method="POST")
        return request

    def budget_left(self):
        """How many model calls remain this game, or None when unlimited."""
        if not self.config.max_requests:
            return None
        shared = self.config.active_budget() if hasattr(self.config, "active_budget") else None
        used = max(shared.used if shared is not None else 0, self.usage["requests"])
        return max(0, self.config.max_requests - used)

    def _bump(self, field, amount=1):
        with self._lock:
            self.usage[field] += amount
        if field == "requests":
            shared = self.config.active_budget() if hasattr(self.config, "active_budget") else None
            if shared is not None:
                shared.add(amount)

    def chat(self, messages, response_format=None, timeout=None, use_cache=False,
             model=None, deadline=None):
        """Return the assistant's text, or raise :class:`LLMError`.

        ``model`` overrides ``config.model`` for this one call, so a fallback
        chain never has to rewrite the shared configuration.  ``deadline`` is a
        :class:`Deadline` shared with the caller's other calls: this call never
        outlives it, and stops at once if the caller cancels it.
        """
        if self.config.offline:
            raise LLMNotConfigured("offline mode is on; no model calls are made")
        if not self.config.api_key:
            raise LLMNotConfigured("no API key configured")
        self._check_settings()
        model = model or self.config.model
        limit = self.budget_left()
        if limit is not None and limit <= 0:
            raise LLMError("the per-game model budget of %d calls is used up"
                           % self.config.max_requests)

        key = None
        if use_cache:
            key = self._cache_key(messages, response_format, model)
            if key in self.cache:
                self._bump("cache_hits")
                return self.cache[key]
        timeout = timeout or self.config.timeout
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),          # honour HTTP(S)_PROXY
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=self._ssl_context()))

        last = None
        host = _host_of(self.config.base_url)
        # Everything retried together may take at most 1.5 x the timeout, so a
        # network that drops packets cannot hold the game for minutes.
        shared = deadline
        if shared is not None and shared.expired():
            raise LLMTimeout("no time left for this request")
        own = Deadline(timeout * 1.5, parent=shared)
        deadline = own.expires          # the monotonic instant used below
        for attempt in range(MAX_RETRIES + 1):
            if attempt and (time.monotonic() >= deadline or own.cancelled):
                break
            call_timeout = max(0.25, min(timeout, deadline - time.monotonic()))
            effective = response_format
            if effective is not None and self._schema_supported is False \
                    and uses_schema(effective):
                effective = LOOSE_JSON
            uses_reasoning = (self.config.disable_reasoning
                              and self._reasoning_supported is not False)
            self._send_reasoning = uses_reasoning
            request = self._build_request(messages, effective, model)
            try:
                with opener.open(request, timeout=call_timeout) as response:
                    raw = _read_limited(response, deadline=own)
                    ctype = response.headers.get("Content-Type", "")
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except ValueError:
                    if _looks_html(raw, ctype):
                        raise _block_error(host, "200")
                    raise
                text = self._extract(payload, self.config.api_key)
                if uses_schema(effective):
                    self._schema_supported = True
                if uses_reasoning:
                    # Only a *successful* request that actually carried the
                    # field proves the provider accepts it.  Setting this on the
                    # retry - which deliberately omits the field - would wipe
                    # out the downgrade that was just recorded.
                    self._reasoning_supported = True
                # Only a call that produced an answer counts against the budget.
                self._bump("requests")
                self._account(payload)
                if key is not None:
                    self.cache[key] = text
                return text
            except urllib.error.HTTPError as exc:
                if 300 <= exc.code < 400:
                    # Not followed on purpose (see _NoRedirect).
                    target = (exc.headers.get("Location", "") if exc.headers else "")
                    where = _host_of(target) if target else "another address"
                    self._bump("failures")
                    raise LLMError("the request to %s was redirected to %s "
                                   "(HTTP %s) - probably a web filter or captive "
                                   "portal; ask IT to allow %s"
                                   % (host, where, exc.code, host))
                detail = ""
                try:
                    detail = exc.read(4096).decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                last = LLMError("HTTP %s from %s: %s"
                                % (exc.code, self.config.base_url,
                                   _redact(detail, self.config.api_key)))
                network = _classify_http_error(
                    exc.code, detail, exc.headers.get("Content-Type", "")
                    if exc.headers else "", host)
                if network is not None:
                    raise network
                if exc.code in (401, 403):
                    raise LLMError("the API key was rejected (HTTP %s)" % exc.code)
                if exc.code == 404:
                    raise LLMError("model %r not found at %s"
                                   % (model, self.config.base_url))
                if exc.code == 429 or 500 <= exc.code < 600:
                    asked = parse_retry_after(exc.headers.get("Retry-After")
                                              if exc.headers else None)
                    wait = (asked if asked is not None
                            else 0.8 * (2 ** attempt) + random.random() * 0.3)
                    if asked is not None and asked > deadline - time.monotonic() - 0.5:
                        # The service says to wait longer than this call may
                        # take.  Retrying early only earns another refusal.
                        self._bump("failures")
                        raise LLMError("HTTP %s: the service asked us to wait %.0f s, "
                                       "longer than the time allowed"
                                       % (exc.code, asked))
                    self._pause(wait, deadline)
                    continue
                # Only a 400 that actually complains about the field counts.
                # Treating every 400 as a rejection would silently switch the
                # setting off (and mislabel the reason) the first time a provider
                # refused the request for some entirely different cause.
                mentions_reasoning = "reasoning" in detail.lower()
                if exc.code == 400 and self._reasoning_supported is None \
                        and self.config.disable_reasoning and mentions_reasoning:
                    # The provider rejects the reasoning field.  Drop it once and
                    # remember, rather than paying for the rejection every turn.
                    self._reasoning_supported = False
                    self.schema_note = ("this provider does not accept a reasoning "
                                        "setting; thinking models may answer briefly")
                    continue
                if exc.code == 400 and uses_schema(effective) \
                        and self._schema_supported is None:
                    # The provider does not do structured outputs.  Fall back to
                    # the loose JSON mode once, and remember it for the rest of
                    # the game so the same rejected request is not repeated every
                    # single turn.
                    self._schema_supported = False
                    self.schema_note = ("this provider rejected a JSON schema; "
                                        "using plain JSON mode")
                    continue
                raise last
            except urllib.error.URLError as exc:
                last, retry = _classify_network_error(
                    exc, self.config.base_url, self.config.api_key, self.tls_note)
                if not retry:
                    self._bump("failures")
                    raise last
                self._pause(0.5 * (2 ** attempt), deadline)
                continue
            except (TimeoutError, OSError) as exc:
                last, retry = _classify_network_error(
                    exc, self.config.base_url, self.config.api_key, self.tls_note)
                if not retry:
                    # A timeout or TLS error repeats: do not wait for it again.
                    self._bump("failures")
                    raise last
                self._pause(0.5 * (2 ** attempt), deadline)
                continue
            except http.client.HTTPException as exc:
                # A connection cut mid-body (IncompleteRead) or a garbled status
                # line: not an OSError, but the same kind of transient failure.
                last = LLMError("the connection broke mid-answer: %s"
                                % _redact(type(exc).__name__, self.config.api_key))
                self._pause(0.5 * (2 ** attempt), deadline)
                continue
            except ValueError as exc:
                raise LLMError("the response was not JSON: %s"
                               % _redact(exc, self.config.api_key))
            except LLMError:
                raise
            except Exception as exc:
                # Whatever a strange payload does to the parsing above, the
                # caller is promised an LLMError and nothing else.
                raise LLMError("could not read the response (%s)"
                               % type(exc).__name__)
        self._bump("failures")
        raise last or LLMError("request failed")

    def _check_settings(self):
        """Trim the settings and name an unusable one plainly."""
        config = self.config
        config.api_key = _clean(config.api_key)
        config.base_url = _clean(config.base_url).rstrip("/")
        scheme = urllib.parse.urlsplit(config.base_url).scheme.lower()
        if scheme not in ("http", "https"):
            raise LLMError(
                "the base URL %r must start with https:// (or http://)"
                % config.base_url)
        key = config.api_key
        if any(ord(c) > 255 or ord(c) < 33 for c in key):
            raise LLMError(
                "the API key contains a character that is not allowed in a key "
                "(a space, a line break or a non-Latin letter - check for a "
                "copy/paste error)")

    @staticmethod
    def _pause(seconds, deadline):
        """Sleep before a retry, but never past the overall deadline."""
        time.sleep(max(0.0, min(seconds, deadline - time.monotonic() - 0.5)))

    def _cache_key(self, messages, response_format, model=None):
        try:
            blob = json.dumps([model or self.config.model, messages, bool(response_format)],
                              sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        import hashlib
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _account(self, payload):
        """Record what the provider says the call cost in tokens."""
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self._bump(field, int(value))

    def spend_report(self):
        """A one-line summary for the settings window and the reasoning log."""
        report = "%d call%s, %d tokens" % (
            self.usage["requests"], "" if self.usage["requests"] == 1 else "s",
            self.usage["total_tokens"])
        if self.usage["cache_hits"]:
            report += ", %d cached" % self.usage["cache_hits"]
        limit = self.config.max_requests
        if limit:
            report += " (limit %d)" % limit
        return report

    def chat_chain(self, messages, response_format=None, timeout=None,
                   use_cache=False, deadline=None):
        """Try each configured model in turn; return the first answer.

        Raises the *last* error, so the caller sees why the final attempt failed
        rather than why the first one did.
        """
        last = None
        if deadline is None:
            # One allowance for the whole chain: a second model is a second
            # chance, not a second helping of the wait.
            deadline = Deadline((timeout or self.config.timeout) * 1.5)
        # The model is passed per call instead of being written into the shared
        # config: this runs on a worker thread while the settings window may be
        # changing that very config on the GUI thread.  The cache key includes
        # the model, so answers from different models cannot mix.
        for model in self.config.model_chain():
            if deadline.expired():
                # Out of time, or the caller already gave up and went on without
                # us: do not start another attempt nobody is waiting for.
                raise last or LLMTimeout("no time left for another model")
            try:
                return self.chat(messages, response_format=response_format,
                                 timeout=timeout, use_cache=use_cache, model=model,
                                 deadline=deadline)
            except LLMNotConfigured:
                raise
            except LLMError as exc:
                last = exc
                if "budget" in str(exc):
                    raise
                continue
        raise last or LLMError("no model in the chain answered")

    @staticmethod
    def _extract(payload, secret=None):
        try:
            choices = payload["choices"]
            message = choices[0]["message"]
            if not isinstance(message, dict):
                raise TypeError("message is not an object")
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape: %s"
                           % _redact(json.dumps(payload, default=str)[:300], secret))
        content = message.get("content")
        if isinstance(content, list):
            # Some providers return content as a list of parts.
            content = "".join(part.get("text", "") for part in content
                              if isinstance(part, dict)
                              and isinstance(part.get("text", ""), str))
        if not isinstance(content, str) or not content.strip():
            # A hybrid reasoning model that ran out of budget before it started
            # writing lands here, and "empty answer" sends the reader looking in
            # the wrong place.  Say which it was.
            reasoning = message.get("reasoning")
            if isinstance(reasoning, str) and reasoning.strip():
                raise LLMError(
                    "the model spent its whole answer budget thinking (%d tokens "
                    "of reasoning, no answer); raise Max answer tokens or turn "
                    "off its reasoning pass" % (len(reasoning) // 4))
            raise LLMError("the model returned an empty answer")
        return content

    def chat_json(self, messages, timeout=None):
        """Ask for JSON and return the parsed object.

        Models wrap JSON in prose or fences often enough that being strict here
        would fail a third of the time, so the first ``{...}`` block is
        extracted before parsing.
        """
        text = self.chat(messages, response_format={"type": "json_object"},
                         timeout=timeout)
        return extract_json(text)


def extract_json(text):
    """Pull the first JSON object out of a model answer."""
    text = text.strip()
    if text.startswith("```"):
        # Strip a fenced block.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:index + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    raise LLMError("no JSON object found in the answer")
