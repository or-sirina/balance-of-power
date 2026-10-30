"""
The Decisions API: Jev, and anything else shaped like it.

``typesafe/jev-1.13`` is **not a chat model** and cannot be called at
``/chat/completions`` — it answers 400 and tells you so.  It is a *decision*
model: you send it a ``state`` and one or more typed ``questions``, and it
returns typed answers with probabilities instead of prose.

Three question primitives:

``choice``
    Which one of these options?  Returns the chosen key, a probability per
    option, and a confidence.
``noul``
    Does this condition hold?  Returns the probability of yes.
``score``
    Where does this fall on an ordered scale?  Returns a probability-weighted
    position, a probability per level, and a confidence.

For a game like this that is a better fit than a chat model: the opponent's turn
is a sequence of judgements — *which country matters, what should be done there,
how much* — and each one is a choice or a score.  It is also far cheaper, since
output tokens are free and only the ``state`` is billed.

The cost of the trade is that Jev returns no reasoning.  The opponent log
therefore shows probabilities and confidence rather than an explanation, which is
arguably more useful: you can see that it chose "arm the insurgents" on 51 % and
hesitated.
"""

import http.client
import json
import random
import threading
import time
import urllib.error
import urllib.request

from GameLogic.LLMClient import (Deadline, LLMError, LLMTimeout, _NoRedirect, _redact,
                                 _read_limited, parse_retry_after,
                                 _block_error, _classify_http_error,
                                 _classify_network_error, _host_of, _looks_html,
                                 _make_ssl_context)

#: Path appended to the provider host.
DECISION_PATH = "/api/alpha/decisions"
#: Answer orders accepted by the API.
PRIMITIVES = ("choice", "noul", "score")
MAX_ATTEMPTS = 3


class JevError(LLMError):
    """The decision request failed."""


class JevTimeout(LLMTimeout):
    """The decisions endpoint did not answer in time."""


def decision_url(base_url):
    """Derive the decisions endpoint from the configured chat base URL.

    OpenRouter serves chat at ``/api/v1`` and decisions at ``/api/alpha``, so the
    path is rebuilt from the host rather than configured twice.  An explicit
    ``BOP_LLM_DECISION_URL`` wins, which is what a self-hosted deployment needs.
    """
    import os
    override = os.environ.get("BOP_LLM_DECISION_URL")
    if override:
        return override.rstrip("/")
    base = (base_url or "").rstrip("/")
    if base.endswith("/api/v1"):
        return base[:-len("/api/v1")] + DECISION_PATH
    if base.endswith("/api/alpha"):
        return base + "/decisions"
    return base + DECISION_PATH


def _as_float(value, default=0.0):
    """A finite float, or ``default`` for anything else (text, null, NaN)."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _as_dict(value):
    return dict(value) if isinstance(value, dict) else {}


class JevAnswer(object):
    """One typed answer.

    Confidence is a nicety for the log, not something the game depends on, so a
    value that is not a number is read as 0 instead of throwing away the whole
    answer; the same goes for odd probability and legend containers.
    """

    def __init__(self, question_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        self.id = question_id
        self.type = payload.get("type", "unknown")
        self.raw = payload
        self.probabilities = dict((k, _as_float(v)) for k, v in
                                  _as_dict(payload.get("probabilities")).items())
        self.confidence = _as_float(payload.get("confidence"))
        self.legend = _as_dict(payload.get("legend"))

    @property
    def choice(self):
        return self.raw.get("choice")

    @property
    def noul(self):
        """Probability that the condition holds, 0-1."""
        value = self.raw.get("noul")
        return float(value) if isinstance(value, (int, float)) else 0.0

    @property
    def score(self):
        value = self.raw.get("score")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def best(self):
        """The single most likely option, for a choice question."""
        if self.choice is not None:
            return self.choice
        if self.probabilities:
            return max(self.probabilities.items(), key=lambda kv: kv[1])[0]
        return None

    def sample(self, rng=random, floor=0.0):
        """Draw an option according to the model's own probabilities.

        Taking the argmax every time makes the opponent deterministic and
        predictable; sampling keeps its 51/49 calls genuinely uncertain, which is
        what the probabilities are for.  Low-confidence answers wobble, confident
        ones do not.

        ``floor`` is a *relative* threshold: options holding less than this
        fraction of the leader's probability are dropped before the draw.  It
        removes the tail that turns a 79/13/4 answer into a 1-in-25 lurch towards
        a country the model barely considered, while leaving a real 55/45 split
        intact.  The default of 0.0 keeps the raw distribution.
        """
        if self.type == "noul":
            return rng.random() < self.noul
        if self.type == "choice":
            keys = list(self.probabilities)
            if not keys:
                return self.choice
            weights = [max(0.0, self.probabilities[k]) for k in keys]
            if floor > 0.0:
                top = max(weights)
                keep = [i for i, w in enumerate(weights) if w >= floor * top]
                if keep:
                    keys = [keys[i] for i in keep]
                    weights = [weights[i] for i in keep]
            total = sum(weights)
            if total <= 0:
                return self.choice
            roll = rng.random() * total
            upto = 0.0
            for key, weight in zip(keys, weights):
                upto += weight
                if roll <= upto:
                    return key
            return keys[-1]
        return self.score

    def describe(self, taken=None, labels=None):
        """A short human-readable summary, for the opponent log.

        ``taken`` is the option the game actually used.  Because a choice answer
        is sampled from the model's distribution rather than read off the
        argmax, the two differ regularly, and a log that reported the favourite
        would attribute to the opponent a move it never made.  ``labels`` maps
        the machine keys (country ids, verb names) to what the player sees.
        """
        labels = labels or {}

        def show(key):
            return labels.get(str(key), key)

        if self.type == "choice":
            ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])[:3]
            spread = ", ".join("%s %.0f%%" % (show(k), v * 100) for k, v in ranked)
            lead = self.choice if self.choice is not None else self.best()
            lead_share = self.probabilities.get(str(lead), self.confidence)
            if taken is not None and str(taken) != str(lead):
                share = self.probabilities.get(str(taken),
                                               self.probabilities.get(taken, 0.0))
                return ("drew %s, a %.0f%% option (favourite was %s at %.0f%%) "
                        "\u2014 %s" % (show(taken), share * 100, show(lead),
                                       lead_share * 100, spread))
            return "chose %s (%.0f%% confidence) \u2014 %s" % (
                show(lead), self.confidence * 100, spread)
        if self.type == "noul":
            return "yes with probability %.0f%%" % (self.noul * 100)
        if self.type == "score":
            return "scored %.2f (%.0f%% confidence)" % (self.score, self.confidence * 100)
        return self.type

    def as_dict(self):
        return {"id": self.id, "type": self.type, "choice": self.choice,
                "noul": self.noul, "score": self.score,
                "confidence": self.confidence,
                "probabilities": self.probabilities}


class JevClient(object):
    """Calls the Decisions API."""

    def __init__(self, config, requester=None):
        self.config = config
        #: Injected in tests to avoid a socket.
        self.requester = requester
        #: Guards the counters, which the worker thread updates while the GUI
        #: thread reads them for the status line.
        self._lock = threading.Lock()
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0,
                      "cost": 0.0, "failures": 0}
        self.last_answers = {}
        self.tls_note = ""

    # -- transport ----------------------------------------------------------

    def _post(self, payload, timeout, deadline=None):
        if deadline is not None:
            # Never wait longer than the turn has left (and never a negative or
            # zero timeout, which urllib reads as "no timeout" or an error).
            timeout = max(0.25, min(timeout, deadline.remaining()))
        request = urllib.request.Request(
            decision_url(self.config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % self.config.api_key,
                "HTTP-Referer": "https://localhost/balance-of-power",
                "X-Title": "Balance of Power",
                "User-Agent": "BalanceOfPower/1.0",
            },
            method="POST")
        context, self.tls_note = _make_ssl_context()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=context))
        with opener.open(request, timeout=timeout) as response:
            raw = _read_limited(response, deadline=deadline)
            ctype = response.headers.get("Content-Type", "")
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            if _looks_html(raw, ctype):
                raise _block_error(_host_of(self.config.base_url), "200")
            raise

    # -- public -------------------------------------------------------------

    def decide(self, state, questions, timeout=None, deadline=None):
        """Ask one or more typed questions about ``state``.

        Returns ``{question_id: JevAnswer}``.  Raises :class:`JevError` on any
        failure, including a question the API rejects.  ``deadline`` is shared
        with the caller's other calls in the same turn (see
        :class:`GameLogic.LLMClient.Deadline`).
        """
        if getattr(self.config, "offline", False):
            raise JevError("offline mode is on; no model calls are made")
        if not self.config.api_key:
            raise JevError("no API key configured")
        timeout = timeout or self.config.timeout
        limit = self._budget_left()
        if limit is not None and limit <= 0:
            raise JevError("the per-game model budget of %d calls is used up"
                           % self.config.max_requests)

        payload = {"model": self.config.model, "state": state, "questions": questions}
        last = None
        secret = self.config.api_key
        host = _host_of(decision_url(self.config.base_url))
        if deadline is not None and deadline.expired():
            raise JevTimeout("no time left for this request")
        own = Deadline(timeout * 1.5, parent=deadline)
        deadline = own.expires          # the monotonic instant used below
        for attempt in range(MAX_ATTEMPTS):
            if attempt and (time.monotonic() >= deadline or own.cancelled):
                break
            try:
                data = self._post(payload, timeout, deadline=own)
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read(4096).decode("utf-8", "replace")
                except Exception:
                    body = ""
                network = _classify_http_error(
                    exc.code, body, exc.headers.get("Content-Type", "")
                    if exc.headers else "", host)
                if network is not None:
                    raise JevError(str(network))
                if 300 <= exc.code < 400:
                    # Not followed on purpose (see _NoRedirect).
                    target = exc.headers.get("Location", "") if exc.headers else ""
                    where = _host_of(target) if target else "another address"
                    raise JevError("the request to %s was redirected to %s (HTTP %s) - "
                                   "probably a web filter or captive portal; ask IT "
                                   "to allow %s" % (host, where, exc.code, host))
                if exc.code in (401, 403):
                    raise JevError("the API key was rejected (HTTP %d)" % exc.code)
                if exc.code == 404:
                    raise JevError("model %r is not available at the decisions "
                                   "endpoint" % self.config.model)
                if exc.code == 400:
                    raise JevError("the request was rejected: %s" % _redact(body[:300], secret))
                if exc.code == 429 or 500 <= exc.code < 600:
                    last = JevError("HTTP %d from the decisions endpoint" % exc.code)
                    asked = parse_retry_after(exc.headers.get("Retry-After")
                                              if exc.headers else None)
                    if asked is not None and asked > deadline - time.monotonic() - 0.5:
                        self._bump("failures")
                        raise JevError("HTTP %d: the service asked us to wait %.0f s, "
                                       "longer than the time allowed"
                                       % (exc.code, asked))
                    self._pause(asked if asked is not None else 0.7 * (2 ** attempt),
                                deadline)
                    continue
                raise JevError("HTTP %d: %s" % (exc.code, _redact(body[:200], secret)))
            except urllib.error.URLError as exc:
                last, retry = _classify_network_error(
                    exc, decision_url(self.config.base_url), secret, self.tls_note)
                if isinstance(last, LLMTimeout):
                    last = JevTimeout(str(last))
                elif not isinstance(last, JevError):
                    last = JevError(str(last))
                if not retry:
                    self._bump("failures")
                    raise last
                self._pause(0.5 * (2 ** attempt), deadline)
                continue
            except (TimeoutError, OSError) as exc:
                last, retry = _classify_network_error(
                    exc, decision_url(self.config.base_url), secret, self.tls_note)
                if not retry:
                    self._bump("failures")
                    raise (JevTimeout(str(last)) if isinstance(last, LLMTimeout)
                           else JevError(str(last)))
                last = JevError(str(last))
                self._pause(0.5 * (2 ** attempt), deadline)
                continue
            except http.client.HTTPException as exc:
                last = JevError("the connection broke mid-answer: %s"
                                % type(exc).__name__)
                self._pause(0.5 * (2 ** attempt), deadline)
                continue
            except ValueError as exc:
                raise JevError("the answer was not JSON: %s" % _redact(exc, secret))
            except JevError:
                raise
            except LLMError as exc:
                raise JevError(str(exc))

            # Whatever shape the endpoint answered in, the caller is promised a
            # JevError and nothing else; a list, a string or a half-formed
            # answer must send the opponent to the built-in AI, not crash it.
            try:
                if not isinstance(data, dict):
                    raise TypeError("the answer is not an object")
                raw_answers = data.get("answers") or {}
                usage = data.get("usage")
                answers = {}
                for key, value in raw_answers.items():
                    if isinstance(value, dict):
                        answers[key] = JevAnswer(key, value)
                if not answers:
                    raise JevError("the endpoint returned no answers")
                self._bump("requests")
                self._account(usage if isinstance(usage, dict) else {})
            except JevError:
                raise
            except Exception as exc:
                raise JevError("the answer was malformed (%s)" % type(exc).__name__)
            self.last_answers = answers
            return answers
        self._bump("failures")
        raise last or JevError("the decision request failed")

    @staticmethod
    def _pause(seconds, deadline):
        time.sleep(max(0.0, min(seconds, deadline - time.monotonic() - 0.5)))

    def _bump(self, field, amount=1):
        with self._lock:
            self.usage[field] += amount
        if field == "requests":
            shared = (self.config.active_budget()
                      if hasattr(self.config, "active_budget") else None)
            if shared is not None:
                shared.add(amount)

    def budget_left(self):
        """How many decision calls remain this game, or None when unlimited."""
        return self._budget_left()

    def _budget_left(self):
        if not self.config.max_requests:
            return None
        shared = (self.config.active_budget()
                  if hasattr(self.config, "active_budget") else None)
        used = max(shared.used if shared is not None else 0, self.usage["requests"])
        return max(0, self.config.max_requests - used)

    def _account(self, usage):
        for field, key in (("input_tokens", "input_tokens"),
                           ("output_tokens", "output_tokens")):
            value = usage.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self._bump(key, int(value))
        cost = usage.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            self._bump("cost", float(cost))

    # -- convenience --------------------------------------------------------

    def choose(self, state, question_id, instructions, options, timeout=None):
        """A single ``choice`` question.  ``options`` maps key to description."""
        answers = self.decide(state, {question_id: {
            "type": "choice", "instructions": instructions,
            "criteria": dict(options)}}, timeout=timeout)
        return answers[question_id]

    def noul(self, state, question_id, instructions, timeout=None):
        answers = self.decide(state, {question_id: {
            "type": "noul", "instructions": instructions}}, timeout=timeout)
        return answers[question_id]

    def score(self, state, question_id, instructions, criteria, timeout=None):
        answers = self.decide(state, {question_id: {
            "type": "score", "instructions": instructions,
            "criteria": list(criteria)}}, timeout=timeout)
        return answers[question_id]

    def spend_report(self):
        report = "%d decision%s, %d input tokens, $%.4f" % (
            self.usage["requests"], "" if self.usage["requests"] == 1 else "s",
            self.usage["input_tokens"], self.usage["cost"])
        limit = self.config.max_requests
        if limit:
            left = self._budget_left()
            report += " (%d of %d left)" % (left, limit)
        return report

