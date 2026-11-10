"""Russian display text from committed mechanics; never mutates game locale."""

import json
import re
from functools import lru_cache

import Local
import Paths
from constants import WORLD_EVENT
from GameLogic.Globals import econConv, intvConv, mAidConv


POLICIES_RU = ("Дестабилизация", "Экономическая помощь", "Военная помощь",
               "Помощь повстанцам", "Войска на стороне правительства",
               "Войска на стороне повстанцев", "Дипломатическое давление",
               "Договор", "Торговля")
_LABELS = {
    0: ("Нет активности", "Помощь диссидентам", "Финансирование оппозиции", "Разжигание беспорядков", "Убийства", "Поддержка переворота"),
    6: ("Нет", "Тихая дипломатия", "Публичные заявления", "Умеренное давление", "Сильное давление", "Дипломатическое наступление"),
    7: ("Нет отношений", "Дипломатические отношения", "Торговые отношения", "Военные базы", "Обычная оборона", "Ядерная оборона"),
    8: ("Нет торговли", "Торговые переговоры", "Ограниченная торговля", "Торговое соглашение", "Льготная торговля", "Полное торговое партнёрство"),
}

# Stable historical keys, including both branches of the Reykjavik headline.
HISTORY_RU = {
    "falklands": ("Фолклендская война", "Британское соединение направляется на юг; Аргентина отказывается вывести войска с островов."),
    "brezhnev_dies": ("Смерть Брежнева", "Леонид Брежнев умер. Генеральным секретарём становится Юрий Андропов."),
    "evil_empire": ("Речь об «империи зла»", "Выступая во Флориде, президент Рейган называет Советский Союз «империей зла»."),
    "sdi": ("Стратегическая оборонная инициатива", "Президент США объявляет программу защиты от баллистических ракет. Москва считает её попыткой получить возможность выиграть ядерную войну."),
    "able_archer": ("Учения Able Archer 83", "Начинаются ежегодные командные учения НАТО. Советские авиаполки приведены в боевую готовность; целую неделю стороны не уверены, что противник действительно проводит учения."),
    "kal007": ("Рейс Korean Air Lines 007", "Советский перехватчик уничтожает гражданский авиалайнер над Сахалином. Погибли все 269 человек на борту."),
    "chernenko": ("Черненко сменяет Андропова", "Генеральным секретарём становится тяжело больной 72-летний Константин Черненко. Внешняя политика Москвы становится менее активной."),
    "gorbachev": ("Приход Горбачёва к власти", "Михаил Горбачёв становится Генеральным секретарём и говорит о новом мышлении. Запад пока не понимает, чего от него ждать."),
    "chernobyl": ("Чернобыль", "Горит четвёртый реактор Чернобыльской АЭС. Москва молчит два дня, пока радиоактивное облако пересекает Европу."),
    "reykjavik": ("Встреча в Рейкьявике", "Рейган и Горбачёв встречаются в Исландии. Переговоры срываются из-за разногласий о противоракетной обороне, но оба лидера убеждены в серьёзности намерений друг друга."),
    "inf_treaty": ("Договор о РСМД", "США и СССР подписывают договор, ликвидирующий целый класс ядерного оружия."),
    "afghan_withdrawal": ("Вывод войск из Афганистана", "Советские войска начинают покидать Афганистан. Впервые после Второй мировой войны Москва отказывается от поддержки своего клиента."),
    "wall": ("Падение Берлинской стены", "Открыта граница между Восточным и Западным Берлином. Восточный блок распадается."),
    "reunification": ("Объединение Германии", "Германия вновь становится единой страной и остаётся в НАТО. Послевоенное устройство Европы уходит в прошлое."),
}
_REYKJAVIK_FAILURE = "Рейган и Горбачёв встречаются в Исландии. Договориться не удаётся; встреча заканчивается взаимными обвинениями."


@lru_cache(maxsize=1)
def country_names():
    try:
        with open(Paths.data("country_names_ru.json"), encoding="utf-8") as handle:
            names = json.load(handle)
        if isinstance(names, list) and len(names) == 80 and all(isinstance(x, str) and x for x in names):
            return tuple(names)
    except (OSError, ValueError):
        pass
    return tuple(Local.countryName(i) for i in range(80))


def country_name(country_id):
    return country_names()[country_id] if 0 <= country_id < 80 else "Неизвестная страна"


def step_ru(action, step):
    step = max(0, min(5, int(step)))
    if action in (1, 2, 3):
        millions = econConv(step) * 200 if action == 1 else mAidConv(step) * 20
        return "%s млн долларов в год" % millions
    if action in (4, 5):
        return "%s военнослужащих" % format(intvConv(step) * 1000, ",").replace(",", " ")
    return _LABELS[action][step] if action in _LABELS else str(step)


def historical_key(news):
    if getattr(news, "source", None) == "ai_generated" or news.action != WORLD_EVENT:
        return None
    from GameLogic.HistoricalEvents import EVENTS
    text = getattr(news, "customText", None) or news.text
    for event in EVENTS:
        if isinstance(event.headline, str) and event.headline == text:
            return event.key
        if event.key == "reykjavik" and str(text).startswith("Reagan and Gorbachev meet in Iceland."):
            return event.key
    return None


def type_ru(news):
    if getattr(news, "source", None) == "ai_generated" and news.action == WORLD_EVENT:
        return "Событие ИИ"
    if news.action == WORLD_EVENT:
        return "Историческое событие"
    if news.actor.id == news.target.id:
        return {0: "Внутренние события", 1: "Революция", 2: "Государственный переворот"}.get(news.action, "Внутренние события")
    if news.target.id < 2 and news.action == 0:
        return "Финляндизация"
    if news.actor.id >= 2 and news.target.id >= 2 and news.action == 6:
        return "Капитуляция" if news.old == 2 else "Военные действия"
    return POLICIES_RU[news.action] if 0 <= news.action <= 8 else "Событие"


def gm_news_text(news, ru=False):
    """Localized synthetic report, with engine-authored mechanical context."""
    headline = getattr(news, 'gmHeadlineRu' if ru else 'gmHeadline', '')
    prefix = '[Создано ИИ] ' if ru else '[AI-generated] '
    kind = getattr(news, 'gmKind', '')
    old = getattr(news, 'gmEffectOld', news.old)
    new = getattr(news, 'gmEffectNew', news.new)
    labels = {'unrest': ('Government popularity', 'Популярность правительства'),
              'economic_shock': ('Economic output', 'Объём экономики'),
              'diplomatic_incident': ('Diplomatic relations', 'Дипломатические отношения')}
    if kind in labels:
        effect = '%s: %s → %s.' % (labels[kind][int(ru)], old, new)
    elif 0 <= news.action <= 8:
        label = POLICIES_RU[news.action] if ru else Local.strings[Local.LABEL_POLICY][news.action]
        before = step_ru(news.action, news.old) if ru else news.getActionValue(True)
        after = step_ru(news.action, news.new) if ru else news.getActionValue(False)
        effect = '%s: %s → %s.' % (label, before, after)
    else:
        effect = ''
    fiction = 'Вымышленное событие экспериментального режима.' if ru else 'Fictional event in experimental mode.'
    return '%s%s %s %s' % (prefix, headline, effect, fiction)


def news_ru(news):
    if getattr(news, 'source', None) == 'ai_generated':
        return gm_news_text(news, True)
    actor, target = country_name(news.actor.id), country_name(news.target.id)
    if news.action == WORLD_EVENT:
        key = historical_key(news)
        if key in HISTORY_RU:
            title, text = HISTORY_RU[key]
            if key == "reykjavik" and "Nothing is agreed" in news.text:
                text = _REYKJAVIK_FAILURE
            return "%s. %s" % (title, text)
        return "Историческое событие: %s — %s." % (actor, target)
    if news.actor.id == news.target.id:
        if news.action == 1:
            return "%s: революция. Повстанцы свергли правительство и пришли к власти." % actor
        if news.action == 2:
            return "%s: государственный переворот. Руководство страны сменилось." % actor
        return "%s: внутренние события." % actor
    if news.target.id < 2 and news.action == 0:
        return "%s меняет внешнеполитический курс в пользу стороны «%s» (финляндизация)." % (actor, target)
    if news.actor.id >= 2 and news.target.id >= 2 and news.action == 6:
        return ("%s капитулирует перед стороной «%s»." if news.old == 2 else "%s продолжает войну со стороной «%s».") % (actor, target)
    if 0 <= news.action <= 8:
        verb = "повышает уровень" if news.new > news.old else ("снижает уровень" if news.new < news.old else "сохраняет уровень")
        return "%s — %s. %s %s политики «%s»: %s → %s." % (
            actor, target, actor, verb, POLICIES_RU[news.action], step_ru(news.action, news.old), step_ru(news.action, news.new))
    return "%s — %s: международное событие." % (actor, target)


_REASONS = {
    "A treaty or trade level cannot be lowered.": "Уровень договора или торговли нельзя снизить по собственной инициативе.",
    "Their government won't accept more economic aid (not enough goodwill).": "Правительство не примет больше экономической помощи: отношения недостаточно хорошие.",
    "Not enough economic aid budget for a higher step.": "Для следующего уровня недостаточно бюджета экономической помощи.",
    "Their government won't accept more military aid (not enough goodwill).": "Правительство не примет больше военной помощи: отношения недостаточно хорошие.",
    "Not enough military aid budget: a higher step needs its full cost free, the aid already given is not counted.": "Не хватает бюджета военной помощи: для повышения нужна вся стоимость нового уровня свободными средствами; уже выделенная помощь не засчитывается.",
    "The insurgents are too weak to be worth arming.": "Повстанцы слишком слабы; соотношение сил ограничивает объём помощи.",
    "No staging area: you need troops in a neighbouring country to arm these insurgents further.": "Нет базы снабжения: для увеличения помощи повстанцам нужны войска в соседней стране.",
    "Treaty level too low for more troops.": "Уровень договора слишком низок для увеличения контингента.",
    "Their government won't accept more troops.": "Правительство не примет больше войск.",
    "No staging area: you need troops in a neighbouring country to send more troops for the rebels.": "Нет базы снабжения: для отправки дополнительных войск повстанцам нужны войска в соседней стране.",
    "Their government won't accept a closer treaty (not enough goodwill).": "Правительство не примет более тесный договор: отношения недостаточно хорошие.",
    "Their government won't accept closer trade (not enough goodwill).": "Правительство не согласится расширить торговлю: отношения недостаточно хорошие.",
}


def reason_ru(reason):
    if not reason:
        return ""
    if reason in _REASONS:
        return _REASONS[reason]
    match = re.fullmatch(r"Not enough troops left \((-?\d+) thousand free\); a higher step needs its full number free\.", reason)
    if match:
        return "Не хватает свободных войск (%s тыс.): для повышения нужен весь контингент нового уровня." % match.group(1)
    return "Действие ограничено правилами текущей ситуации."


def reaction_ru(world, event):
    crisis, news = world.crisis, world.crisis.whichHead
    if world.NWFlag or world.ANWFlag:
        return "Кризис привёл к ядерной войне. Игра завершена для обеих сторон."
    if news is None:
        return ""
    event = event or {}
    speaker = country_name(event.get("speaker", world.cmptr))
    outcome = event.get("outcome", "current_step")
    if outcome == "backed_down" or crisis.backDown or not crisis.hasBegun:
        table = ("destab", "econAid", "govtAid", "insgAid", "govtIntv", "insgIntv", "pressure", "treaty", "trade")[news.action]
        held = getattr(news.actor, table)[news.target.id]
        policy = "Спорное изменение политики отменено." if held == min(news.old, news.new) else "Спорная политика сохраняется."
        return "Сторона «%s» отступила. %s Продолжите ход." % (speaker, policy)
    if outcome == "restored":
        return "Кризис восстановлен на ступени %d. Ни одна сторона ещё не приняла нового решения." % crisis.level
    if outcome == "challenge":
        return "Сторона «%s» оспаривает политику стороны «%s». Выберите ответ на возражение." % (speaker, country_name(news.actor.id))
    return "Сторона «%s» настаивает на своей позиции. Кризис перешёл на ступень %d; дальнейшая эскалация повышает ставки." % (speaker, crisis.level)


# Same order as the core's 32-entry Local.ADVISORY table. These are opinions,
# not predictions that an opponent must actually concede or that war is safe.
_ADVISORY_RU = (
    "Они нас разгромят в этом споре!", "В этом вопросе преимущество полностью на их стороне.",
    "Откажитесь от спора: положение безнадёжно.", "Лучше не затрагивать этот вопрос.",
    "Они загнали нас в угол.", "Отступите.", "Этот вопрос решается в их пользу.",
    "У нас нет убедительных оснований для спора.", "Не в этот раз.", "Мы не сможем выиграть этот спор.",
    "Они не отступят.", "Это не стоит конфликта.", "Не думаю, что мы сможем победить.",
    "Я предпочёл бы избежать этого конфликта.", "Это довольно рискованно.",
    "Здесь можно выбрать любой из двух путей.", "Здесь очень трудно выбрать верное решение.",
    "Возможно, стоит попробовать.", "Думаю, мы можем выиграть этот спор.", "Не бойтесь.",
    "Думаю, нам стоит действовать.", "Мы можем выиграть этот спор.", "Они отступят.",
    "В этом вопросе они переходят границы.", "Твёрдо стойте на своём.", "Мы загнали их в угол.",
    "На этот раз они серьёзно ошиблись.", "Этот вопрос решается в нашу пользу.",
    "Не позволяйте им уйти от ответа.", "Решительно выступите против них.",
    "Дайте им отпор!", "Нанесите ядерный удар!",
)


def crisis_advice_ru(world, panel, verdicts):
    """Translate actual core verdicts and attach only player-visible facts.

    The caller computes verdicts on its detached world. Never rerun importance
    calculations here: they overwrite the crisis's scratch values in the core.
    """
    crisis, news = world.crisis, world.crisis.whichHead
    if news is None:
        return []
    originals = Local.strings[Local.ADVISORY]
    translated = [_ADVISORY_RU[originals.index(text)] for text in verdicts]
    resolved = crisis.backDown or not crisis.hasBegun or world.NWFlag or world.ANWFlag
    if world.NWFlag or world.ANWFlag:
        return ["Ядерная война завершила игру; дальнейших решений в кризисе нет. "
                "Оценка исходного спора советником: «%s»" % text for text in translated]
    if resolved:
        return ["Кризис завершён; это оценка сообщения после развязки, а не предложение продолжить эскалацию: «%s» %s"
                % (text, reaction_ru(world, panel.get("dialogue"))) for text in translated]
    policy_table = ("destab", "econAid", "govtAid", "insgAid", "govtIntv", "insgIntv", "pressure", "treaty", "trade")
    held = getattr(news.actor, policy_table[news.action])[news.target.id]
    actor, target = country_name(news.actor.id), country_name(news.target.id)
    is_superpower = news.actor.id < 2
    details = [
        "Спор: %s — %s, политика «%s», %s → %s. Наша сторона %s."
        % (actor, target, POLICIES_RU[news.action], step_ru(news.action, news.old),
           step_ru(news.action, news.new), "защищает своё изменение" if news.actor.id == world.human else "оспаривает чужое изменение"),
        ("Ступень %d. Показанная цена нашего отступления: %s очков престижа; это оценка, а не вероятность войны."
         % (crisis.level, panel["risk"][0]))
        if panel["risk"][0] and is_superpower else "Текущая ступень кризиса: %d." % crisis.level,
        "Сейчас у стороны «%s» в стране «%s» действует: %s — %s. Отношение этой страны к нам: %+d."
        % (actor, target, POLICIES_RU[news.action], step_ru(news.action, held), news.target.diplOpinion[world.human]),
        ("При эскалации к ступеням 4–2 возможна случайная ядерная война, если отношения сверхдержав враждебны; ступень 1 означает ядерную войну."
         if is_superpower else "Это спор с малой страной: её собственная эскалация не приводит к ядерной войне."),
    ]
    return ["Оценка советника по правилам: «%s» %s Это мнение, а не гарантия ответа соперника." % (text, detail)
            for text, detail in zip(translated, details)]


def model_status(code, language):
    """Public availability categories; never include raw provider failures."""
    messages = {
        "training": ("Offline training; rules-based response", "Обучение без модели; ответ по правилам"),
        "disabled": ("AI advisors disabled in settings; rules-based response", "Советники ИИ выключены в настройках; ответ по правилам"),
        "offline": ("Offline model mode selected; rules-based response", "Выбран автономный режим модели; ответ по правилам"),
        "unconfigured": ("Text model not configured; rules-based response", "Текстовая модель не настроена; ответ по правилам"),
        "failed": ("Model request unavailable or invalid; rules-based response", "Запрос к модели недоступен или ответ некорректен; ответ по правилам"),
        "ready": ("Model-generated response", "Ответ языковой модели"),
    }
    return messages[code][language == "ru"]


_ERRORS = {
    "gamemaster_unavailable": "Экспериментальный ведущий доступен только в одиночной кампании.",
    "gamemaster_disabled": "Сначала включите экспериментального ведущего ИИ.",
    "invalid_request": "Некорректный запрос к игре.", "invalid_argument": "Некорректный параметр действия.",
    "mode_unavailable": "Этот режим карты недоступен на текущем уровне сложности.",
    "duplicate_id": "Номер запроса уже использован для другого действия.",
    "request_in_progress": "Это действие уже выполняется.",
    "stale_revision": "Положение изменилось. Обновите данные и повторите действие.",
    "turn_in_progress": "Соперник завершает расчёт текущего действия.",
    "tutorial_active": "Сначала вернитесь из обучения в основную игру; затем можно сохранять, загружать или начинать новую партию.",
    "stale_simulation": "Положение изменилось; запоздавший ответ соперника отброшен.",
    "stale_advice": "Положение изменилось, пока советник готовил ответ. Задайте вопрос снова.",
    "no_game": "Сначала начните или загрузите игру.", "game_ended": "Эта игра завершена.",
    "crisis_active": "Сначала разрешите текущий кризис.",
    "illegal_policy": "Этот уровень политики недоступен: проверьте отношения, бюджет и другие ограничения.",
    "not_questionable": "Это сообщение нельзя оспорить.", "no_crisis": "Сейчас нет незавершённого кризиса.",
    "illegal_choice": "Выберите один из доступных ответов в кризисе.",
    "invalid_slot": "В прототипе доступен только слот «prototype».",
    "unsupported_save": "Этот файл сохранения не поддерживается прототипом.",
    "save_error": "Не удалось прочитать или записать локальное сохранение.",
    "unknown_command": "Неизвестное действие.",
    "command_failed": "Не удалось выполнить действие; игровая позиция сохранена.",
}


def error_ru(code):
    return _ERRORS.get(code, "Не удалось выполнить действие.")
