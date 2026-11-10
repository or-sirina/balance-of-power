"""Opt-in experimental director: models select bounded, engine-authored events.

Call prepare under the service lock, request outside it, then apply under the
lock only after the caller's campaign/settings/revision token still matches.
No network call or world mutation happens on import or in prepare/request.
"""
import hashlib
import json

import Local
from constants import AVL_ACTIONS, GOVTAID, INSGAID, PRESSURE, WORLD_EVENT
from GameLogic.Globals import doPolicy, changeDiplOpinion
from GameLogic.News import News
from GameLogic.PolicyRules import check_request, policy_info

PREFIX = "[AI-generated] "
PREFIX_RU = "[Создано ИИ] "
MAX_HISTORY = 16


class GameMasterError(ValueError):
    """A safe, stable reason code suitable for localized service status."""


def _state(world):
    value = getattr(world, 'gameMasterState', None)
    return value if isinstance(value, dict) else {}


def validate_state(world):
    """Return a detached validated save payload; missing legacy state is {}.

    Raises GameMasterError('invalid_state') before a loaded document is installed.
    Accepts only persisted service controls and at most MAX_HISTORY engine outcomes.
    """
    import copy
    import re
    state = getattr(world, 'gameMasterState', None)
    if state is None:
        state = {}
    def require(ok):
        if not ok:
            raise GameMasterError('invalid_state')
    require(isinstance(state, dict))
    require(not set(state) - {'enabled', 'language', 'status', 'reason',
                              'last_attempt_year', 'last_year', 'history'})
    if 'enabled' in state: require(type(state['enabled']) is bool)
    if 'language' in state: require(state['language'] in ('en', 'ru'))
    if 'status' in state: require(state['status'] in ('disabled', 'ready', 'fallback', 'generated'))
    if 'reason' in state:
        require(isinstance(state['reason'], str) and len(state['reason']) <= 64
                and re.fullmatch(r'[a-z_]*', state['reason']) is not None)
    for name in ('last_attempt_year', 'last_year'):
        if name in state:
            year = state[name]
            require(type(year) is int and (year == -1 or 1900 <= year <= world.year))
    history = state.get('history', [])
    require(isinstance(history, list) and len(history) <= MAX_HISTORY)
    seen_years = set()
    for event in history:
        base = {'year', 'candidate_id', 'kind', 'target', 'old', 'new', 'headline', 'headline_ru', 'source'}
        require(isinstance(event, dict) and base <= set(event) and not set(event) - base - {'actor', 'action'})
        require(type(event['year']) is int and 1900 <= event['year'] <= world.year and event['year'] not in seen_years)
        seen_years.add(event['year'])
        require(isinstance(event['candidate_id'], str) and re.fullmatch(r'[0-9a-f]{20}', event['candidate_id']) is not None)
        require(event['source'] == 'ai_generated')
        require(event['kind'] in ('unrest', 'economic_shock', 'diplomatic_incident', 'crisis_flashpoint'))
        require(type(event['target']) is int and 2 <= event['target'] < len(world.country))
        for name in ('headline', 'headline_ru'):
            require(isinstance(event[name], str) and 3 <= len(event[name]) <= 240
                    and not any(ord(c) < 32 for c in event[name]))
        old, new = event['old'], event['new']
        require(type(old) is int and type(new) is int and abs(old) <= 2**63 - 1 and abs(new) <= 2**63 - 1)
        kind = event['kind']
        if kind == 'unrest':
            require(set(event) == base and 1 <= new < old and old - new <= 2)
        elif kind == 'economic_shock':
            require(set(event) == base and old > 100 and new == old - max(1, old // 100))
        else:
            require(type(event.get('actor')) is int and event['actor'] in (0, 1))
            if kind == 'diplomatic_incident':
                require(set(event) == base | {'actor'} and -127 <= new < old <= 127 and old - new == 3)
            else:
                require(set(event) == base | {'actor', 'action'} and type(event.get('action')) is int
                        and event['action'] in (GOVTAID, INSGAID, PRESSURE) and 0 <= old < new <= 5 and new == old + 1)
    if history:
        require([e['year'] for e in history] == sorted(seen_years))
        require(state.get('last_year') == history[-1]['year'])
    if state.get('last_year', -1) != -1:
        require(bool(history))
    for news in world.news:
        if getattr(news, 'source', None) != 'ai_generated':
            continue
        year = getattr(news, 'gmYear', None)
        require(type(year) is int)
        matches = [e for e in history if e['year'] == year
                   and e['target'] == getattr(news.target, 'id', None)]
        require(len(matches) == 1)
        event = matches[0]
        for attribute, field in (('gmHeadline', 'headline'), ('gmHeadlineRu', 'headline_ru'),
                                 ('gmKind', 'kind'), ('gmEffectOld', 'old'), ('gmEffectNew', 'new')):
            require(type(getattr(news, attribute, None)) is type(event[field])
                    and getattr(news, attribute) == event[field])
        if event['kind'] == 'crisis_flashpoint':
            require(news.action == event['action'] and news.actor.id == event['actor'])
        else:
            require(news.action == WORLD_EVENT and news.actor is news.target)
    return copy.deepcopy(state)


def _mark_news(news, world, event, checked):
    news.source = 'ai_generated'
    news.gmHeadline = checked['headline']
    news.gmHeadlineRu = checked['headline_ru']
    news.gmYear = world.year
    news.gmKind = event['kind']
    news.gmEffectOld = event['old']
    news.gmEffectNew = event['new']


def _candidate(world, kind, target, old, new, **extra):
    data = dict(kind=kind, target=target.id, old=old, new=new, **extra)
    raw = json.dumps([world.year, data], sort_keys=True).encode()
    return dict(candidate_id=hashlib.sha256(raw).hexdigest()[:20], **data)


def prepare(world, locale='en'):
    """Public event menu; never exports hidden resolve, intelligence or plans."""
    if world.twoPFlag or world.NWFlag or world.ANWFlag or world.crisis.hasBegun or world.beingQuestioned:
        raise GameMasterError('unavailable')
    state = _state(world)
    if state.get('last_year') == world.year:
        raise GameMasterError('already_generated')
    recent = {x.get('target') for x in state.get('history', [])[-2:] if isinstance(x, dict)}
    candidates = []
    actor = world.country[world.cmptr]
    for target in world.country[2:]:
        if target.id in recent:
            continue
        if target.govtPopul > 2:
            candidates.append(_candidate(world, 'unrest', target, target.govtPopul,
                                         max(1, target.govtPopul - 2)))
        if target.GNP > 100:
            candidates.append(_candidate(world, 'economic_shock', target, target.GNP,
                                         target.GNP - max(1, target.GNP // 100)))
        old = target.diplOpinion[actor.id]
        if old > -124 and actor.diplOpinion[target.id] == old:
            candidates.append(_candidate(world, 'diplomatic_incident', target, old,
                                         old - 3, actor=actor.id))
        for action in (GOVTAID, INSGAID, PRESSURE):
            if action not in AVL_ACTIONS[min(world.level, 5) - 1]:
                continue
            info = policy_info(world, actor, action, target)
            new = info.old + 1
            legal, _ = check_request(world, actor, action, target.id, new)
            # Do not merge with an existing headline: a GM flashpoint must have
            # its own exact reversible old/new pair and visible provenance.
            existing = any(n.actor is actor and n.target is target and n.action == action
                           for n in world.news)
            if new <= 5 and legal and not existing:
                candidates.append(_candidate(world, 'crisis_flashpoint', target,
                                             info.old, new, actor=actor.id, action=action))
    return dict(year=world.year, locale='ru' if locale == 'ru' else 'en',
                countries=[dict(id=c.id, name=Local.countryName(c.id)) for c in world.country],
                candidates=candidates)


def validate_response(context, response):
    if not isinstance(response, dict) or set(response) != {'candidate_id', 'headline', 'headline_ru'}:
        raise GameMasterError('invalid_response')
    key = response['candidate_id']
    if not isinstance(key, str) or not any(c['candidate_id'] == key for c in context['candidates']):
        raise GameMasterError('invalid_candidate')
    for field in ('headline', 'headline_ru'):
        headline = response[field]
        if not isinstance(headline, str) or not 3 <= len(headline.strip()) <= 240 or any(ord(c) < 32 for c in headline):
            raise GameMasterError('invalid_headline')
    return dict(year=context['year'], candidate_id=key, headline=response['headline'].strip(), headline_ru=response['headline_ru'].strip())


def request(client, context):
    """Exactly one model request; the supplied client owns provider budgets."""
    messages = [dict(role='system', content=(
        'You are an experimental game master for a Cold War strategy game. '
        'Choose exactly one supplied candidate; you cannot invent effects or alter values. '
        'Return only JSON with candidate_id, headline (English), headline_ru (Russian); both headlines 3-240 characters, one line. '
        'The headline describes this fictional event accurately, without claiming historical fact. '
        'Always supply both English and Russian headlines. '
        'crisis_flashpoint is a challengeable opponent policy increase; the human decides whether to challenge.')),
        dict(role='user', content=json.dumps(context, ensure_ascii=False))]
    return validate_response(context, client.chat_json(messages))


def apply(world, proposal, locale='en'):
    """Revalidate before any mutation. A saved applied year cannot apply twice."""
    if not isinstance(proposal, dict) or set(proposal) != {'year', 'candidate_id', 'headline', 'headline_ru'}:
        raise GameMasterError('invalid_response')
    if type(proposal['year']) is not int or proposal['year'] != world.year:
        raise GameMasterError('stale_response')
    context = prepare(world, locale)
    checked = validate_response(context, {k: proposal[k] for k in ('candidate_id', 'headline', 'headline_ru')})
    event = next(c for c in context['candidates'] if c['candidate_id'] == checked['candidate_id'])
    target = world.country[event['target']]
    text = PREFIX_RU + checked['headline_ru'] if locale == 'ru' else PREFIX + checked['headline']
    # Construct the news before touching any mechanical field.
    if event['kind'] == 'crisis_flashpoint':
        actor = world.country[event['actor']]
        news = News(target, event['action'], event['old'], event['new'], actor, target, False, text=text)
        # doPolicy accounts for aid/troop resources and adds ordinary news.
        doPolicy(world, actor, target, event['action'], event['new'])
        ordinary = next(n for n in world.news if n.actor is actor and n.target is target and n.action == event['action'])
        _mark_news(ordinary, world, event, checked)
        ordinary.customText = text
        ordinary.setStrings()
    else:
        news = News(target, WORLD_EVENT, 0, 0, target, target, True, text=text, importance=35)
        if event['kind'] == 'unrest':
            target.govtPopul = event['new']
        elif event['kind'] == 'economic_shock':
            target.GNP = event['new']
            # Military expenditure is stored in ten times the civilian
            # sector's units. Scale the existing figures to preserve units.
            target.gnpSpnd = [(spend * event['new']) // event['old'] for spend in target.gnpSpnd]
        else:
            changeDiplOpinion(target, world.country[event['actor']], event['new'] - event['old'])
        _mark_news(news, world, event, checked)
        world.news.append(news)
        world.news.sort(key=lambda n: n.importance, reverse=True)
    outcome = dict(year=world.year, **event, headline=checked['headline'], headline_ru=checked['headline_ru'], source='ai_generated')
    history = list(_state(world).get('history', []))[-(MAX_HISTORY - 1):]
    world.gameMasterState = dict(_state(world), last_year=world.year, history=history + [outcome])
    return outcome
