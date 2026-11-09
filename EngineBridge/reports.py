"""Read-only report DTOs using the original rules, without importing Qt.

All report builders work on a snapshot clone: objective predicates may maintain
bookkeeping, but opening a report must never change the live game or RNG.
"""

import re

import Local
from constants import (AVL_ACTIONS, ENCYCLOPEDIA_UNITS, GAME_BASE_YEAR,
                       INAVL_MAP_MODES, MAP_MODE_COUNT)
from GameLogic import Objectives
from GameLogic.Globals import econConv, intvConv, mAidConv, tdiv
from GameLogic.MovePlanner import estimate_error
from GameLogic.PolicyRules import UNIT_MODES, policy_info
from Net.State import clone_world

from .localization import POLICIES_RU, country_name, reason_ru, step_ru


class ReportError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


MAP_NAMES_RU = (
    "Сферы влияния", "Главные события", "Вес в престиже", "Повстанческое движение",
    "Устойчивость правительства", "Риск финляндизации в пользу США", "Риск финляндизации в пользу СССР",
    "Страны в состоянии войны", "Отношение выбранной страны к другим", "Военная помощь от выбранной страны",
    "Помощь повстанцам от выбранной страны", "Правительственные войска от выбранной страны",
    "Войска повстанцам от выбранной страны", "Экономическая помощь от выбранной страны",
    "Дестабилизация выбранной страной", "Давление выбранной страны", "Договоры выбранной страны",
    "Отношение других к выбранной стране", "Военная помощь выбранной стране", "Помощь повстанцам выбранной страны",
    "Правительственные войска в выбранной стране", "Войска повстанцев в выбранной стране",
    "Номинальный ВНП", "ВНП на душу населения", "Потребление: объём", "Потребление на душу населения",
    "Потребление: доля ВНП", "Инвестиции: объём", "Инвестиции на душу населения", "Инвестиции: доля ВНП",
    "Военные расходы: объём", "Военные расходы на душу населения", "Военные расходы: доля ВНП",
    "Население", "Военнослужащие", "Грамотность", "Энергопотребление на душу населения", "Потребление калорий",
    "Врачи", "Детская смертность", "Охват школьным обучением", "Телевизоры", "Телефоны",
    "Демонстрации протеста", "Погибшие от политического насилия", "Беспорядки", "Вооружённые нападения",
    "Убийства", "Политические казни", "Политические права", "Гражданские права", "Доля сельского хозяйства",
    "Доля промышленности", "Доля услуг", "Доля торговли", "Доля государственных налогов",
    "Доля государственного образования", "Доля государственного здравоохранения",
    "Торговля от выбранной страны", "Торговля в пользу выбранной страны")

_TAG_RU = {
    "relation": ("Враг", "Враждебность", "Холодные", "Прохладные", "Нейтральные", "Добрые", "Дружественные", "Тёплые", "Близкие"),
    "sphere": ("Полностью СССР", "Очень сильное влияние СССР", "Сильное влияние СССР", "Умеренное влияние СССР", "Заметное влияние СССР", "Слабое влияние СССР", "Нейтральная сфера", "Слабое влияние США", "Заметное влияние США", "Умеренное влияние США", "Сильное влияние США", "Очень сильное влияние США", "Полностью США"),
    "event": ("Нет крупных событий", "Революция", "Переворот", "Финляндизация — США", "Финляндизация — СССР"),
    "insurgency": ("Гражданская война", "Крупная партизанская война", "Малая партизанская война", "Массовый терроризм", "Ограниченный терроризм", "Слабые волнения", "Мирная обстановка"),
    "stability": ("На грани падения", "Крайне неустойчивое", "Неустойчивое", "Слабое", "Удовлетворительное", "Устойчивое", "Сильное", "Очень сильное"),
    "finlandization": ("Защищена", "Низкий", "Умеренный", "Высокий", "Очень высокий"),
    "war": ("Мир", "Война"),
    "military": ("Незначительная", "Очень слабая", "Слабая", "Ограниченная", "Умеренная", "Сильная", "Очень сильная", "Сверхдержава"),
    "ideology": ("Крайне левая", "Крайне левая", "Крайне левая", "Радикально левая", "Выраженно левая", "Левая", "Умеренно левая", "Слегка левая", "Центристская", "Слегка правая", "Умеренно правая", "Правая", "Выраженно правая", "Радикально правая", "Крайне правая", "Крайне правая", "Крайне правая"),
}
_GROUPS = {"relation": Local.TAG_RELATION, "sphere": Local.TAG_SPHERE, "event": Local.TAG_EVENT,
           "insurgency": Local.TAG_INSURGENCY, "stability": Local.TAG_COUP_CHANCE,
           "finlandization": Local.FINL_PROB, "war": Local.TAG_WARPEACE,
           "military": Local.TAG_STREMGTH, "ideology": Local.TAG_IDEOLOGY}
_POLICY_MODES = {9: 2, 10: 3, 11: 4, 12: 5, 13: 1, 14: 0, 15: 6, 16: 7,
                 18: 2, 19: 3, 20: 4, 21: 5, 58: 8, 59: 8}
_DISCRETE_GROUPS = {0: "sphere", 1: "event", 3: "insurgency", 4: "stability",
                    5: "finlandization", 6: "finlandization", 7: "war", 8: "relation", 17: "relation"}
_HEAT = ("#faf0d2", "#f6c86c", "#e88c3c", "#c64a30", "#8c1a1a")
_RESOURCE = ("#fae8a0", "#f6c45a", "#e88232", "#b42e20")
_ENCYCLOPEDIA = ("#b4e8aa", "#78c878", "#389650", "#10502e")
_DIPLO = ("#b03030", "#e28484", "#eeeee8", "#78be78", "#2e7d46")
_SPHERE = ("#b02c26", "#e28c82", "#eeeee8", "#78a4dc", "#265ca8")
_UNITS_RU = {4: "%", 6: "фунтов угольного эквивалента", 10: "калорий", 7: "на миллион", 8: "на тысячу", 11: "", 9: "баллов", 5: "% ВНП"}
_TABLES = ("destab", "econAid", "govtAid", "insgAid", "govtIntv", "insgIntv", "pressure", "treaty", "trade")


def _tag(group, value, ru=False):
    labels = _TAG_RU[group] if ru else Local.strings[_GROUPS[group]]
    return labels[max(0, min(len(labels) - 1, int(value)))]


def _clean(text):
    return re.sub(r"<[^>]+>", "", str(text))


def _mode_name(mode):
    if mode < 35:
        return Local.strings[Local.MAP_MODE_NAME][mode].replace("\n", " ").strip()
    return Local.strings[Local.MENU][72 if mode == 58 else 73 if mode == 59 else mode - 4].strip()


def mode_registry(world):
    unavailable = INAVL_MAP_MODES[min(world.level, 5) - 1]
    return [{"id": mode, "label": _mode_name(mode), "label_ru": MAP_NAMES_RU[mode],
             "available": mode not in unavailable,
             "requires_country": 8 <= mode <= 21 or mode in (58, 59)} for mode in range(MAP_MODE_COUNT)]


def _raw_map_value(world, country, mode, source):
    c = country
    if mode == 0: return c.getSphOfInfluence(world)
    if mode == 1: return c.getMajorEvents()
    if mode == 2: return c.prestigeVal // 8
    if mode == 3: return c.getInsurgency()
    if mode == 4: return c.getGovtStability()
    if mode in (5, 6): return c.getCloseUpInfoValue(world, world.country[mode - 5], 10)[1]
    if mode == 7: return int(c.id > 1 and any(value == -127 for value in c.diplOpinion[2:]))
    if mode == 8: return source.getDiplOpinionTowards(c)
    if mode == 17: return c.getDiplOpinionTowards(source)
    if mode in _POLICY_MODES:
        action = _POLICY_MODES[mode]
        incoming = mode in (18, 19, 20, 21, 59)
        actor, target = (c, source) if incoming else (source, c)
        table = getattr(actor, _TABLES[action], None)
        return table[target.id] if table is not None else 0
    if mode == 22: return c.getNominalGNP(3)
    if mode == 23: return c.getGNPpcap(3)
    if 24 <= mode <= 32:
        sector, kind = divmod(mode - 24, 3)
        return (c.getNominalGNP(sector) if kind == 0 else c.getGNPpcap(sector)
                if kind == 1 else c.gnpFrac[sector] / 255.0)
    if mode == 33: return c.population
    if mode == 34: return c.milMen
    index = mode - 35
    return c.encyclopedia[index] if 0 <= index < len(c.encyclopedia) else 0


def _raw_underlying(world, c, mode, source, displayed):
    if mode == 0: return c.dMess
    if mode == 2: return c.prestigeVal
    if mode == 3: return c.strengthRatio
    if mode == 4: return c.govtPopul
    if mode in (5, 6): return c.finlProb[mode - 5]
    if mode == 8: return source.diplOpinion[c.id]
    if mode == 17: return c.diplOpinion[source.id]
    return displayed


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _lerp(first, last, fraction):
    fraction = min(1, max(0, fraction))
    return "#%02x%02x%02x" % tuple(int(a + (b - a) * fraction) for a, b in zip(_rgb(first), _rgb(last)))


def _ramp(colors, count):
    if count < 2:
        return [colors[0]]
    result = []
    for i in range(count):
        position = i / (count - 1) * (len(colors) - 1)
        low = int(position)
        result.append(_lerp(colors[low], colors[min(low + 1, len(colors) - 1)], position - low))
    return result


def _discrete(mode):
    if mode in _POLICY_MODES:
        action = _POLICY_MODES[mode]
        return ([Local.parseValue(UNIT_MODES[action], step) for step in range(6)],
                [step_ru(action, step) for step in range(6)], _HEAT)
    group = _DISCRETE_GROUPS.get(mode)
    if group is None:
        return None
    ramp = (_SPHERE if mode == 0 else _DIPLO if mode in (8, 17) else
            ("#3a4756", "#c0553f", "#3f8f5c", "#8d5fb8", "#c9a227") if mode == 1 else
            ("#e8e4d8", "#b03030") if mode == 7 else tuple(reversed(_HEAT)) if mode in (3, 4) else _HEAT)
    return list(Local.strings[_GROUPS[group]]), list(_TAG_RU[group]), ramp


def _map_caption(mode, value, ru=False):
    discrete = _discrete(mode)
    if discrete:
        labels = discrete[1 if ru else 0]
        return labels[max(0, min(len(labels) - 1, int(value)))]
    if mode == 2:
        return "%s %s" % (format(int(value), ","), "баллов престижа" if ru else "prestige points")
    if mode in (22, 24, 27, 30):
        return "%s млн долларов" % (value * 100) if ru else Local.formatValue(value, 11)
    if mode in (23, 25, 28, 31):
        return "%s долларов" % value if ru else Local.formatValue(value, 12)
    if mode in (26, 29, 32):
        return "%.1f%%" % (value * 100)
    if mode == 33:
        return "%s %s" % (format(int(value * 100000), ","), "человек" if ru else "people")
    if mode == 34:
        return "%s %s" % (format(int(value * 1000), ","), "военнослужащих" if ru else "troops")
    if 35 <= mode <= 57:
        unit = ENCYCLOPEDIA_UNITS[mode - 35]
        name = _UNITS_RU[unit] if ru else Local.strings[Local.UNIT][unit]
        return ("%s %s" % (format(int(value), ","), name)).strip()
    return str(value)


def map_report(world, mode, source_id=None):
    if type(mode) is not int or not 0 <= mode < MAP_MODE_COUNT:
        raise ReportError("invalid_argument", "map mode must be an integer from 0 to 59")
    registry = mode_registry(world)
    if not registry[mode]["available"]:
        raise ReportError("mode_unavailable", "this map mode is unavailable at the current difficulty")
    source_id = world.human if source_id is None else source_id
    if type(source_id) is not int or not 0 <= source_id < len(world.country):
        raise ReportError("invalid_argument", "country_id must be an integer from 0 to 79")
    source = world.country[source_id]
    values = [_raw_map_value(world, c, mode, source) for c in world.country]
    minimum, maximum, mean = min(values), max(values), sum(values) / len(values)
    discrete = _discrete(mode)
    countries = []
    if discrete:
        en, ru, ramp = discrete
        colors = _ramp(ramp, len(en))
        scale = {"kind": "discrete", "min": minimum, "mean": mean, "max": maximum,
                 "breaks": list(range(len(en))), "legend": [dict(index=i, label=_clean(en[i]), label_ru=ru[i], color=colors[i]) for i in range(len(en))]}
        if mode in (8, 17):
            scale.update(raw_breaks=[-100, -72, -44, -16, 16, 44, 62, 100], comparison="strictly_greater")
    else:
        ramp = ("#4a2f10", "#efe9dd", "#e0a33c") if mode == 2 else _ENCYCLOPEDIA if mode >= 35 else _RESOURCE
        colors = _ramp(ramp, 128)
        breaks = [0, mean / 2, mean, (mean + maximum) / 2, maximum]
        legend_colors = _ramp(ramp, 5)
        scale = {"kind": "diverging" if mode == 2 else "relative", "min": minimum, "mean": mean, "max": maximum,
                 "lower_anchor": 0, "breaks": breaks,
                 "legend": [dict(index=i, label=("Minimum", "", "Mean", "", "Maximum")[i],
                                 label_ru=("Минимум", "", "Среднее", "", "Максимум")[i], value=breaks[i], color=legend_colors[i]) for i in range(5)]}
    for c, value in zip(world.country, values):
        if discrete:
            index = max(0, min(len(colors) - 1, int(value)))
            normalized, color = index / max(1, len(colors) - 1), colors[index]
        elif mode == 2:
            average = mean or 1.0
            if value > average and maximum > average:
                fraction = (value - average) / (maximum - average)
                normalized, color = .5 + .5 * fraction, _lerp("#efe9dd", "#e0a33c", fraction)
            else:
                fraction = max(0, min(1, value / average))
                normalized, color = fraction / 2, _lerp("#efe9dd", "#4a2f10", 1 - fraction)
            index = int(normalized * 127)
        else:
            index = 64 + int((value - mean) / (maximum - mean) * 63) if value > mean and maximum > mean else int(value / mean * 64) if mean > 0 else 0
            index = max(0, min(127, index))
            normalized, color = index / 127, colors[index]
        countries.append({"id": c.id, "value": value, "raw_value": _raw_underlying(world, c, mode, source, value),
                          "label": _clean(_map_caption(mode, value)), "label_ru": _map_caption(mode, value, True),
                          "color_index": index, "normalized": normalized, "color": color})
    return {"kind": "map", "mode": mode, "label": _mode_name(mode), "label_ru": MAP_NAMES_RU[mode],
            "source_country": source_id if registry[mode]["requires_country"] else None,
            "registry": registry, "scale": scale, "countries": countries}


def _standing(world, power):
    return power.historyScore[-1] if (world.NWFlag or world.ANWFlag) and power.historyScore else power.score - power.initScore


def scores_report(world):
    nuclear = bool(world.NWFlag or world.ANWFlag)
    rows = []
    for p in world.country[:2]:
        history = list(p.historyScore)
        rows.append({"side": p.id, "name": Local.countryName(p.id), "name_ru": country_name(p.id),
                     "standing": _standing(world, p), "delta": history[-1] - history[-2] if len(history) > 1 else 0,
                     "total": p.score, "baseline": p.initScore, "base_prestige": p.prestige(world),
                     "objective_bonus": 0 if nuclear else Objectives.bonus(world, p.id), "history": history})
    gap = rows[0]["standing"] - rows[1]["standing"]
    return {"kind": "scores", "year": world.year, "nuclear": nuclear, "ended": bool(world.winFlag or nuclear),
            "winner": None if nuclear or not world.winFlag or gap == 0 else 0 if gap > 0 else 1,
            "leader": None if nuclear or gap == 0 else 0 if gap > 0 else 1,
            "gap": abs(gap), "rows": rows,
            "years": list(range(GAME_BASE_YEAR, GAME_BASE_YEAR + max(len(row["history"]) for row in rows)))}


_OBJECTIVES_RU = {
    "bloc_intact": ("Сохранить единство блока", "У каждого указанного союзника договор с вами должен быть выше, чем с соперником. Выход одного союзника нарушает обязательство."),
    "gulf_held": ("Сохранить влияние в Персидском заливе", "Как минимум две страны из Ирака, Саудовской Аравии и Ирана должны оцениваться вами благоприятнее, чем соперником."),
    "sphere_growth": ("Расширить сферу влияния", "Ваша сфера влияния должна быть больше, чем в начале 1982 года."),
    "calm_world": ("Сохранить спокойствие до 1985 года", "Напряжённость не должна превысить 100 до конца 1985 года. Один зафиксированный выход за предел теряет это обязательство навсегда."),
    "clients_kept": ("Не потерять союзников", "Потерять можно не более трёх формальных союзников по сравнению с 1982 годом."),
}


def objectives_report(world, side=None):
    side = world.human if side is None else side
    nuclear = bool(world.NWFlag or world.ANWFlag)
    rows = []
    for objective, met, progress in Objectives.evaluate(world, side):
        title_ru, detail_ru = _OBJECTIVES_RU.get(objective.id, (objective.title, objective.detail))
        ru = progress
        if objective.check_name in ("alliance_loyal", "clients_kept"):
            match = re.match(r"(\d+) of (\d+) allies", progress)
            ru = "%s из %s союзников остаются с вами" % match.groups() if match else progress
        elif objective.check_name == "gulf_held":
            match = re.match(r"(\d+) of (\d+), (\d+) needed", progress)
            ru = "%s из %s; необходимо %s" % match.groups() if match else progress
        elif objective.check_name == "sphere_growth":
            match = re.search(r"[+-]\d+", progress)
            ru = "Изменение сферы с 1982 года: %s" % (match.group() if match else "0")
        elif objective.check_name == "calm_world":
            base = (world.objectiveState.get("baseline") or {}).get(str(side), {})
            limit, until = int(objective.params.get("limit", 100)), int(objective.params.get("until", 9999))
            if base.get("tension_broken"):
                year = base.get("tension_broken_year", "?")
                progress, ru = "Limit %d breached in %s; objective lost" % (limit, year), "Предел %d превышен в %s году; обязательство потеряно" % (limit, year)
            elif world.year > until:
                progress, ru = "Kept to %d; limit %d" % (until, limit), "Выполнено до %d года; предел %d" % (until, limit)
            else:
                known, error = world.knownNastiness[side], estimate_error(world.intel[side])
                progress, ru = "Estimated tension %d ±%d; limit %d" % (known, error, limit), "Оценка напряжённости %d ±%d; предел %d" % (known, error, limit)
        detail = ("For at least two of Iraq, Saudi Arabia and Iran, our opinion of the country must be higher than our rival's opinion of it."
                  if objective.check_name == "gulf_held" else objective.detail)
        rows.append({"id": objective.id, "title": objective.title, "title_ru": title_ru,
                     "detail": detail, "detail_ru": detail_ru, "reward": objective.reward,
                     "met": bool(met and not nuclear), "ever_met": Objectives.ever_met(world, side, objective.id),
                     "progress": progress, "progress_ru": ru,
                     "status": "void" if nuclear else "held" if met else "lost" if Objectives.ever_met(world, side, objective.id) else "unmet"})
    return {"kind": "objectives", "side": side, "void": nuclear,
            "bonus": 0 if nuclear else sum(row["reward"] for row in rows if row["met"]), "rows": rows}


def _row(key, en, ru, value, unit="", text=None, text_ru=None):
    number = format(value, ",") if isinstance(value, (int, float)) else str(value)
    en_units = {"usd_million": " million USD", "usd": " USD", "people": " people", "prestige_points": " prestige points"}
    ru_units = {"usd_million": " млн долларов", "usd": " долларов", "people": " человек", "prestige_points": " баллов престижа"}
    return {"id": key, "label": en, "label_ru": ru, "value": value, "unit": unit,
            "value_text": number + en_units.get(unit, "") if text is None else text,
            "value_text_ru": number.replace(",", " ") + ru_units.get(unit, "") if text_ru is None else text_ru}


def _history_report(world, c):
    h, series = c.history, []
    def add(key, en, ru, values, unit="index", available=True, raw=None):
        en += {"usd_million": " (USD million)", "usd": " (USD)", "policy_step": " (steps 0–5)", "fraction": " (share 0–1)"}.get(unit, "")
        ru += {"usd_million": " (млн долларов)", "usd": " (долларов)", "policy_step": " (уровни 0–5)", "fraction": " (доля 0–1)"}.get(unit, "")
        series.append({"id": key, "label": en, "label_ru": ru, "values": list(values) if available else [],
                       "raw_values": list(values if raw is None else raw) if available else [], "unit": unit, "available": available})
    add("strength_balance", "Government/rebel strength balance", "Соотношение сил правительства и повстанцев", h.sqrtStrength[0])
    add("government_popularity", "Government popularity", "Популярность правительства", h.govtPopul[0], available=world.level >= 2)
    add("security_pressure", "Internal security pressure", "Внутреннее давление на безопасность", h.milPressure[0])
    add("population", "Population", "Население", [x * 100000 for x in h.population[0]], "people", raw=h.population[0])
    add("gnp_per_capita", "GNP per capita", "ВНП на душу населения", h.GNPcap[0], "usd")
    nominal = []
    for i, gnp in enumerate(h.GNP[0]):
        fractions = [sector[i] if i < len(sector) else 0 for sector in h.gnpFrac]
        nominal.append(sum((fractions[j] * gnp // 255) * (1 if j == 2 else 2) for j in range(3)) * 100)
    add("gnp", "Nominal GNP", "Номинальный ВНП", nominal, "usd_million", raw=h.GNP[0])
    for side in (0, 1):
        name, ru = Local.countryName(side), country_name(side)
        add("opinion_%d" % side, "%s opinion of this country" % name, "Отношение стороны «%s» к этой стране" % ru, h.diplOpinion[side], "opinion")
        add("finlandization_%d" % side, "Finlandization towards %s" % name, "Риск финляндизации в пользу стороны «%s»" % ru, h.finlProb[side], available=world.level >= 3)
        for action in range(9):
            attr = _TABLES[action]
            values = getattr(h, attr)[side]
            add("policy_%d_%d" % (side, action), "%s: %s" % (name, Local.strings[Local.LABEL_POLICY][action]),
                "%s: %s" % (ru, POLICIES_RU[action]), values, "policy_step", action in AVL_ACTIONS[min(world.level, 5) - 1])
    for sector, en, ru in ((0, "Consumer", "Потребление"), (1, "Investment", "Инвестиции"), (2, "Military", "Военные расходы")):
        add("gnp_fraction_%d" % sector, en + " share", ru + ": доля ВНП", [x / 255 for x in h.gnpFrac[sector]], "fraction", raw=h.gnpFrac[sector])
    points = max((len(row["values"]) for row in series), default=0)
    return {"years": list(range(GAME_BASE_YEAR, GAME_BASE_YEAR + points)), "series": series}


def country_report(world, country_id):
    if type(country_id) is not int or not 0 <= country_id < len(world.country):
        raise ReportError("invalid_argument", "country_id must be an integer from 0 to 79")
    c = world.country[country_id]
    rows = []
    for key, en, ru, group, value in (
        ("insurgency", "Insurgency", "Повстанческое движение", "insurgency", c.getInsurgency()),
        ("government_stability", "Government stability", "Устойчивость правительства", "stability", c.getGovtStability()),
        ("government_ideology", "Government ideology", "Идеология правительства", "ideology", c.getIdeology("govt")),
        ("insurgent_ideology", "Insurgent ideology", "Идеология повстанцев", "ideology", c.getIdeology("insg")),
        ("military_power", "Military strength", "Военная мощь", "military", c.getMilPower()),
        ("sphere", "Sphere of influence", "Сфера влияния", "sphere", c.getSphOfInfluence(world))):
        if key == "government_stability" and world.level < 2:
            continue
        rows.append(_row(key, en, ru, value, text=_tag(group, value), text_ru=_tag(group, value, True)))
    rows.extend([_row("government_strength", "Government forces", "Силы правительства", c.govtStrength),
                 _row("insurgent_strength", "Insurgent forces", "Силы повстанцев", c.insgStrength),
                 _row("population", "Population", "Население", c.population * 100000, "people"),
                 _row("military_personnel", "Military personnel", "Военнослужащие", c.milMen * 1000, "people"),
                 _row("prestige", "Prestige value", "Вес в престиже", c.prestigeVal // 8, "prestige_points"),
                 _row("security_pressure", "Internal security pressure", "Внутреннее давление на безопасность", c.milPressure),
                 _row("nominal_gnp", "Nominal GNP", "Номинальный ВНП", c.getNominalGNP(3) * 100, "usd_million"),
                 _row("gnp_per_capita", "GNP per capita", "ВНП на душу населения", c.getGNPpcap(3), "usd")])
    capital = Local.strings[Local.DATA_COUNTRIES + c.id][Local.CTRY_CAPITAL]
    rows.extend([_row("capital", "Capital", "Столица", capital),
                 _row("leader", "Leader", "Руководитель", c.leaderName),
                 _row("insurgents", "Insurgent movement", "Повстанческое движение", c.getInsurgentsName())])
    pace = c.getInsurgencyChange()
    rows.append(_row("insurgency_change", "Insurgency trend", "Изменение повстанческой активности", pace,
                     text=Local.strings[Local.TAG_INSG_PACE][pace],
                     text_ru=("Повстанцы усиливаются", "Повстанцы слабеют")[pace]))
    if world.level >= 2:
        pace = c.getGovtStabilityChange()
        rows.append(_row("stability_change", "Government stability trend", "Изменение устойчивости правительства", pace,
                         text=Local.strings[Local.TAG_COUP_PACE][pace],
                         text_ru=("Быстро ослабевает", "Ослабевает", "Медленно ослабевает", "Медленно укрепляется", "Укрепляется", "Быстро укрепляется")[pace]))
    for sector, en, ru in ((0, "Consumer spending", "Потребительские расходы"), (1, "Investment spending", "Инвестиционные расходы"),
                            (2, "Military spending", "Военные расходы")):
        amount, percentage = c.getNominalGNP(sector) * 100, c.gnpFrac[sector] / 255 * 100
        rows.append(_row("gnp_sector_%d" % sector, en, ru, amount, "usd_million",
                         text="%s million USD (%.1f%% of GNP)" % (format(amount, ","), percentage),
                         text_ru="%s млн долларов (%.1f%% ВНП)" % (format(amount, ",").replace(",", " "), percentage)))
    policies, relations, totals = [], [], []
    for p in world.country[:2]:
        relations.append({"side": p.id, "opinion_of_country": p.diplOpinion[c.id],
                          "country_opinion_of_side": c.diplOpinion[p.id],
                          "score_contribution": 0 if c.id < 2 else tdiv(c.diplOpinion[p.id] * c.prestigeVal, 1024),
                          "legacy_closeup_value": tdiv(p.diplOpinion[c.id] * c.prestigeVal, 1024),
                          "finlandization": c.getFinlizProb(p) if world.level >= 3 else None,
                          "finlandization_raw": c.finlProb[p.id] if world.level >= 3 else None})
        rows.extend([
            _row("opinion_out_%d" % p.id, "%s opinion of this country" % Local.countryName(p.id),
                 "Отношение стороны «%s» к этой стране" % country_name(p.id), p.diplOpinion[c.id], "opinion"),
            _row("opinion_in_%d" % p.id, "This country's opinion of %s" % Local.countryName(p.id),
                 "Отношение этой страны к стороне «%s»" % country_name(p.id), c.diplOpinion[p.id], "opinion")])
        if c.id >= 2:
            rows.append(_row("score_contribution_%d" % p.id, "Contribution to %s prestige" % Local.countryName(p.id),
                             "Вклад в престиж стороны «%s»" % country_name(p.id),
                             tdiv(c.diplOpinion[p.id] * c.prestigeVal, 1024), "prestige_points"))
        if world.level >= 3:
            risk = c.getFinlizProb(p)
            rows.append(_row("finlandization_%d" % p.id, "Finlandization towards %s" % Local.countryName(p.id),
                             "Риск финляндизации в пользу стороны «%s»" % country_name(p.id), risk,
                             text=_tag("finlandization", risk), text_ru=_tag("finlandization", risk, True)))
        if c.id >= 2:
            for action in AVL_ACTIONS[min(world.level, 5) - 1]:
                info = policy_info(world, p, action, c)
                policies.append({"side": p.id, "action": action, "label": Local.strings[Local.LABEL_POLICY][action],
                                 "label_ru": POLICIES_RU[action], "old": info.old, "steps": info.steps(),
                                 "ceiling": info.ceiling, "floor": info.floor, "available": info.avail,
                                 "reason": info.reason, "reason_ru": reason_ru(info.reason),
                                 "value_text": _clean(Local.parseValue(info.mode, info.old)), "value_text_ru": step_ru(action, info.old)})
                rows.append(_row("policy_%d_%d" % (p.id, action),
                    "%s: %s" % (Local.countryName(p.id), Local.strings[Local.LABEL_POLICY][action]),
                    "%s: %s" % (country_name(p.id), POLICIES_RU[action]), info.old, "policy_step",
                    text="%s%s (step %d; ceiling %d)" % (_clean(Local.parseValue(info.mode, info.old)), " annually" if action in (1, 2, 3) else "", info.old, info.ceiling),
                    text_ru="%s (уровень %d; предел %d)" % (step_ru(action, info.old), info.old, info.ceiling)))
    for action, attr, conv, multiplier, unit in ((2, "govtAid", mAidConv, 20, "usd_million"), (3, "insgAid", mAidConv, 20, "usd_million"),
                                                (4, "govtIntv", intvConv, 1000, "people"), (5, "insgIntv", intvConv, 1000, "people")):
        totals.append({"action": action, "label": Local.strings[Local.LABEL_POLICY][action], "label_ru": POLICIES_RU[action],
                       "value": sum(conv(getattr(donor, attr)[c.id]) for donor in world.country) * multiplier, "unit": unit})
        rows.append(_row("incoming_total_%d" % action, "All donors: %s" % Local.strings[Local.LABEL_POLICY][action],
                         "Всего от всех стран: %s" % POLICIES_RU[action], totals[-1]["value"], unit))
    if c.id < 2:
        rows.extend([_row("available_aid", "Available military aid", "Доступный бюджет военной помощи", c.getAvailableAid() * 10, "usd_million"),
                     _row("available_troops", "Available troops", "Свободный контингент", c.getAvailableMen() * 1000, "people"),
                     _row("credibility", "Treaty credibility", "Надёжность договорных обязательств", c.integrity, "index")])
        remaining_economic = c.GNP // 44 - 2 * sum(econConv(value) for value in c.econAid[2:])
        rows.append(_row("available_economic_aid", "Available economic aid", "Доступный бюджет экономической помощи", remaining_economic * 100, "usd_million"))
    encyclopedia = [{"id": i + 35, "label": _mode_name(i + 35), "label_ru": MAP_NAMES_RU[i + 35], "value": value,
                     "value_text": _map_caption(i + 35, value), "value_text_ru": _map_caption(i + 35, value, True),
                     "unit": Local.strings[Local.UNIT][ENCYCLOPEDIA_UNITS[i]], "unit_ru": _UNITS_RU[ENCYCLOPEDIA_UNITS[i]]}
                    for i, value in enumerate(c.encyclopedia[:23])]
    return {"kind": "country", "year": world.year,
            "country": {"id": c.id, "name": Local.countryName(c.id), "name_ru": country_name(c.id),
                        "capital": capital, "leader": c.leaderName, "insurgents": c.getInsurgentsName(),
                        "local_news": c.localNews},
            "rows": rows, "relations": relations, "policies": policies, "incoming_totals": totals,
            "history": _history_report(world, c), "encyclopedia": encyclopedia}


def build_report(world, args, selected_country=None):
    """Snapshot before invoking predicates that can update objective scratch data."""
    kind = args.get("kind")
    copied = clone_world(world)
    if kind == "scores": return scores_report(copied)
    if kind == "objectives": return objectives_report(copied)
    if kind == "country": return country_report(copied, args.get("country_id", selected_country))
    if kind == "map": return map_report(copied, args.get("mode", 0), args.get("country_id", selected_country))
    raise ReportError("invalid_argument", "report kind must be country, scores, objectives or map")
