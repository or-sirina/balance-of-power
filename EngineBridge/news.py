"""Read-only presentation of the current news feed, without invented provenance."""

import hashlib
import json

import Local

from constants import WORLD_EVENT
from .localization import country_name, historical_key, news_ru, step_ru, type_ru

_CATEGORIES = {
    "historical": ("Historical event", "Историческое событие"),
    "domestic": ("Domestic affairs", "Внутренние события"),
    "war": ("Armed conflict", "Вооружённый конфликт"),
    "diplomacy": ("Diplomacy", "Дипломатия"),
    "policy": ("Foreign policy", "Внешняя политика"),
}
_CONTEXT = {
    "historical": ("Review the countries involved to assess your next move.", "Оцените положение затронутых стран перед следующим решением."),
    "domestic": ("Review the country's government and insurgency before choosing your response.", "Оцените положение правительства и повстанцев перед выбором ответа."),
    "war": ("Review both countries and their foreign support before choosing your response.", "Оцените положение обеих стран и их внешнюю поддержку перед выбором ответа."),
    "diplomacy": ("Review the country's relations with both superpowers.", "Оцените отношения страны с обеими сверхдержавами."),
    "policy": ("Compare the previous and current policy before choosing your response.", "Сравните прежнюю и текущую политику перед выбором ответа."),
}
_POLICY_NAMES = (
    ("Destabilization", "дестабилизации"),
    ("Economic aid", "экономической помощи"),
    ("Military aid", "военной помощи"),
    ("Aid to insurgents", "помощи повстанцам"),
    ("Government intervention", "военного вмешательства на стороне правительства"),
    ("Insurgent intervention", "военного вмешательства на стороне повстанцев"),
    ("Diplomatic pressure", "дипломатического давления"),
    ("Treaty", "уровня договора"),
    ("Trade", "уровня торговли"),
)
_POLICY_CONTEXT = (
    ("Destabilization supports opposition to the government.", "Дестабилизация поддерживает противников правительства."),
    ("Economic aid provides financial support to the government.", "Экономическая помощь оказывает финансовую поддержку правительству."),
    ("Military aid supplies the government's armed forces.", "Военная помощь снабжает вооружённые силы правительства."),
    ("Aid to insurgents supplies forces opposing the government.", "Помощь повстанцам снабжает силы, выступающие против правительства."),
    ("Intervention commits troops to support the government.", "Военное вмешательство направляет войска на поддержку правительства."),
    ("Intervention commits troops to support the insurgents.", "Военное вмешательство направляет войска на поддержку повстанцев."),
    ("Diplomatic pressure seeks to influence the country's foreign-policy alignment.", "Дипломатическое давление направлено на изменение внешнеполитической ориентации страны."),
    ("Treaties define the strength of diplomatic and defence commitments.", "Договоры определяют уровень дипломатических и оборонных обязательств."),
    ("Trade policy defines the level of commercial relations.", "Торговая политика определяет уровень торговых отношений."),
)


def _policy_headlines(news):
    direction = 0 if news.new > news.old else (1 if news.new < news.old else 2)
    label, label_ru = _POLICY_NAMES[news.action]
    verb = ("increased", "reduced", "unchanged")[direction]
    change_ru = ("повышение", "снижение", "сохранение")[direction]
    return ("%s: %s %s" % (Local.countryName(news.target.id), label.lower(), verb),
            "%s: %s %s" % (country_name(news.target.id), change_ru, label_ru))


def present_news(world, questionable):
    """Keep positional command ids; add deterministic identities for feed selection.

    Generated News objects have no creation year. The feed's current year is
    only an identity scope, never represented as an individual event's date.
    Nothing is persisted and no hidden diplomatic or crisis state is read.
    """
    result, occurrences = [], {}
    for index, news in enumerate(world.news):
        actor, target, host = news.actor.id, news.target.id, news.host.id
        if news.action == WORLD_EVENT:
            category = "historical"
        elif actor == target:
            category = "domestic"
        elif actor >= 2 and target >= 2 and news.action == 6:
            category = "war"
        elif target < 2 and news.action == 0:
            category = "diplomacy"
        else:
            category = "policy"
        key = historical_key(news)
        year = None
        if key:
            from GameLogic.HistoricalEvents import EVENTS
            year = next((event.year for event in EVENTS if event.key == key), None)
        signature = json.dumps([world.year, actor, target, host, news.action,
                                getattr(news, "customText", None)], ensure_ascii=True)
        occurrence = occurrences.get(signature, 0)
        occurrences[signature] = occurrence + 1
        story_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24] + ":" + str(occurrence)
        has_values = category == "policy" and 0 <= news.action <= 8 and not news.isEventWithNoValues()
        context, context_ru = _CONTEXT[category]
        headline, headline_ru = news.text, news_ru(news)
        if has_values:
            headline, headline_ru = _policy_headlines(news)
            context, context_ru = _POLICY_CONTEXT[news.action]
        result.append({
            "id": index, "story_key": story_key,
            "text": news.text, "text_ru": news_ru(news),
            "headline": headline, "headline_ru": headline_ru,
            "type": news.getTypeName(), "type_ru": type_ru(news),
            "actor": actor, "target": target, "host": host,
            "country_id": host if type(host) is int and 0 <= host < len(world.country) else None,
            "action": news.action, "old": news.old, "new": news.new,
            "importance": news.importance,
            "category": category, "category_en": _CATEGORIES[category][0],
            "category_ru": _CATEGORIES[category][1], "year": year,
            "old_text": news.getActionValue(True) if has_values else "",
            "new_text": news.getActionValue(False) if has_values else "",
            "old_text_ru": step_ru(news.action, news.old) if has_values else "",
            "new_text_ru": step_ru(news.action, news.new) if has_values else "",
            "context": context, "context_ru": context_ru,
            "questionable": questionable(news),
        })
    return result
