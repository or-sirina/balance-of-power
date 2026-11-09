"""Bounded campaign transcripts and calibration, saved inside bridge metadata.

Spoken context stays separate by language; each advisor's track record is shared
across languages. No SessionMemory operation reads or writes the Qt memory file.
"""

import copy
import json
import math
import re
import uuid

import Local
from GameLogic.AdvisorMemory import (ALIGNMENT_BASIS, MAX_EVENTS, MAX_PENDING,
                                    MAX_RECENT, AdvisorMemory)
from GameLogic.Advisors import roster
from GameLogic.LLMClient import _redact

MAX_METADATA_BYTES = 24000
MAX_COUNT = 1000000
_VERDICTS_RU = {"too early to say": "данных пока мало", "well calibrated": "хорошая калибровка",
                "overconfident": "переоценивает уверенность", "underconfident": "недооценивает уверенность",
                "about right": "уверенность близка к результатам"}


class SessionMemory(AdvisorMemory):
    def _read_file(self):
        return {}

    def save(self):
        pass


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    value = _redact(value[:limit].encode("utf-8", "replace").decode("utf-8").replace("\x00", ""))
    return re.sub(r"(?i)\b(api[ _-]?key|api[ _-]?ключ|token|токен|secret|секрет)\s*[:=]\s*[^\s,;]+",
                  r"\1: ***", value)[:limit]


def _integer(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not low <= value <= high or not math.isfinite(value) or int(value) != value:
        return None
    return int(value)


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if low <= value <= high and math.isfinite(value) else None


def _history(rows):
    if not isinstance(rows, list):
        return []
    return [{"role": row["role"], "content": _text(row["content"], 6000)}
            for row in rows[-12:] if isinstance(row, dict)
            and row.get("role") in ("user", "assistant")
            and isinstance(row.get("content"), str)]


def _key(side, index):
    team = roster(side)
    return team[index].key if index < len(team) else ""


def _side(memory):
    if memory is None:
        return None
    snapshot = memory.snapshot or {}
    side = _integer(snapshot.get("side"), 0, 1)
    if side is not None:
        return side
    for prediction in memory.pending:
        side = _integer(prediction.get("side"), 0, 1)
        if side is not None:
            return side
    found = {int(key[0]) for key in memory.records if isinstance(key, str) and key.startswith(("0:", "1:"))}
    return next(iter(found)) if len(found) == 1 else None


def _record(value):
    if not isinstance(value, dict):
        return None
    resolved = _integer(value.get("resolved"), 0, MAX_COUNT)
    if resolved is None:
        return None
    hits = _integer(value.get("hits"), 0, resolved)
    confidence = _number(value.get("confidence_sum"), 0, resolved * 100)
    hit_confidence = _number(value.get("hit_confidence_sum"), 0, (hits or 0) * 100)
    brier = _number(value.get("brier_sum"), 0, resolved)
    if any(item is None for item in (hits, confidence, hit_confidence, brier)):
        return None
    if hit_confidence > confidence + 1e-9 or confidence - hit_confidence > (resolved - hits) * 100 + 1e-9:
        return None
    recent = []
    rows = value.get("recent", [])
    for row in rows[-MAX_RECENT:] if isinstance(rows, list) else []:
        if not isinstance(row, list) or len(row) != 7:
            continue
        year, direction, certainty, hit, after, delta = (
            _integer(row[0], 1900, 2200), _integer(row[2], -1, 1),
            _integer(row[3], 0, 100), _integer(row[4], 0, 1),
            _integer(row[5], -127, 127), _integer(row[6], -254, 254))
        if any(item is None for item in (year, direction, certainty, hit, after, delta)):
            continue
        recent.append([year, _text(row[1], 80), direction, certainty, hit, after, delta])
    recent = recent[-resolved:] if resolved else []
    return {"resolved": resolved, "hits": hits, "confidence_sum": confidence,
            "hit_confidence_sum": hit_confidence, "brier_sum": brier, "recent": recent}


def _snapshot(value):
    if not isinstance(value, dict) or value.get("alignment_basis") != ALIGNMENT_BASIS:
        return None
    year, side = _integer(value.get("year"), 1900, 2200), _integer(value.get("side"), 0, 1)
    if year is None or side is None:
        return None
    scores = value.get("scores")
    if not isinstance(scores, list) or len(scores) != 2:
        return None
    scores = [_integer(v, -1000000000, 1000000000) for v in scores]
    if any(v is None for v in scores):
        return None
    raw, align = value.get("align"), {}
    if isinstance(raw, dict):
        for country_id in range(80):
            number = _integer(raw.get(str(country_id)), -127, 127)
            if number is not None:
                align[str(country_id)] = number
    fired = value.get("fired", [])
    return {"year": year, "side": side, "scores": scores, "align": align,
            "crisis": value.get("crisis") is True, "crisis_backdown": value.get("crisis_backdown") is True,
            "crisis_country": _text(value.get("crisis_country"), 80), "alignment_basis": ALIGNMENT_BASIS,
            "fired": [_text(item, 64) for item in fired[-32:] if isinstance(item, str)] if isinstance(fired, list) else []}


def _memory_dump(memory, index):
    records = {}
    for side in (0, 1):
        key = "%d:%s" % (side, _key(side, index))
        cleaned = _record(memory.records.get(key))
        if cleaned is not None:
            records[key] = cleaned
    pending = []
    for prediction in memory.pending[-MAX_PENDING:]:
        if not isinstance(prediction, dict) or prediction.get("alignment_basis") != ALIGNMENT_BASIS:
            continue
        side = _integer(prediction.get("side"), 0, 1)
        row = [side, _integer(prediction.get("year"), 1900, 2200),
               _integer(prediction.get("country_id"), 0, 79), _integer(prediction.get("direction"), -1, 1),
               _integer(prediction.get("confidence"), 0, 100), _integer(prediction.get("alignment"), -127, 127)]
        if any(v is None for v in row) or prediction.get("key") != _key(side, index):
            continue
        pending.append(row)
    events = []
    for event in memory.events[-MAX_EVENTS:]:
        if not isinstance(event, dict):
            continue
        year, side, sequence = (_integer(event.get("year"), 1900, 2200),
                                _integer(event.get("side"), 0, 1), _integer(event.get("seq"), 0, 1000000000))
        if year is not None and side is not None and sequence is not None:
            events.append([year, side, _text(event.get("kind"), 24), _text(event.get("text"), 160), sequence])
    return {"schema": 1, "alignment_basis": ALIGNMENT_BASIS,
            "sequence": _integer(memory.sequence, 0, 1000000000) or 0,
            "records": records, "pending": pending, "events": events, "snapshot": _snapshot(memory.snapshot)}


def _memory_load(value, index, generation):
    memory = SessionMemory(path="unused", game=generation)
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1 or value.get("alignment_basis") != ALIGNMENT_BASIS:
        return memory
    raw_records = value.get("records", {})
    if isinstance(raw_records, dict):
        for side in (0, 1):
            key = "%d:%s" % (side, _key(side, index))
            record = _record(raw_records.get(key))
            if record is not None:
                memory.records[key] = record
    pending = value.get("pending", [])
    seen = set()
    for row in pending[-MAX_PENDING:] if isinstance(pending, list) else []:
        if not isinstance(row, list) or len(row) != 6:
            continue
        side, year, country_id, direction, confidence, alignment = (
            _integer(row[0], 0, 1), _integer(row[1], 1900, 2200), _integer(row[2], 0, 79),
            _integer(row[3], -1, 1), _integer(row[4], 0, 100), _integer(row[5], -127, 127))
        if any(v is None for v in (side, year, country_id, direction, confidence, alignment)) or (side, country_id) in seen:
            continue
        seen.add((side, country_id))
        memory.pending.append({"side": side, "key": _key(side, index), "year": year,
            "country_id": country_id, "country": Local.countryName(country_id), "direction": direction,
            "confidence": confidence, "alignment": alignment, "alignment_basis": ALIGNMENT_BASIS, "question": ""})
    events = value.get("events", [])
    for row in events[-MAX_EVENTS:] if isinstance(events, list) else []:
        if not isinstance(row, list) or len(row) != 5:
            continue
        year, side, sequence = _integer(row[0], 1900, 2200), _integer(row[1], 0, 1), _integer(row[4], 0, 1000000000)
        if year is not None and side is not None and sequence is not None:
            memory.events.append({"year": year, "side": side, "kind": _text(row[2], 24),
                                  "text": _text(row[3], 160), "seq": sequence})
    memory.sequence = max([_integer(value.get("sequence"), 0, 1000000000) or 0]
                          + [event["seq"] for event in memory.events])
    memory.snapshot = _snapshot(value.get("snapshot"))
    return memory


class ConversationBook:
    def __init__(self):
        self.generation = uuid.uuid4().hex
        self.records = {}
        self._memories = {}
        self._memory_versions = {}

    @staticmethod
    def _validate(index, language):
        if type(index) is not int or not 0 <= index <= 3 or language not in ("en", "ru"):
            raise ValueError("invalid advisor conversation")

    def prepare(self, index, language):
        self._validate(index, language)
        key = (index, language)
        record = self.records.get(key, {})
        memory = self._memories.get(index) or SessionMemory(path="unused", game=self.generation)
        return {"generation": self.generation, "key": key,
                "version": record.get("version", 0), "memory_version": self._memory_versions.get(index, 0),
                "history": copy.deepcopy(record.get("history", [])), "memory": copy.deepcopy(memory)}

    def commit(self, pending):
        if pending["generation"] != self.generation:
            return False
        index, language = pending["key"]
        self._validate(index, language)
        current = self.records.get((index, language), {})
        if current.get("version", 0) != pending["version"] or pending.get("memory_version", 0) != self._memory_versions.get(index, 0):
            return False
        memory = _memory_load(_memory_dump(pending["memory"], index), index, self.generation)
        self._memories[index] = memory
        self._memory_versions[index] = self._memory_versions.get(index, 0) + 1
        self.records[(index, language)] = {"version": pending["version"] + 1,
            "history": _history(pending["history"]), "memory": memory}
        for key, row in self.records.items():
            if key[0] == index:
                row["memory"] = memory
        return True

    def observe(self, world):
        """Resolve due forecasts after a committed turn, without touching world."""
        if not self._memories:
            return False
        from Net.State import clone_world
        copied = clone_world(world)
        copied.advisorGameId = self.generation
        changed = False
        for index, memory in list(self._memories.items()):
            updated = copy.deepcopy(memory)
            side = _side(memory)
            updated.observe(copied, side if side is not None else copied.human)
            if _memory_dump(updated, index) == _memory_dump(memory, index):
                continue
            self._memories[index] = updated
            self._memory_versions[index] = self._memory_versions.get(index, 0) + 1
            for key, row in self.records.items():
                if key[0] == index:
                    row["memory"] = updated
            changed = True
        return changed

    def dump(self):
        rows = [{"index": key[0], "language": key[1], "history": _history(record.get("history", []))}
                for key, record in sorted(self.records.items())]
        for index, memory in sorted(self._memories.items()):
            anchor = next((row for row in rows if row["index"] == index), None)
            if anchor is None:
                anchor = {"index": index, "language": "en", "history": []}
                rows.append(anchor)
            anchor["memory"] = _memory_dump(memory, index)
        # Preserve pending forecasts and aggregate calibration before older text.
        while len(json.dumps(rows, ensure_ascii=True, allow_nan=False).encode("utf-8")) > MAX_METADATA_BYTES:
            candidates = [row for row in rows if row["history"]]
            if candidates:
                largest = max(candidates, key=lambda row: len(json.dumps(row["history"], ensure_ascii=True)))
                del largest["history"][:2]
                continue
            memories = [row["memory"] for row in rows if "memory" in row]
            events = [memory["events"] for memory in memories if memory["events"]]
            if events:
                del max(events, key=lambda values: len(json.dumps(values, ensure_ascii=True)))[0]
                continue
            snapshots = [memory for memory in memories if memory["snapshot"] is not None]
            if snapshots:
                max(snapshots, key=lambda memory: len(json.dumps(memory["snapshot"], ensure_ascii=True)))["snapshot"] = None
                continue
            recent = [record["recent"] for memory in memories for record in memory["records"].values() if record["recent"]]
            if recent:
                del max(recent, key=len)[0]
                continue
            break
        return rows

    @classmethod
    def load(cls, rows):
        book = cls()
        if not isinstance(rows, list):
            return book
        for row in rows[:8]:
            if not isinstance(row, dict) or type(row.get("index")) is not int or not 0 <= row["index"] <= 3 or row.get("language") not in ("en", "ru"):
                continue
            index, language = row["index"], row["language"]
            book.records[(index, language)] = {"version": 0, "history": _history(row.get("history", []))}
            if "memory" in row and index not in book._memories:
                book._memories[index] = _memory_load(row["memory"], index, book.generation)
        # Reapply the byte bound to arbitrary locally edited save metadata.
        bounded = book.dump()
        book.records, book._memories = {}, {}
        for row in bounded:
            index, language = row["index"], row["language"]
            book.records[(index, language)] = {"version": 0, "history": row["history"]}
            if "memory" in row:
                book._memories[index] = _memory_load(row["memory"], index, book.generation)
        for key, record in book.records.items():
            if key[0] in book._memories:
                record["memory"] = book._memories[key[0]]
        return book

    def details(self, index, language):
        """A read-only spoken transcript and localized calibration view."""
        self._validate(index, language)
        from GameLogic.AdvisorChat import clean_reply
        from .localization import country_name
        history = []
        for row in _history(self.records.get((index, language), {}).get("history", [])):
            content = clean_reply(row["content"]) if row["role"] == "assistant" else row["content"]
            if content:
                history.append({"role": row["role"], "content": content})
        memory = copy.deepcopy(self._memories.get(index))
        side = _side(memory)
        stats = memory.stats(side, _key(side, index)) if memory is not None and side is not None else {
            "resolved": 0, "hits": 0, "open": 0, "rate": 0, "mean_confidence": 0, "brier": None,
            "recent": [], "verdict": "too early to say"}
        resolved, hits, opened = stats["resolved"], stats["hits"], stats["open"]
        statistics = {"resolved": resolved, "hits": hits, "open": opened,
                      "hit_rate": stats["rate"] if resolved else None,
                      "mean_confidence": stats["mean_confidence"] if resolved else None, "brier": stats["brier"]}
        if resolved:
            status = "%d of %d correct; confidence %.0f%%; %s. Pending: %d." % (hits, resolved, stats["mean_confidence"] * 100, stats["verdict"], opened)
            status_ru = "Верных прогнозов: %d из %d; уверенность %.0f%%; %s. Ожидают проверки: %d." % (hits, resolved, stats["mean_confidence"] * 100, _VERDICTS_RU[stats["verdict"]], opened)
        else:
            status = "No predictions have been scored. Pending: %d." % opened
            status_ru = "Прогнозы ещё не проверены. Ожидают проверки: %d." % opened
        pending = []
        for item in memory.pending if memory is not None else []:
            if item["side"] != side or item["key"] != _key(side, index):
                continue
            direction = item["direction"]
            name, name_ru = Local.countryName(item["country_id"]), country_name(item["country_id"])
            move = {1: "towards us", 0: "unchanged", -1: "away from us"}[direction]
            move_ru = {1: "сблизится с нами", 0: "сохранит положение", -1: "отдалится от нас"}[direction]
            pending.append({key: item[key] for key in ("country_id", "year", "direction", "confidence")})
            pending[-1].update(summary_en="%d: %s, %s, confidence %d%%; pending." % (item["year"], name, move, item["confidence"]),
                               summary_ru="%d: %s %s, уверенность %d%%; ожидает проверки." % (item["year"], name_ru, move_ru, item["confidence"]))
        recent = []
        for year, name, direction, confidence, hit, after, delta in stats["recent"]:
            country_id = next((cid for cid in range(80) if Local.countryName(cid) == name), None)
            name_ru = country_name(country_id) if country_id is not None else name
            recent.append({"year": year, "direction": direction, "confidence": confidence, "hit": bool(hit),
                           "alignment_after": after, "delta": delta,
                           "summary_en": "%d: %s, confidence %d%%; %s; alignment change %+d." % (year, name, confidence, "correct" if hit else "incorrect", delta),
                           "summary_ru": "%d: %s, уверенность %d%%; %s; изменение отношения %+d." % (year, name_ru, confidence, "верно" if hit else "неверно", delta)})
        return {"index": index, "language": language, "side": side, "history": history,
                "statistics": statistics, "status": status, "status_ru": status_ru,
                "pending": pending, "recent": recent}
