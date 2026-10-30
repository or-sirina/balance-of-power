"""
What the advisors remember, and how well their advice has held up.

Two features share this module because they share one file and one moment: the
end of a turn.

**Long memory (E5).**  An advisor with no memory of the game so far is a
goldfish: the player backs down over Poland in 1984 and is asked in 1986 why
Poland matters.  So the notable things that happen -- a crisis won or lost, a
country that swung, a historical event, the score at the end of a year -- are
written down as one short sentence each, and the sentences relevant to the
current question are mixed back into the prompt.  The store is deliberately
small and bounded (a few dozen lines, a few hundred characters in the prompt):
a memory that grows without limit eventually costs more than the answer is
worth.

**Calibration (E3).**  Every recommendation ends with a machine-readable line
giving the country the advisor expects to move, the direction, and a confidence
from 0 to 100.  When the next turn has been played the prediction is scored
against the world state: did that country's alignment actually move the way the
advisor said?  The scoreboard -- hits, hit rate, mean confidence and a Brier
score -- is what gives the player a reason to prefer one voice to another.
Overconfidence is visible as a mean confidence well above the hit rate.

Both live in the per-user directory, so a reputation survives a restart.  The
advisors' memory is per game (keyed by an id stashed on the world object) while
the track record is cumulative across games: a Secretary of State who has been
wrong four times is still the man who was wrong four times.

Nothing here is allowed to raise into a game: a corrupt file, a missing country
or an odd world object degrades to "no memory" rather than an exception in the
middle of a turn.
"""

import json
import os
import time

import Local
import Paths
from GameLogic.Advisors import roster

#: Where the record and the memories are kept, inside the per-user directory.
MEMORY_FILENAME = "advisors_memory.json"

#: A prediction moves the alignment of a country by at least this much to count
#: as having moved at all.  Below it the honest answer is "it did not move".
MOVE_EPSILON = 3
#: Alignment swing worth writing down in the memory.
ALIGN_STEP = 25
#: Score swing worth writing down in the memory.
SCORE_STEP = 25

#: Bounds.  The prompt is the reason these exist.
MAX_EVENTS = 24          # sentences remembered per game
MAX_PROMPT_EVENTS = 6    # sentences offered to the model per question
MAX_PROMPT_CHARS = 700
MAX_PENDING = 24         # unresolved predictions per game
MAX_RECENT = 8           # scored predictions kept per advisor
MAX_GAMES = 6            # games whose memory is kept in the file
#: Below this many scored predictions the scoreboard says "too early to say".
MIN_SAMPLE = 3

#: Direction words as the model (and the offline path) writes them.
UP, HOLD, DOWN = 1, 0, -1


def alignment(world, side, country_id):
    """How aligned a country is with the given superpower, -127..127.

    This is the number the whole game already uses for "whose side is this
    country on" (``diplOpinion``), and it is what a prediction about the
    direction of a country's alignment is scored against.
    """
    return int(world.country[int(side)].diplOpinion[int(country_id)])


def game_key(world):
    """A stable id for this game, created on first use.

    The world object is the only thing that is guaranteed to live as long as the
    game does, and its save format belongs to other modules, so the id is just
    stashed on it.  A game reloaded from a save gets a fresh id and therefore a
    fresh memory: that is a limitation, not a promise we can keep from here.
    """
    key = getattr(world, "advisorGameId", None)
    if isinstance(key, str) and key:
        return key
    key = "g%d" % time.time_ns()
    try:
        world.advisorGameId = key
    except (AttributeError, TypeError):
        pass
    return key


def _lower_first(text):
    """A title fit to follow "in 1985, ": keep acronyms alone."""
    text = str(text).strip()
    if not text:
        return text
    head = text.split(" ", 1)[0]
    # Only an article is lowered: most titles start with a proper noun
    # ("Chernobyl", "Solidarity"), which must keep its capital.
    if head in ("The", "A", "An"):
        return text[0].lower() + text[1:]
    return text


def _event_titles():
    """``{event key: title}`` from the historical deck, imported lazily."""
    try:
        from GameLogic.HistoricalEvents import EVENTS
    except Exception:                     # pragma: no cover - defensive
        return {}
    return dict((event.key, event.title) for event in EVENTS)


class AdvisorMemory(object):
    """The per-game memory, the open predictions and the track record."""

    def __init__(self, path=None, game=None):
        self.path = path or Paths.user_file(MEMORY_FILENAME)
        self.game = game
        self.events = []
        self.pending = []
        self.snapshot = None
        self.records = {}
        self.sequence = 0
        self.last_error = ""
        self._titles = None
        self.load()

    # -- storage ------------------------------------------------------------

    def _read_file(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            self.last_error = "could not read %s: %s" % (os.path.basename(self.path), exc)
            return {}
        return data if isinstance(data, dict) else {}

    def load(self):
        """Read the record and this game's memory; a bad file means empty."""
        data = self._read_file()
        records = data.get("records")
        self.records = records if isinstance(records, dict) else {}
        games = data.get("games")
        games = games if isinstance(games, dict) else {}
        if self.game is None:
            return
        block = games.get(self.game)
        if not isinstance(block, dict):
            return
        self.sequence = self._as_int(block.get("sequence"), 0)
        for name in ("events", "pending"):
            value = block.get(name)
            if isinstance(value, list):
                setattr(self, name, [item for item in value if isinstance(item, dict)])
        snapshot = block.get("snapshot")
        if isinstance(snapshot, dict):
            self.snapshot = snapshot

    def save(self):
        """Write everything back.  A failure is recorded, never raised."""
        data = self._read_file()
        records = data.get("records")
        data["records"] = records if isinstance(records, dict) else {}
        for key, record in self.records.items():
            if isinstance(record, dict):
                data["records"][key] = record
        games = data.get("games")
        games = games if isinstance(games, dict) else {}
        if self.game is not None:
            games[self.game] = {
                "updated": time.time(),
                "sequence": self.sequence,
                "events": self.events,
                "pending": self.pending,
                "snapshot": self.snapshot,
            }
        data["games"] = self._trim_games(games)
        data["version"] = 1
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=1, ensure_ascii=False)
            os.replace(temp, self.path)
        except (OSError, ValueError, TypeError) as exc:
            self.last_error = "could not write %s: %s" % (os.path.basename(self.path), exc)
            return False
        return True

    @staticmethod
    def _trim_games(games):
        """Keep the most recently touched games only."""
        if len(games) <= MAX_GAMES:
            return games
        ordered = sorted(games.items(),
                         key=lambda item: (item[1] or {}).get("updated", 0)
                         if isinstance(item[1], dict) else 0,
                         reverse=True)
        return dict(ordered[:MAX_GAMES])

    @staticmethod
    def _as_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # -- memory -------------------------------------------------------------

    def _append(self, side, kind, text, year):
        """One bounded sentence of memory."""
        text = " ".join(str(text).split())[:160]
        if not text:
            return None
        self.sequence += 1
        event = {"year": self._as_int(year), "side": self._as_int(side),
                 "kind": str(kind), "text": text, "seq": self.sequence}
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[:len(self.events) - MAX_EVENTS]
        return event

    def remember(self, world, side, kind, text, year=None):
        """Record one notable event and persist it."""
        self.follow(world)
        if year is None:
            year = getattr(world, "year", 0)
        event = self._append(side, kind, text, year)
        if event is not None:
            self.save()
        return event

    def events_for(self, side):
        """This side's memories, oldest first."""
        side = self._as_int(side)
        return [e for e in self.events if e.get("side") == side]

    def prompt_block(self, world, question, side, limit=MAX_PROMPT_EVENTS):
        """The remembered lines worth putting in front of this advisor.

        Events that name a country the question names come first, then the most
        recent ones; the whole block is capped in both count and characters so
        that a long game cannot turn the prompt into a transcript.
        """
        events = self.events_for(side)
        if not events:
            return ""
        lowered = str(question or "").lower()
        names = [name for name in self._country_names(world)
                 if len(name) > 3 and name.lower() in lowered]
        wanted = []
        for event in events:
            text = str(event.get("text", "")).lower()
            priority = 0 if any(name.lower() in text for name in names) else 1
            wanted.append((priority, -self._as_int(event.get("seq")), event))
        wanted.sort(key=lambda item: (item[0], item[1]))
        chosen = [item[2] for item in wanted[:max(1, int(limit))]]
        chosen.sort(key=lambda event: (self._as_int(event.get("year")),
                                       self._as_int(event.get("seq"))))
        lines = ["WHAT YOU REMEMBER ABOUT THIS GAME"]
        for event in chosen:
            line = "- %s" % event.get("text", "")
            if sum(len(part) for part in lines) + len(line) > MAX_PROMPT_CHARS:
                break
            lines.append(line)
        return "\n".join(lines) if len(lines) > 1 else ""

    def _country_names(self, world):
        """Country names this world knows, from the localisation data."""
        names = []
        try:
            total = len(getattr(world, "country", ()) or ())
        except TypeError:
            return names
        for index in range(min(total, len(Local.strings) - Local.DATA_COUNTRIES)):
            try:
                name = Local.strings[Local.DATA_COUNTRIES + index][Local.CTRY_NAME]
            except (IndexError, TypeError, KeyError):
                break
            if isinstance(name, str) and name:
                names.append(name)
        return names

    # -- observation --------------------------------------------------------

    def _snapshot_of(self, world, side):
        """The few numbers and flags needed to notice what happened."""
        side = self._as_int(side)
        crisis = getattr(world, "crisis", None)
        head = getattr(crisis, "whichHead", None)
        victim = getattr(crisis, "victim", None)
        if victim is None and head is not None:
            victim = getattr(head, "target", None)
        align = {}
        me = world.country[side]
        for country in world.country[2:]:
            try:
                align[str(country.id)] = int(me.diplOpinion[country.id])
            except (AttributeError, IndexError, TypeError):
                continue
        crisis_country = ""
        if victim is not None:
            # ``Country.name`` is the leader's name; remember the country.
            crisis_country = self._country_name(getattr(victim, "id", None)) \
                or str(getattr(victim, "name", "") or "")
        scores = []
        for power in world.country[:2]:
            scores.append(int(getattr(power, "score", 0) - getattr(power, "initScore", 0)))
        return {
            "year": self._as_int(getattr(world, "year", 0)),
            "side": side,
            "scores": scores,
            "crisis": bool(head is not None or getattr(crisis, "hasBegun", False)),
            "crisis_backdown": bool(getattr(crisis, "backDown", False)),
            "crisis_country": crisis_country,
            "align": align,
            "fired": [str(key) for key in (getattr(world, "firedEvents", None) or ())],
        }

    def _differences(self, previous, current):
        """Notable changes between two snapshots: (kind, text) pairs."""
        found = []
        side = self._as_int(current.get("side"))
        previous_year = self._as_int(previous.get("year"))

        if previous.get("crisis") and not previous.get("crisis_backdown") \
                and current.get("crisis_backdown"):
            country = (previous.get("crisis_country")
                       or current.get("crisis_country") or "the crisis")
            found.append(("crisis", "in %d you backed down over %s"
                          % (previous_year, country)))
        elif previous.get("crisis") and not current.get("crisis"):
            if not previous.get("crisis_backdown"):
                country = previous.get("crisis_country") or "the crisis"
                found.append(("crisis", "in %d you stood firm over %s"
                              % (previous_year, country)))
        elif not previous.get("crisis") and current.get("crisis"):
            country = current.get("crisis_country") or "a client"
            found.append(("crisis", "in %d a crisis opened over %s"
                          % (self._as_int(current.get("year")), country)))

        if current.get("year", 0) > previous_year:
            known = set(previous.get("fired", ()))
            if self._titles is None:
                self._titles = _event_titles()
            for key in current.get("fired", ()):
                if key in known:
                    continue
                title = self._titles.get(key)
                if title:
                    found.append(("event", "in %d, %s"
                                  % (self._as_int(current.get("year")),
                                     _lower_first(title))))
            scores = current.get("scores") or [0, 0]
            old = previous.get("scores") or [0, 0]
            if len(scores) > side and len(old) > side:
                delta = self._as_int(scores[side]) - self._as_int(old[side])
                if abs(delta) >= SCORE_STEP:
                    found.append(("score", "in %d the year ended %d points %s"
                                  % (previous_year, abs(delta),
                                     "in your favour" if delta > 0 else "against you")))
            found.extend(self._movers(previous, current, side, previous_year))
        return found

    def _movers(self, previous, current, side, year):
        """Countries whose alignment moved most during the turn, at most two."""
        old = previous.get("align") or {}
        new = current.get("align") or {}
        moves = []
        for cid, value in new.items():
            if cid not in old:
                continue
            delta = self._as_int(value) - self._as_int(old[cid])
            if abs(delta) >= ALIGN_STEP:
                moves.append((abs(delta), delta, cid))
        moves.sort(reverse=True)
        found = []
        for _, delta, cid in moves[:2]:
            name = self._country_name(cid)
            if not name:
                continue
            found.append(("alignment", "in %d %s moved %d points %s you"
                          % (year, name, abs(delta),
                             "towards" if delta > 0 else "away from")))
        return found

    def _country_name(self, country_id):
        try:
            index = Local.DATA_COUNTRIES + int(country_id)
            return str(Local.strings[index][Local.CTRY_NAME])
        except (IndexError, TypeError, KeyError, ValueError):
            return ""

    def follow(self, world):
        """Point the store at the game this world belongs to.

        A new game started in this process, or a world reloaded from a save,
        must not inherit the last game's memories -- but the cumulative track
        record deliberately survives.  Called before anything is read or
        written, so that ``remember()``/``predict()`` used on their own (a hook
        in another module, a test) file their lines under the right game rather
        than under none and lose them.
        """
        key = game_key(world)
        if key == self.game:
            return False
        self.game = key
        self.events, self.pending = [], []
        self.snapshot = None
        self.sequence = 0
        self.load()
        return True

    def observe(self, world, side):
        """Notice what changed since the last look, and score what is due.

        Safe to call as often as the UI likes: with nothing changed it writes
        nothing.
        """
        try:
            current = self._snapshot_of(world, side)
        except (AttributeError, IndexError, TypeError, KeyError) as exc:
            self.last_error = "could not read the world: %s" % exc
            return []
        self.follow(world)
        previous = self.snapshot
        added = []
        if previous and previous.get("side") == current["side"]:
            for kind, text in self._differences(previous, current):
                event = self._append(current["side"], kind, text, previous.get("year"))
                if event is not None:
                    added.append(event["text"])
        self.snapshot = current
        resolved = self.resolve(world)
        if added or resolved or previous != current:
            self.save()
        return added

    # -- predictions and the scoreboard -------------------------------------

    def predict(self, world, side, key, country_id, direction, confidence,
                country_name="", question="", year=None):
        """Record a prediction, unless the same one is already open.

        Asking the same advisor the same thing twice in one turn must not turn
        into two bets on the same coin: an unresolved prediction about the same
        country by the same advisor is left alone.
        """
        self.follow(world)
        side = self._as_int(side)
        year = self._as_int(year if year is not None else getattr(world, "year", 0))
        for item in self.pending:
            if item.get("side") == side and item.get("key") == key \
                    and self._as_int(item.get("country_id")) == self._as_int(country_id):
                item["confidence"] = self._as_int(confidence, 50)
                item["direction"] = self._as_int(direction)
                item["question"] = str(question)[:200]
                self.save()
                return item
        prediction = {
            "side": side,
            "key": str(key),
            "year": year,
            "country_id": self._as_int(country_id),
            "country": str(country_name),
            "direction": self._as_int(direction),
            "confidence": max(0, min(100, self._as_int(confidence, 50))),
            "alignment": alignment(world, side, country_id),
            "question": str(question)[:200],
        }
        self.pending.append(prediction)
        if len(self.pending) > MAX_PENDING:
            del self.pending[:len(self.pending) - MAX_PENDING]
        self.save()
        return prediction

    @staticmethod
    def _hit(direction, delta):
        """Did the alignment move the way the advisor said it would?"""
        if int(direction) == HOLD:
            return abs(delta) < MOVE_EPSILON
        if int(direction) > 0:
            return delta >= MOVE_EPSILON
        return delta <= -MOVE_EPSILON

    def resolve(self, world):
        """Score every prediction whose turn has been played.  Returns lines."""
        self.follow(world)
        year = self._as_int(getattr(world, "year", 0))
        due, lines = [], []
        for prediction in self.pending:
            if self._as_int(prediction.get("year"), year) >= year:
                continue
            side = self._as_int(prediction.get("side"))
            country_id = prediction.get("country_id")
            try:
                now = alignment(world, side, country_id)
            except (AttributeError, IndexError, TypeError, KeyError):
                due.append(prediction)        # world cannot say; stop guessing
                continue
            delta = now - self._as_int(prediction.get("alignment"), now)
            hit = self._hit(prediction.get("direction", HOLD), delta)
            self._score(prediction, hit, now, delta)
            name = prediction.get("country") or self._country_name(country_id) or "a country"
            outcome = ("it did" if hit else "it did not")
            lines.append((side, "in %d you said %s would move %s; %s"
                          % (self._as_int(prediction.get("year")), name,
                             {UP: "your way", DOWN: "their way"}.get(
                                 self._as_int(prediction.get("direction")), "neither way"),
                             outcome)))
            due.append(prediction)
        if due:
            for prediction in due:
                if prediction in self.pending:
                    self.pending.remove(prediction)
            for side, text in lines:
                self._append(side, "prediction", text, year)
            self.save()
        return [text for _, text in lines]

    def _record_key(self, side, key):
        return "%d:%s" % (self._as_int(side), key)

    def record_for(self, side, key):
        """The cumulative record dict for one advisor."""
        record = self.records.get(self._record_key(side, key))
        if not isinstance(record, dict):
            record = {}
            self.records[self._record_key(side, key)] = record
        for field in ("resolved", "hits", "confidence_sum", "hit_confidence_sum",
                      "brier_sum"):
            record[field] = float(record.get(field, 0) or 0)
        recent = record.get("recent")
        record["recent"] = recent if isinstance(recent, list) else []
        return record

    def _score(self, prediction, hit, now, delta):
        side = self._as_int(prediction.get("side"))
        confidence = max(0, min(100, self._as_int(prediction.get("confidence"), 50)))
        record = self.record_for(side, prediction.get("key"))
        record["resolved"] += 1
        record["hits"] += 1 if hit else 0
        record["confidence_sum"] += confidence
        if hit:
            record["hit_confidence_sum"] += confidence
        probability = confidence / 100.0
        record["brier_sum"] += (probability - (1.0 if hit else 0.0)) ** 2
        record["recent"].append([self._as_int(prediction.get("year")),
                                 prediction.get("country", ""),
                                 self._as_int(prediction.get("direction")),
                                 confidence, 1 if hit else 0, now, delta])
        if len(record["recent"]) > MAX_RECENT:
            del record["recent"][:len(record["recent"]) - MAX_RECENT]
        return record

    def stats(self, side, key):
        """The numbers the scoreboard shows for one advisor."""
        record = self.record_for(side, key)
        resolved = int(record["resolved"])
        hits = int(record["hits"])
        stats = {
            "key": str(key),
            "resolved": resolved,
            "hits": hits,
            "open": sum(1 for p in self.pending
                        if self._as_int(p.get("side")) == self._as_int(side)
                        and p.get("key") == str(key)),
            "rate": (hits / float(resolved)) if resolved else 0.0,
            "mean_confidence": (record["confidence_sum"] / resolved / 100.0) if resolved else 0.0,
            "brier": (record["brier_sum"] / resolved) if resolved else None,
            "recent": list(record["recent"]),
        }
        stats["verdict"] = self._verdict(stats)
        return stats

    @staticmethod
    def _verdict(stats):
        """A one-phrase reading of the record, honest about small samples."""
        if stats["resolved"] < MIN_SAMPLE:
            return "too early to say"
        gap = stats["mean_confidence"] - stats["rate"]
        if stats["brier"] is not None and stats["brier"] <= 0.2:
            return "well calibrated"
        if gap > 0.15:
            return "overconfident"
        if gap < -0.15:
            return "underconfident"
        return "about right"

    def scoreboard(self, side):
        """One row per advisor on this bench, in roster order."""
        rows = []
        for advisor in roster(side):
            stats = self.stats(side, advisor.key)
            stats["name"] = advisor.name
            stats["role"] = advisor.role
            stats["bias"] = advisor.bias
            rows.append(stats)
        return rows

    def format_scoreboard(self, side):
        """The scoreboard as plain lines, for the log and for tests."""
        lines = []
        for row in self.scoreboard(side):
            if row["resolved"]:
                lines.append("%s: %d/%d (%.0f%%), says %.0f%% on average, %s%s"
                             % (row["name"], row["hits"], row["resolved"],
                                100.0 * row["rate"], 100.0 * row["mean_confidence"],
                                row["verdict"],
                                ", %d open" % row["open"] if row["open"] else ""))
            else:
                lines.append("%s: no scored predictions yet%s"
                             % (row["name"],
                                ", %d open" % row["open"] if row["open"] else ""))
        return lines


#: One store per process: the window rebuilds its sessions on every reload, and
#: a reputation that reset every time the window was reopened would be useless.
_STORE = None


def store(path=None):
    """The process-wide memory store."""
    global _STORE
    if _STORE is None or (path is not None and _STORE.path != path):
        if path is None:
            _STORE = AdvisorMemory()
        else:
            _STORE = AdvisorMemory(path=path)
    return _STORE


def forget():
    """Drop the cached store (used by tests and when the user dir changes)."""
    global _STORE
    _STORE = None
