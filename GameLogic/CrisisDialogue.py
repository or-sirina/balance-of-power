"""Display-only diplomatic wording, independent of the crisis engine and UI.

Build the immutable request on the caller's thread. Only the text request and
the shared chat client cross to a worker; no model output is applied to a world.
"""

import json
import re
from dataclasses import dataclass

import Local
from GameLogic.AdvisorChat import country_facts, guarded_chat
from GameLogic.Advisors import roster
from GameLogic.LLMClient import LLMError, extract_json


SYSTEM = """Write the dialogue for an already resolved step of a Cold War crisis.
The supplied event and outcome are authoritative. You supply WORDING ONLY;
never choose an action, change a policy, undo a concession, invent a summit,
promise aid or announce a war that the facts do not report.
Write reaction as the diplomatic speaker's direct statement, in at most 40
words. The four advisors privately advise the player, each in one sentence of
at most 25 words, with distinct priorities and voices. For an ended crisis they
assess the outcome rather than asking the player to escalate it again.
Mention the actual country and
policy at issue, and use only the supplied facts and numbers.
Return ONLY a JSON object with exactly these fields:
{"reaction": "statement", "advisors": {"ADVISOR_KEY": "sentence", ...}}
Include every advisor key supplied in the facts. No HTML or other fields."""


@dataclass(frozen=True)
class DialogueRequest:
    facts: str
    advisor_keys: tuple
    language: str = "en"


@dataclass(frozen=True)
class DialogueReply:
    reaction: str
    advice: tuple
    used_model: bool = True
    status: str = "LLM diplomacy: ready."

    @property
    def advisors(self):
        """Compatibility spelling for the Qt advisor cards."""
        return self.advice


def snapshot(world, headline, speaker, outcome, headline_text=None, language="en"):
    """Copy primitive facts without calling gimpt or modifying crisis scratch data."""
    if language not in ("en", "ru"):
        raise ValueError("crisis dialogue language must be en or ru")
    side = int(world.human)
    crisis = world.crisis
    team = list(roster(side))[:4]

    def name(country):
        return Local.strings[Local.DATA_COUNTRIES + country.id][Local.CTRY_NAME]

    ended = bool(crisis.backDown or not crisis.hasBegun)
    table_name = ("destab", "econAid", "govtAid", "insgAid", "govtIntv",
                  "insgIntv", "pressure", "treaty", "trade")[headline.action]
    held = int(getattr(headline.actor, table_name)[headline.target.id])
    # Read what the engine actually enacted, including minor-country endings.
    # HangLoose may already have swapped the headline's old/new fields.
    policy_status = ("reverted" if held == min(headline.old, headline.new) else "stands") if ended else "contested"
    facts = {
        "year": int(world.year),
        "language": language,
        "player": name(world.country[side]),
        "diplomatic_speaker": name(world.country[int(speaker)]),
        "event": outcome,
        "crisis_ended": ended,
        "crisis_level": int(crisis.level),
        "ladder": "9 is initial questioning; 1 is nuclear war",
        "policy_status": policy_status,
        "nuclear_war": bool(world.NWFlag or world.ANWFlag),
        "headline": str(headline_text if headline_text is not None else headline.text),
        "policy_actor": name(headline.actor),
        "policy": str(Local.strings[Local.LABEL_POLICY][headline.action]),
        "reported_policy_levels": {"old": int(headline.old), "new": int(headline.new)},
        "held_policy_level": held,
        "relations": int(world.USA.diplOpinion[1]),
        "country": country_facts(world, side, headline.target),
        "advisors": [{"key": a.key, "name": a.name, "role": a.role,
                      "priority": a.blurb, "voice": a.prompt_block()} for a in team],
    }
    return DialogueRequest(json.dumps(facts, ensure_ascii=False),
                           tuple(a.key for a in team), language)


def _line(value, limit):
    if not isinstance(value, str) or not value.strip():
        raise LLMError("the crisis dialogue contains an empty or invalid line")
    return " ".join(value.split())[:limit]


def generate(request, client, execute=None):
    """One batched completion; malformed/failed replies raise for caller fallback."""
    instruction = ("Write EVERY reaction and advisor sentence in Russian. "
                   "Translate country and policy names into Russian."
                   if request.language == "ru" else
                   "Write EVERY reaction and advisor sentence in English.")
    messages = [{"role": "system", "content": SYSTEM + "\n\n" + instruction},
                {"role": "user", "content": request.facts}]
    raw = guarded_chat(client, execute, messages)
    parsed = extract_json(raw)
    if not isinstance(parsed, dict) or set(parsed) != {"reaction", "advisors"}:
        raise LLMError("the crisis dialogue has an invalid structure")
    lines = parsed["advisors"]
    if not isinstance(lines, dict) or set(lines) != set(request.advisor_keys):
        raise LLMError("the crisis dialogue must include all four advisors")
    reaction = _line(parsed["reaction"], 550)
    advice = tuple(_line(lines[key], 300) for key in request.advisor_keys)
    if request.language == "ru" and any(not re.search(r"[А-Яа-яЁё]", line)
                                         for line in (reaction,) + advice):
        raise LLMError("the crisis model did not answer in Russian")
    status = "Дипломатия LLM: ответ получен." if request.language == "ru" else "LLM diplomacy: ready."
    return DialogueReply(reaction, advice, status=status)
