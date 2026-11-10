"""Pure, public facts for the illustrative living-map layer.

Markers locate a country, never a simulated city or battle. Connections show
policy relationships, not roads, supply paths, or movement. Encyclopedia counts
are historical reference data and deliberately do not become live riot events.
Only the human policy row is included: opponent rows can contain unannounced
orders while a turn is being planned.
"""

import Local
from GameLogic.PolicyRules import UNIT_MODES
from .localization import POLICIES_RU, step_ru
from .reports import _tag

_ROUTE_TYPES = ((2, "govtAid", "government_aid", "Military aid"),
                (3, "insgAid", "insurgent_aid", "Insurgent aid"),
                (4, "govtIntv", "government_intervention", "Government intervention"),
                (5, "insgIntv", "insurgent_intervention", "Insurgent intervention"),
                (8, "trade", "trade", "Trade policy"))


def build_map_scene(world):
    """Return detached JSON values without mutating world, bookkeeping or RNG."""
    countries, events, routes = [], [], []
    for c in world.country:
        insurgency, stability, major = c.getInsurgency(), c.getGovtStability(), c.getMajorEvents()
        wars = [other.id for other in world.country[2:]
                if c.id >= 2 and other.id != c.id and c.diplOpinion[other.id] == -127]
        countries.append({"id": c.id, "insurgency": insurgency,
                          "insurgency_label": _tag("insurgency", insurgency),
                          "insurgency_label_ru": _tag("insurgency", insurgency, True),
                          "stability": stability,
                          "stability_label": _tag("stability", stability),
                          "stability_label_ru": _tag("stability", stability, True),
                          "event": major, "event_label": _tag("event", major),
                          "event_label_ru": _tag("event", major, True), "war_with": wars})
        if c.id < 2:
            continue
        if insurgency < 6:
            kind = "civil_war" if insurgency == 0 else "insurgency" if insurgency <= 2 else "unrest"
            events.append({"country_id": c.id, "kind": kind,
                           "label": _tag("insurgency", insurgency),
                           "label_ru": _tag("insurgency", insurgency, True),
                           "source": "insurgency_status"})
        # Preserve both flags when both occurred; getMajorEvents prioritizes one.
        for flag, kind, index in ((c.hasRevolution, "revolution", 1), (c.hasCoup, "coup", 2)):
            if flag:
                events.append({"country_id": c.id, "kind": kind,
                               "label": _tag("event", index), "label_ru": _tag("event", index, True),
                               "source": "turn_event"})
    actor = world.country[world.human]
    for action, table_name, kind, name in _ROUTE_TYPES:
        table = getattr(actor, table_name, ())
        for target, step in enumerate(table):
            if target == actor.id or not step:
                continue
            routes.append({"actor": actor.id, "target": target, "kind": kind,
                           "step": step, "label": name, "label_ru": POLICIES_RU[action],
                           "value_label": Local.parseValue(UNIT_MODES[action], step),
                           "value_label_ru": step_ru(action, step), "source": "human_policy"})
    return {"version": 1, "year": world.year, "countries": countries,
            "events": events, "routes": routes,
            "geography": "historical_1982_capital_anchors",
            "route_semantics": "policy_relationships",
            "notice": "Country-level status; illustrative links, not roads or troop movements.",
            "notice_ru": "Состояние стран; условные связи, не дороги и не перемещения войск."}
