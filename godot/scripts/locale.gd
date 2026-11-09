extends RefCounted

static var language := "en"
static var names: Array = []
const RU_COUNTRIES = ["США", "СССР", "Мексика", "Гондурас", "Никарагуа", "Панама", "Куба", "Аргентина", "Колумбия", "Перу", "Венесуэла", "Бразилия", "Чили", "Канада", "Греция", "Швеция", "Великобритания", "Франция", "Испания", "ФРГ", "Румыния", "Италия", "ГДР", "Польша", "Чехословакия", "Югославия", "ЮАР", "Египет", "Тунис", "Марокко", "Алжир", "Ливия", "Мали", "Нигерия", "Судан", "Эфиопия", "Кения", "Заир", "Танзания", "Мозамбик", "Замбия", "Ангола", "Япония", "КНДР", "Южная Корея", "Австралия", "Китай", "Вьетнам", "Турция", "Сирия", "Израиль", "Тайвань", "Ирак", "Саудовская Аравия", "Иран", "Афганистан", "Пакистан", "Индия", "Бирма", "Таиланд", "Индонезия", "Филиппины", "Гватемала", "Сальвадор", "Коста-Рика", "Мавритания", "Гвинея", "Кот-д’Ивуар", "Буркина-Фасо", "Гана", "Нигер", "Чад", "Камерун", "Центральная Африка", "Конго", "Зимбабве", "Ботсвана", "Иордания", "Ливан", "Боливия"]
const POLICIES_EN = ["Destabilization", "Economic aid", "Military aid", "Aid to insurgents", "Government intervention", "Rebel intervention", "Diplomatic pressure", "Treaty", "Trade"]
const POLICIES_RU = ["Дестабилизация", "Экономическая помощь", "Военная помощь", "Помощь повстанцам", "Войска на стороне власти", "Войска на стороне повстанцев", "Дипломатическое давление", "Договор", "Торговля"]
const STRINGS = {
 "title": ["Balance of Power", "Баланс сил"],
 "scores": ["Scores", "Счёт"], "objectives": ["Objectives", "Обязательства"],
 "ai_settings": ["AI settings", "Настройки ИИ"],
 "country_report": ["Country details", "Сведения о стране"],
 "report_changed": ["The position changed. Close and reopen this report.", "Обстановка изменилась. Закройте и снова откройте этот отчёт."],
 "year_delta": ["Last year", "За последний год"],
 "objective_bonus": ["Commitment bonus", "Бонус обязательств"],
 "score_history": ["Prestige through the years", "Престиж по годам"],
 "score_explanation": ["The score is prestige gained since the start. Commitments have a separate standing bonus: it holds only while their conditions remain true.", "Счёт отражает прирост престижа с начала игры. Обязательства дают отдельный бонус: он действует лишь пока выполняются условия."],
 "objectives_help": ["These are continuing commitments. Meeting a condition earns its bonus; losing it removes that bonus.", "Это постоянные обязательства. Выполнение условия даёт бонус; при нарушении условия бонус пропадает."],
 "reward": ["Points", "Очки"], "current_position": ["Current position", "Текущее положение"],
 "indicator": ["Indicator", "Показатель"], "value": ["Value", "Значение"],
 "history": ["History", "История"], "year": ["Year", "Год"],
 "country_profile": ["Country profile", "Справка"], "map_perspective": ["Perspective", "Относительно страны"],
 "subtitle": ["The Cold War, 1982–1990", "Холодная война, 1982–1990"],
 "new": ["New game", "Новая игра"], "save": ["Save", "Сохранить"], "load": ["Load", "Загрузить"],
 "learn": ["Learn to play", "Учиться играть"], "end": ["End the year", "Завершить год"],
 "advisor": ["Ask an advisor", "Спросить советника"], "news": ["Dispatches", "Донесения"],
 "policies": ["Commitments", "Обязательства"], "apply": ["Apply policy", "Применить"],
 "relations": ["Their opinion of us", "Их отношение к нам"], "outgoing": ["Our opinion of them", "Наше отношение к ним"],
 "prestige": ["Prestige value", "Вес в престиже"], "credibility": ["Credibility", "Авторитет"],
 "tension": ["Tension estimate", "Оценка напряжённости"], "score": ["Score change", "Изменение счёта"],
 "select": ["Select a country on the map", "Выберите страну на карте"],
 "map_rel": ["Relations", "Отношения"], "map_value": ["Prestige", "Престиж"],
 "map_hint": ["Wheel: zoom   •   Middle-drag: pan   •   Arrows: select", "Колесо: масштаб   •   Средняя кнопка: перемещение   •   Стрелки: выбор"],
 "reset_map": ["Fit map", "Вся карта"], "opposed": ["Opposed", "Враждебность"], "aligned": ["Aligned", "Дружба"],
 "ready": ["Ready", "Готово"], "working": ["Resolving…", "Расчёт…"], "connect": ["Connecting to the simulation…", "Подключение к симуляции…"],
 "connection_error": ["Could not reach the game. Start with tools/run_godot.py.", "Нет связи с игрой. Запустите tools/run_godot.py."],
 "saved": ["Game saved in the prototype slot.", "Игра сохранена в слот прототипа."],
 "quiet": ["No dispatches yet. Choose a commitment, then end the year.", "Донесений пока нет. Выберите политику и завершите год."],
 "challenge": ["Question this move", "Оспорить действие"], "crisis": ["Diplomatic crisis", "Дипломатический кризис"],
 "tough": ["Stand firm", "Стоять на своём"], "loose": ["Back down", "Отступить"], "continue": ["Continue", "Продолжить"],
 "rung": ["Crisis rung", "Ступень кризиса"], "risk": ["Prestige at risk", "Престиж под угрозой"],
 "crisis_note": ["Escalation can cost more than the policy is worth. Nuclear war ends the game for both sides.", "Эскалация может стоить дороже спорной политики. Ядерная война завершает игру для обеих сторон."],
 "briefing": ["Request crisis briefing", "Запросить разбор кризиса"],
 "advisor_prompt": ["What are the tradeoffs of this policy?", "Каковы выгоды и риски этой политики?"],
 "ask": ["Ask", "Спросить"], "close": ["Close", "Закрыть"],
 "thinking": ["The advisor is considering the position…", "Советник изучает обстановку…"],
 "offline": ["Rules-based advice", "Совет на основе правил"], "model": ["Model-generated advice", "Ответ языковой модели"],
 "music": ["Music", "Музыка"], "motion": ["Reduced motion", "Меньше анимации"],
 "credits": ["Credits", "Авторы"], "side": ["Your side", "Ваша сторона"], "difficulty": ["Difficulty", "Сложность"],
 "start": ["Start game", "Начать игру"], "cancel": ["Cancel", "Отмена"],
 "beginner": ["Beginner", "Начальный"], "intermediate": ["Intermediate", "Средний"], "expert": ["Expert", "Эксперт"],
 "multipolar": ["Multipolar", "Многополярный"], "adaptive": ["Adaptive (LLM)", "Адаптивный (LLM)"],
 "superpower": ["Select a minor country to make a commitment.", "Выберите малую страну для изменения политики."],
 "no_options": ["No legal changes at this difficulty.", "На этом уровне сложности изменения недоступны."],
 "held": ["Current", "Сейчас"], "available": ["Available", "Доступно"],
 "complete": ["Game over", "Игра завершена"], "ack": ["Understood", "Понятно"],
 "intelligence": ["Intelligence", "Разведка"],
 "intelligence_help": ["Intelligence draws from the military aid budget. Higher levels narrow uncertainty, but never remove it. The new estimate arrives with the next year.", "Разведка расходует бюджет военной помощи. Более высокий уровень уменьшает неопределённость, но не устраняет её. Новая оценка поступит в следующем году."],
 "nuclear_end": ["Nuclear war. Neither side wins; prestige no longer matters.", "Ядерная война. Победителей нет; престиж больше не имеет значения."],
 "winner": ["Higher prestige growth: ", "Больший прирост престижа: "], "draw": ["Equal prestige growth.", "Прирост престижа равен."],
 "end_note": ["The campaign is over. You can inspect the final position or start a new game.", "Партия завершена. Можно изучить итоговую обстановку или начать новую игру."],
 "opponent_heuristic": ["built-in strategy", "встроенная стратегия"],
 "opponent_heuristic_not_configured": ["built-in strategy; model not configured", "встроенная стратегия; модель не настроена"],
 "opponent_heuristic_model_unavailable": ["built-in strategy; model unavailable", "встроенная стратегия; модель недоступна"],
 "opponent_heuristic_fallback": ["built-in strategy; model response failed", "встроенная стратегия; ошибка ответа модели"],
 "opponent_offline": ["offline strategy", "автономная стратегия"],
 "opponent_model": ["language model", "языковая модель"],
 "opponent_llm": ["language model", "языковая модель"],
 "lesson": ["Field guide", "Учебный режим"], "skip": ["Skip guide", "Скрыть обучение"], "restart": ["Restart guide", "Сначала"],
 "return_campaign": ["Return to campaign", "Вернуться к партии"],
 "training_status": ["Training session: your campaign is preserved. Advisor replies use game rules.", "Учебная партия: ваша основная игра сохранена. Советник объясняет правила без LLM."],
 "lesson_0": ["1. Influence, not conquest\nSelect a minor country. Its opinion of you contributes to prestige; its weight tells you how much it matters.", "1. Влияние, а не захват\nВыберите малую страну. Её отношение к вам влияет на престиж; вес страны определяет значимость этого влияния."],
 "lesson_1": ["2. Read the relationship\nCompare ‘Their opinion of us’ with ‘Our opinion of them’. These are different numbers. The former contributes to your score.", "2. Читайте отношения\nСравните «Их отношение к нам» и «Наше отношение к ним». Это разные величины. В счёте учитывается первая."],
 "lesson_2": ["3. Make a commitment\nOpen a policy, read the legal steps, and apply a change. Aid and troops remain committed across years. A greyed-out step has a rule behind it.", "3. Примите обязательство\nОткройте политику, изучите доступные уровни и примените изменение. Помощь и войска сохраняются между ходами. Недоступные уровни ограничены правилами."],
 "lesson_3": ["4. Let a year pass\nEnd the year. Domestic events, both powers and your existing commitments shape the result. If a crisis opens, resolve it before the year can finish.", "4. Проживите год\nЗавершите год. На результат влияют внутренние события, обе сверхдержавы и ваши обязательства. Если возникнет кризис, сначала разрешите его."],
 "lesson_4": ["5. Compare intentions with results\nRead a dispatch and select a country again. Changes can have several causes. A crisis starts with a challenge; standing firm raises the stakes, retreat can reverse a policy.", "5. Сравните замысел и результат\nПрочитайте донесение и снова выберите страну. У изменений бывает несколько причин. Кризис начинается с оспаривания: упорство повышает ставки, отступление может отменить политику."],
 "lesson_5": ["6. Consult, then decide\nAsk an advisor about the selected country. Advisors weigh relations, commitments, influence and resolve differently. Recommendations are not guaranteed outcomes.", "6. Советуйтесь и решайте\nЗадайте советнику вопрос о выбранной стране. Советники по-разному оценивают отношения, обязательства, влияние и решимость. Рекомендация не гарантирует результат."],
 "lesson_done": ["Guide complete. Build influence, watch your commitments, and keep a route out of every crisis. You can reopen this guide at any time.", "Обучение пройдено. Укрепляйте влияние, следите за обязательствами и оставляйте выход из каждого кризиса. Этот разбор можно открыть снова."],
 "guide_live": ["The learning session is separate from your campaign and works offline.", "Учебная партия отделена от основной игры и работает без подключения к LLM."],
 "credits_text": ["Original design: Chris Crawford (1985/1988). Python port: Tomasz Ciborski. This fork: Vasilii Vinogradov.\n\nGodot Engine is MIT licensed: godotengine.org/license\nAdvisor photo credits are in assets/advisors/ATTRIBUTION.md.\nThe three original synthesized themes are generated by this project's Music.py.\n\nThis is the desktop engine prototype. Multiplayer and the full legacy screen set remain in the Python application.", "Оригинальная игра: Крис Кроуфорд (1985/1988). Порт на Python: Томаш Циборски. Эта версия: Василий Виноградов.\n\nGodot Engine: лицензия MIT, godotengine.org/license\nИсточники портретов: assets/advisors/ATTRIBUTION.md.\nТри синтезированные темы создаёт Music.py этого проекта.\n\nЭто прототип на новом движке. Сетевая игра и полный набор прежних экранов пока доступны в приложении на Python."]
}

static func text(key: String) -> String:
 var entry: Array = STRINGS.get(key, [key, key])
 return entry[1 if language == "ru" else 0]

static func country(id: int) -> String:
 if id < 0 or id >= 80:
  return "?"
 if language == "ru":
  return RU_COUNTRIES[id]
 if names.is_empty():
  names = JSON.parse_string(FileAccess.get_file_as_string("res://assets/countries.json"))
 return names[id].name

static func policy(action: int) -> String:
 if action < 0 or action > 8:
  return ""
 return POLICIES_RU[action] if language == "ru" else POLICIES_EN[action]

static func step(action: int, value: int) -> String:
 var ru := language == "ru"
 if action in [1, 2, 3]:
  var amounts := [0, 20, 100, 400, 1000, 2000]
  if action == 1:
   amounts = [0, 200, 400, 1000, 2000, 4000]
  return "$%s %s" % [amounts[clampi(value, 0, 5)], "млн/год" if ru else "m/year"]
 if action in [4, 5]:
  return "%s %s" % [[0, 1, 5, 20, 100, 500][clampi(value, 0, 5)], "тыс. военных" if ru else "thousand troops"]
 var labels := ["None", "Low", "Limited", "Moderate", "Strong", "Maximum"]
 if ru:
  labels = ["Нет", "Низкий", "Ограниченный", "Средний", "Сильный", "Максимальный"]
 if action == 7:
  labels = ["No relations", "Diplomatic relations", "Trade relations", "Military bases", "Conventional defense", "Nuclear defense"] if not ru else ["Нет отношений", "Дипотношения", "Торговые отношения", "Военные базы", "Обычная оборона", "Ядерная оборона"]
 elif action == 0:
  labels = ["No activity", "Help dissidents", "Fund opposition", "Incite riots", "Assassinations", "Support coup"] if not ru else ["Нет активности", "Помощь диссидентам", "Финансирование оппозиции", "Разжигание беспорядков", "Убийства", "Поддержка переворота"]
 elif action == 6:
  labels = ["None", "Quiet diplomacy", "Public posturing", "Moderate pressure", "Intense pressure", "Diplomatic offensive"] if not ru else ["Нет", "Тихая дипломатия", "Публичные заявления", "Умеренное давление", "Сильное давление", "Дипломатическое наступление"]
 elif action == 8:
  labels = ["No trade", "Trade talks", "Limited trade", "Trade agreement", "Preferential trade", "Full trade partnership"] if not ru else ["Нет торговли", "Торговые переговоры", "Ограниченная торговля", "Торговое соглашение", "Льготная торговля", "Полное торговое партнёрство"]
 return labels[clampi(value, 0, 5)]
