"""
The historical event deck, 1982-1990.

Nine turns of pure manoeuvre make a predictable game: whoever is ahead in 1984
usually wins in 1990.  The real decade did not work that way.  Afghanistan, the
Polish crisis, Able Archer, KAL-007, Chernobyl, Reykjavik, the INF treaty, the
withdrawal from Afghanistan and the fall of the Wall each rearranged the board
whether the players wanted it or not.

Each event fires once, in its historical year, and applies a bounded shift:
diplomatic opinion, spheres of influence, tension, and the two superpowers'
personality variables.  Nothing here decides the game on its own — the numbers
are deliberately modest — but together they stop a single early lead from
running away with it.

Events are attributed to a superpower so that they flow through the ordinary
news machinery and get a flag and a filter like every other headline; the text
itself is supplied verbatim rather than generated from templates, because the
wording is the point.
"""

from GameLogic.Globals import changeDiplOpinion, changeDMess
from constants import GAME_END_YEAR, GAME_START_YEAR, WORLD_EVENT


class HistoricalEvent(object):
    """One dated event and what it does to the world."""

    def __init__(self, year, key, title, headline, actor, victim=None,
                 effects=None, importance=45):
        self.year = year
        self.key = key
        self.title = title
        self.headline = headline
        #: Country id the headline is attributed to: a superpower, or a minor
        #: country when the event was nobody's superpower action.
        self.actor = actor
        #: Country id of the country it concerns, if any (defaults to the actor).
        self.victim = victim
        self.effects = effects or {}
        self.importance = importance

    def applies(self, world):
        return world.year == self.year

    def apply(self, world):
        """Mutate the world.  Every term is clamped by the helpers used here."""
        fx = self.effects
        usa, ussr = world.USA, world.USSR
        before = [usa.prestige(world), ussr.prestige(world)]

        # Tension and the two personalities.
        if "nastiness" in fx:
            world.nastiness = max(0, min(127, world.nastiness + fx["nastiness"]))
        for who, term in (("usa", usa), ("ussr", ussr)):
            for field in ("pugnacity", "integrity", "adventurousness"):
                key = "%s_%s" % (who, field)
                if key in fx:
                    value = getattr(term, field) + fx[key]
                    setattr(term, field, max(1, min(127, value)))

        # Opinion of the whole world towards a superpower.
        if "world_opinion_usa" in fx:
            for country in world.country[2:]:
                changeDiplOpinion(country, usa, fx["world_opinion_usa"])
        if "world_opinion_ussr" in fx:
            for country in world.country[2:]:
                changeDiplOpinion(country, ussr, fx["world_opinion_ussr"])

        # Opinion between the two superpowers.
        if "detente" in fx:
            changeDiplOpinion(usa, ussr, fx["detente"])

        # The two superpowers' opinion of one specific country.
        if "victim_opinion" in fx and self.victim is not None:
            target = world.country[self.victim]
            for power in (usa, ussr):
                changeDiplOpinion(power, target, fx["victim_opinion"])

        # Spheres of influence, e.g. the Eastern bloc drifting away.
        if "sphere" in fx:
            for country in world.country[2:]:
                if self.victim is not None and country.id != self.victim:
                    continue
                changeDMess(world, country, fx["sphere"])

        # History moves opinion, but it must not move the score.  The events are
        # the same every game and fall harder on the Soviet side: counted at
        # face value they put the USSR player about 1300 points behind whatever
        # either player did.  The score is a pure sum, so shifting each side's
        # baseline by the event's own effect cancels it, while the opinions
        # themselves - and everything that reacts to them - still change.
        for power, prior in zip((usa, ussr), before):
            moved = power.prestige(world) - prior
            power.initScore += moved
            power.oldScore += moved

        headline = self.headline
        if callable(headline):
            headline = headline(world)
        world.addNews(world.country[self.actor],
                      world.country[self.victim if self.victim is not None else self.actor],
                      world.country[self.victim if self.victim is not None else self.actor],
                      WORLD_EVENT, 0, 0, False, text=headline,
                      importance=self.importance)
        return headline


def country_id(name):
    """Resolve a country name to its id, or None.

    Hard-coding ids here was a mistake: the first version of this file used ids
    guessed from a stale reading of the data, two of them pointed past the end
    of the country list, and the ``except`` in :func:`apply_events` swallowed the
    result — the event simply never fired and nothing said so.  Looking the name
    up costs nothing and survives the data being reordered.
    """
    import Local
    for index in range(len(Local.strings) - Local.DATA_COUNTRIES):
        try:
            if Local.strings[Local.DATA_COUNTRIES + index][Local.CTRY_NAME] == name:
                return index
        except (IndexError, TypeError):
            break
    return None


USA = 0
USSR = 1
UNITED_KINGDOM = country_id("United Kingdom")
POLAND = country_id("Poland")
AFGHANISTAN = country_id("Afghanistan")
ARGENTINA = country_id("Argentina")
WEST_GERMANY = country_id("West Germany")
EAST_GERMANY = country_id("East Germany")
HUNGARY = country_id("Hungary")
CZECHOSLOVAKIA = country_id("Czechoslovakia")
SOUTH_KOREA = country_id("South Korea")


EVENTS = (
    HistoricalEvent(
        1982, "falklands",
        "Falklands War",
        "British task force sails south; Argentina refuses to withdraw from the islands.",
        actor=UNITED_KINGDOM, victim=ARGENTINA,
        effects={"nastiness": 3, "usa_pugnacity": 2, "victim_opinion": -14,
                 "sphere": -2},
    ),
    HistoricalEvent(
        1982, "brezhnev_dies",
        "Brezhnev dies",
        "Leonid Brezhnev is dead. Yuri Andropov takes the General Secretaryship.",
        actor=USSR,
        effects={"ussr_pugnacity": 6, "ussr_integrity": 8, "detente": -8},
    ),
    HistoricalEvent(
        1983, "evil_empire",
        "The Evil Empire speech",
        "President Reagan tells a Florida audience that the Soviet Union is an "
        "'evil empire'.",
        actor=USA,
        effects={"nastiness": 7, "ussr_pugnacity": 4, "detente": -14,
                 "world_opinion_usa": -4},
    ),
    HistoricalEvent(
        1983, "sdi",
        "Strategic Defence Initiative",
        "The President announces a programme to build a shield against ballistic "
        "missiles. Moscow calls it a plan to win a nuclear war.",
        actor=USA,
        effects={"nastiness": 8, "ussr_pugnacity": 5, "ussr_integrity": 6,
                 "detente": -12},
    ),
    HistoricalEvent(
        1983, "able_archer",
        "Able Archer 83",
        "NATO's annual command exercise begins. Soviet air regiments are placed on "
        "alert; for a week neither side is certain the other is exercising.",
        actor=USA,
        # The single most dangerous week of the decade: it does not choose a
        # side, it just makes every later crisis harder to walk back from.
        effects={"nastiness": 16, "ussr_pugnacity": 8, "detente": -10},
        importance=60,
    ),
    HistoricalEvent(
        1983, "kal007",
        "Korean Air Lines 007",
        "A Soviet interceptor destroys a civilian airliner over Sakhalin. All 269 "
        "aboard are lost.",
        actor=USSR, victim=SOUTH_KOREA,
        effects={"nastiness": 10, "world_opinion_ussr": -14, "detente": -18,
                 "victim_opinion": -20},
        importance=55,
    ),
    HistoricalEvent(
        1984, "chernenko",
        "Chernenko succeeds Andropov",
        "Konstantin Chernenko, seventy-two and in poor health, becomes General "
        "Secretary. Moscow's foreign policy goes quiet.",
        actor=USSR,
        effects={"ussr_pugnacity": -6, "ussr_integrity": -4, "nastiness": -4},
    ),
    HistoricalEvent(
        1985, "gorbachev",
        "Gorbachev comes to power",
        "Mikhail Gorbachev becomes General Secretary and speaks of new thinking. "
        "The West does not yet know what to make of him.",
        actor=USSR,
        effects={"ussr_pugnacity": -14, "ussr_integrity": 6, "detente": 16,
                 "nastiness": -10, "world_opinion_ussr": 4},
        importance=50,
    ),
    HistoricalEvent(
        1986, "chernobyl",
        "Chernobyl",
        "Reactor four at Chernobyl burns. Moscow says nothing for two days while "
        "the cloud crosses Europe.",
        actor=USSR,
        effects={"world_opinion_ussr": -12, "ussr_integrity": -10, "nastiness": -3},
        importance=55,
    ),
    HistoricalEvent(
        1986, "reykjavik",
        "The Reykjavik summit",
        lambda world: ("Reagan and Gorbachev meet in Iceland. The talks collapse over "
                       "missile defence, but both men leave believing the other is "
                       "serious."
                       if world.USA.diplOpinion[1] > -40 else
                       "Reagan and Gorbachev meet in Iceland. Nothing is agreed, and "
                       "the meeting ends in recrimination."),
        actor=USA,
        # Only pays off if the two sides are still talking when it arrives.
        effects={"detente": 20, "nastiness": -8},
        importance=50,
    ),
    HistoricalEvent(
        1987, "inf_treaty",
        "The INF treaty",
        "The United States and the Soviet Union sign a treaty eliminating a whole "
        "class of nuclear weapons.",
        actor=USSR,
        effects={"detente": 26, "nastiness": -14, "world_opinion_usa": 5,
                 "world_opinion_ussr": 5},
        importance=55,
    ),
    HistoricalEvent(
        1988, "afghan_withdrawal",
        "The withdrawal from Afghanistan",
        "Soviet forces begin leaving Afghanistan. It is the first time Moscow has "
        "given up a client since the Second World War.",
        actor=USSR, victim=AFGHANISTAN,
        effects={"ussr_integrity": -14, "world_opinion_ussr": -4, "nastiness": -8,
                 "detente": 12},
        importance=55,
    ),
    HistoricalEvent(
        1989, "wall",
        "The Wall comes down",
        "The border between East and West Berlin is open. The Eastern bloc is "
        "coming apart.",
        actor=USSR, victim=EAST_GERMANY,
        effects={"world_opinion_ussr": -16, "ussr_pugnacity": -12,
                 "nastiness": -18, "detente": 24},
        importance=70,
    ),
    HistoricalEvent(
        1990, "reunification",
        "German reunification",
        "Germany is one country again, inside NATO. The post-war settlement is over.",
        actor=USA, victim=WEST_GERMANY,
        effects={"world_opinion_usa": 6, "detente": 18, "nastiness": -10},
        importance=65,
    ),
)

#: Events that raised while firing: (key, reason). A test asserts this
#: stays empty, because a silent failure here is invisible in play.
FAILED = []

#: Fast lookup by year.
BY_YEAR = {}
for _event in EVENTS:
    BY_YEAR.setdefault(_event.year, []).append(_event)


def events_for(world):
    """Events due this year that have not fired yet."""
    fired = getattr(world, "firedEvents", None)
    if fired is None:
        fired = world.firedEvents = []
    return [e for e in BY_YEAR.get(world.year, ()) if e.key not in fired]


def apply_events(world):
    """Fire this year's events.  Returns the headlines that were added.

    Called from ``prePlanMove``: the events of a year land at the start of that
    year, before either side moves, so both players see them in the news and can
    react during their own turn.
    """
    if not (GAME_START_YEAR < world.year <= GAME_END_YEAR):
        return []
    headlines = []
    for event in events_for(world):
        try:
            headlines.append(event.apply(world))
        except Exception as exc:
            # A broken event must never take a turn down, but it must not vanish
            # silently either: record it so a test can see it.
            FAILED.append((event.key, "%s: %s" % (type(exc).__name__, exc)))
            world.firedEvents.append(event.key)
            continue
        world.firedEvents.append(event.key)
    return headlines
