extends RefCounted

const L = preload("res://scripts/locale.gd")

static func show(host) -> void:
 var ru := L.language == "ru"
 var column: VBoxContainer = host._dialog("Руководство" if ru else "Field manual", Vector2i(860, 670))
 var tabs := TabContainer.new()
 tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
 tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 column.add_child(tabs)
 var titles := ["Цель и счёт", "Политика", "Кризисы", "Уровни", "Управление", "Игра вдвоём", "Авторы"] if ru else ["Goal & score", "Policies", "Crises", "Levels", "Controls", "Two players", "Credits"]
 var bodies := RU if ru else EN
 for index in range(titles.size()):
  var page := RichTextLabel.new()
  page.name = titles[index]
  page.bbcode_enabled = true
  page.scroll_active = true
  page.selection_enabled = true
  page.add_theme_font_size_override("normal_font_size", 17)
  page.add_theme_color_override("default_color", host.PAPER)
  page.add_theme_constant_override("line_separation", 5)
  page.text = bodies[index]
  tabs.add_child(page)
 var owner: Window = host.popup
 var close: Button = host._button(L.text("close"), func(): owner.hide(); owner.exclusive = false; owner.queue_free())
 column.add_child(close)

const EN = [
"""[font_size=23][color=#eddaa8]Prestige, not territory[/color][/font_size]

Lead the United States or Soviet Union through the Cold War, from the 1982 baseline to the 1990 ending. Your score measures the [b]increase[/b] in geopolitical prestige since the baseline, rather than territory or your current total influence.

[b]Prestige total = Σ (each minor country's opinion of you × its prestige value) ÷ 1024.[/b]

The sum covers the 78 minor countries. Neither superpower contributes to it; the other superpower's opinion of you is not a scoring term. Your displayed score compares this total with its starting value.

A country's prestige value combines military spending and military manpower. A rich microstate or a large but poor country can therefore carry little weight. Use the Prestige map indicator to compare countries. Helping a government generally improves its opinion; attacking it generally worsens it.

[color=#eddaa8][b]Standing objectives[/b][/color]

Objectives add separate, continuing bonuses. A bonus holds while its condition remains true; losing the condition removes it. Review Objectives to see the actual conditions and current standing. These are commitments to maintain, rather than points permanently collected on completion.

The higher score wins at the 1990 ending. [b]Nuclear war means both sides lose, whatever their scores.[/b]""",
"""[font_size=23][color=#eddaa8]Nine instruments of policy[/color][/font_size]

[b]Military aid[/b] strengthens a government. The goodwill it buys depends on how much that government needs your help.

[b]Aid to insurgents[/b] strengthens rebels. It is highly provocative relative to its cost.

[b]Government intervention[/b] sends your troops to fight for the government. Opposing interventions can bring the superpowers' troops together and increase nuclear danger.

[b]Rebel intervention[/b] sends your troops to fight for insurgents. This is the most provocative instrument.

[b]Economic aid[/b] transfers money from your GNP to the recipient's. It reduces coup risk and matters much more to a poor country than a rich one.

[b]Destabilization[/b] is covert action intended to provoke a coup. It lapses each year.

[b]Diplomatic pressure[/b] intimidates a country towards Finlandization—accommodation to a threatening power—and makes it spend more on its army. It also lapses each year.

[b]Treaty[/b] is a graded commitment to a client. Higher steps bind you more strongly. You cannot reduce your treaty yourself; the client can. Losing a treaty weakens your other treaty commitments.

[b]Trade[/b] is a diplomatic statement with no economic effect. It is available at Multipolar level and above.

[color=#eddaa8][b]Six policy steps[/b][/color]

Policies have steps 0–5. Step 0 means none or repeal, where repeal is permitted. Aid and intervention are annual commitments: they persist until changed. Destabilization and pressure must be renewed each year.

[table=4]
[cell][b]Step[/b][/cell][cell][b]Economic aid[/b][/cell][cell][b]Arms aid*[/b][/cell][cell][b]Troops[/b][/cell]
[cell]0[/cell][cell]0[/cell][cell]0[/cell][cell]0[/cell]
[cell]1[/cell][cell]$0.2 bn[/cell][cell]$20 m[/cell][cell]1,000[/cell]
[cell]2[/cell][cell]$0.4 bn[/cell][cell]$100 m[/cell][cell]5,000[/cell]
[cell]3[/cell][cell]$1 bn[/cell][cell]$400 m[/cell][cell]20,000[/cell]
[cell]4[/cell][cell]$2 bn[/cell][cell]$1 bn[/cell][cell]100,000[/cell]
[cell]5[/cell][cell]$4 bn[/cell][cell]$2 bn[/cell][cell]500,000[/cell]
[/table]
* Military aid and aid to insurgents; money is per year.

[color=#eddaa8][b]Why a step is unavailable[/b][/color]

[b]Relations:[/b] a government will not accept unlimited help from a power it distrusts. Improve goodwill first.

[b]Resources:[/b] aid and troops share finite budgets across all recipients. Arms aid comes out of military spending; intervention ties up military manpower. Intelligence spending leaves less available for aid.

[b]Staging areas:[/b] rebel aid and intervention depend on troops supporting a government in a contiguous country. The staging ceiling is one step above the highest government intervention next door. Without a staging area, at most step 1 of rebel arms aid and step 2 of rebel intervention are possible. A superpower's own contiguous territory also matters.

[b]Local balance:[/b] you cannot freely arm a rebellion already being defeated. A strong government relative to its insurgents lowers the permitted aid step.

The policy dialog shows the current commitment, legal choices and the reason for its limit. Use those current limits rather than assuming that a theoretical maximum is available.""",
"""[font_size=23][color=#eddaa8]Decisions under pressure[/color][/font_size]

A superpower may contest the other's policy move. Its willingness depends on relations with the country, treaties, spheres of influence and its appetite for risk. In Dispatches, a challenge button identifies a move you can contest.

[b]The crisis ladder runs from rung 9, the safest, down to rung 1.[/b] Each side can stand firm or back down when it is their decision. Standing firm advances the confrontation and makes retreat more costly.

[b]Rungs 9–7:[/b] back channels. [b]Retreat is free at 9 and 8.[/b] A prestige penalty begins at rung 7.

[b]Rungs 6–5:[/b] public diplomatic crisis; prestige is at stake.

[b]Rungs 4–2:[/b] DEFCON 4, 3 and 2. [b]Accidental launch risk begins at rung 4.[/b] It is zero while superpower relations are friendly and rises as they deteriorate.

[b]Rung 1:[/b] DEFCON 1. Nuclear war; neither side wins.

[color=#eddaa8][b]The price of retreat[/b][/color]

From rung 7 down, backing down costs prestige according to how far the crisis has escalated. Every minor country's opinion shifts towards the winner, not just the disputed country's. A large disputed intervention can make one retreat cost thousands of points and damage your ability to offer aid later.

Read [b]Prestige at risk[/b] before deciding. The same rule applies in two-player games. If the power that made the original move retreats, that move is reversed: aid is withdrawn or troops return. If the challenger retreats, the move remains.

[color=#eddaa8][b]Summits in two-player games[/b][/color]

Each side may propose one summit per crisis during escalation. The proposal counts as the proposer's acceptance; the other side answers. Acceptance leaves the disputed move in force, de-escalates the crisis by one rung and ends it without loss of face. Refusal costs the refuser credibility and returns the decision to the proposer.

The four advisors emphasise relations, treaty obligations, influence and resolve differently. Disagreement is expected. Their explanations do not replace the mechanical consequences of your decision.""",
"""[font_size=23][color=#eddaa8]Five levels of complexity[/color][/font_size]

[b]Beginner[/b] offers military aid, aid to insurgents and both forms of intervention. The world is relatively predictable.

[b]Intermediate[/b] adds economic aid and destabilization, with coups modelled.

[b]Expert[/b] adds treaties and diplomatic pressure, with Finlandization modelled.

[b]Multipolar[/b] adds trade. All 78 minor countries pursue foreign policies of their own and can fight each other, drawing the superpowers into their conflicts.

[b]Adaptive[/b] uses the Multipolar rules with a language-model opponent. Configure its endpoint, model and credentials in AI settings. If unavailable, play falls back visibly to the built-in opponent. Model replies cannot bypass legal policy limits.

Higher levels randomise the opening world more strongly. A country's opening position therefore need not remain the same across campaigns.

[color=#eddaa8][b]Intelligence and uncertainty[/b][/color]

The displayed world tension is an estimate, not the hidden true value. Its error can be about a quarter of the scale. Buying intelligence narrows that uncertainty and uses resources that could otherwise support aid. Open Intelligence through Settings to review the allocation and available resources.

AI settings separately control advisor/opponent models, budgets, timeouts and offline use. Reading or saving settings does not contact a provider. Test connection explicitly contacts the configured service. Offline advice remains available as rules-based guidance.""",
"""[font_size=23][color=#eddaa8]Your map room[/color][/font_size]

[b]Menu[/b] opens the campaign menu. Start a New game, Continue the last saved campaign, open Load, learn the rules, configure Settings or enter Multiplayer. A normal launch waits here until you choose what to do.

[b]Select a country[/b] with a left click on the map. Its drawer shows relations, prestige and available policies. Select a policy, choose a legal step and press Apply. Country details opens its report and history. Close the drawer to recover the full map.

[b]Explore the map[/b] with the wheel or +/− to zoom and the middle mouse button to pan. Double-click a country to focus it; F or Fit map restores the whole view. Arrow keys change country selection. Layers controls city miniatures, terrain relief, conflicts and aid/trade connections. Click a city to open the country, an event marker to read its briefing, or a connection to inspect the policy. The world view highlights major developments; zoom in for minor unrest. City models and streets are illustrative country markers, not simulated city locations. Connections show policy commitments, not transport routes. Choose a map group and indicator to compare relations, policies or country statistics. Perspective-sensitive modes use the selected country.

[b]Dispatches[/b] opens the news drawer. Review events and challenge eligible opposing moves. Close or toggle the drawer to return to the map. A diplomatic crisis displays its available decisions in the country drawer.

[b]End the year[/b] advances the simulation after your decisions are ready. Resolve any pending crisis first. Scores and Objectives explain your campaign standing; Advisors opens advice and conversation records.

[b]Saves[/b] are named slots in the Load/saves window. Choose a slot to save or load; deleting a slot requires confirmation. Export writes a portable .bopg file, and Import opens one. Local Undo is available only when the current game supports it; it does not replace a named save.

[b]Learn to play[/b] starts an isolated training session with a prepared practice crisis. Follow its instructions and acknowledgement button. Return to campaign restores your original position, random stream and pending crisis. Saving, loading and replacing the campaign are blocked during training.

[b]Settings[/b] contains language, music and volume, track choice, reduced motion, map colour accessibility and model configuration. Changes in language update the interface. Reduced motion removes optional interface movement.""",
"""[font_size=23][color=#eddaa8]Two superpowers, two people[/color][/font_size]

Open [b]Multiplayer[/b] from Menu. Choose a mode before starting a campaign; the session panel shows connection state, whose move it is and available session actions.

[b]Hotseat[/b] shares one computer. Each player controls a superpower. Follow the displayed active side and pass/turn controls: both sides make their decisions within the same year before it advances. Pass the computer to the indicated player; do not treat a handover as a new year.

[b]LAN[/b] lets one player host and the other join using the host's address and port. The host owns the authoritative game. Start once the opponent has joined and the lobby permits it. Keep the host running throughout play. Use the session's chat for messages and its status to check connection progress.

[b]Play by mail[/b] uses turn files in a shared folder. Both players must refer to the same game identifier and choose their own side. Create the game or join the existing one, make your moves when it is your turn, then publish the turn. Refresh retrieves the partner's available turn. A local folder on different computers is not automatically shared: arrange file transfer or shared storage between the players.

The game checks imported state and turn lineage; wait for the session to accept a partner's turn before acting. An ordinary single-player save is not a replacement for the multiplayer session's turn files.

In two-player crises, use the displayed decision owner and available escalation, retreat and summit controls. The ordinary prestige and nuclear-risk rules still apply. Leave session when finished; do not close the host while the other player is relying on it.""",
"""[font_size=23][color=#eddaa8]Credits[/color][/font_size]

[b]Original design:[/b] Chris Crawford, 1985 and 1988; published by Mindscape. This game follows Balance of Power: The 1990 Edition.

[b]Python port:[/b] Tomasz Ciborski, 2020, adapting the original Pascal sources with Python and PyQt5.

[b]Fork author:[/b] Vasilii Vinogradov: model opponent, advisors, summits, intermediate objectives and network play.

The original Pascal sources were used to check the rules:
https://github.com/balance-of-power/bop2-pascal-source

The artwork comes from the original game. Advisor photographs come from Wikimedia Commons; individual credits are in img/advisors/ATTRIBUTION.md. Music credits are in music/ATTRIBUTION.md.

The desktop presentation uses Godot; the established Python simulation remains authoritative. Godot is distributed under the MIT licence. Bundled runtime licences and asset credits accompany standalone builds."""
]

const RU = [
"""[font_size=23][color=#eddaa8]Престиж, а не территория[/color][/font_size]

Возглавьте США или СССР в годы холодной войны: от исходного положения 1982 года до завершения партии в 1990 году. Счёт показывает [b]прирост[/b] геополитического престижа относительно начала, а не захваченную территорию или текущее суммарное влияние.

[b]Престиж = Σ (отношение каждой малой страны к вам × её вес в престиже) ÷ 1024.[/b]

Сумма охватывает 78 малых стран. Сами сверхдержавы в неё не входят; отношение другой сверхдержавы к вам также не является слагаемым. Игровой счёт сравнивает эту сумму с её исходным значением.

Вес страны в престиже определяется сочетанием военных расходов и численности вооружённых сил. Поэтому богатое микрогосударство или большая, но бедная страна могут иметь небольшой вес. Сравнить страны позволяет соответствующий показатель карты. Помощь правительству обычно улучшает его отношение, а действия против него ухудшают.

[color=#eddaa8][b]Постоянные обязательства[/b][/color]

Обязательства дают отдельные действующие бонусы. Бонус сохраняется, пока выполняется условие; нарушение условия убирает его. В окне Обязательства указаны конкретные условия и текущее положение. Это цели, которые нужно поддерживать, а не однажды полученные навсегда очки.

При завершении в 1990 году побеждает сторона с большим счётом. [b]Ядерная война означает поражение обеих сторон независимо от очков.[/b]""",
"""[font_size=23][color=#eddaa8]Девять инструментов политики[/color][/font_size]

[b]Военная помощь[/b] укрепляет правительство. Благодарность получателя зависит от того, насколько ему нужна ваша поддержка.

[b]Помощь повстанцам[/b] усиливает мятежников. По отношению к затратам это весьма провокационная мера.

[b]Войска на стороне власти[/b] сражаются за правительство. Встречное вмешательство сверхдержав может свести их войска в бою и повысить ядерную опасность.

[b]Войска на стороне повстанцев[/b] сражаются за мятежников. Это наиболее провокационный инструмент.

[b]Экономическая помощь[/b] передаёт часть вашего ВНП получателю. Она снижает вероятность переворота и гораздо значимее для бедной страны, чем для богатой.

[b]Дестабилизация[/b] — тайные действия с целью вызвать переворот. Её действие прекращается каждый год.

[b]Дипломатическое давление[/b] запугивает страну, подталкивая её к финляндизации — уступчивому отношению к угрожающей державе, — и заставляет больше тратить на армию. Давление также прекращается каждый год.

[b]Договор[/b] — обязательство перед клиентом с несколькими уровнями. Чем выше уровень, тем серьёзнее обязательство. Вы сами не можете понизить договор; клиент может. Потеря одного договора ослабляет остальные ваши договорные обязательства.

[b]Торговля[/b] служит дипломатическим заявлением и не даёт экономического эффекта. Доступна начиная с Многополярного уровня.

[color=#eddaa8][b]Шесть уровней политики[/b][/color]

У каждой меры есть уровни 0–5. Нулевой означает отсутствие или отмену там, где отмена разрешена. Помощь и вмешательство являются ежегодными обязательствами и сохраняются до изменения. Дестабилизацию и давление приходится возобновлять ежегодно.

[table=4]
[cell][b]Уровень[/b][/cell][cell][b]Экономика[/b][/cell][cell][b]Оружие*[/b][/cell][cell][b]Военные[/b][/cell]
[cell]0[/cell][cell]0[/cell][cell]0[/cell][cell]0[/cell]
[cell]1[/cell][cell]0,2 млрд $[/cell][cell]20 млн $[/cell][cell]1 000[/cell]
[cell]2[/cell][cell]0,4 млрд $[/cell][cell]100 млн $[/cell][cell]5 000[/cell]
[cell]3[/cell][cell]1 млрд $[/cell][cell]400 млн $[/cell][cell]20 000[/cell]
[cell]4[/cell][cell]2 млрд $[/cell][cell]1 млрд $[/cell][cell]100 000[/cell]
[cell]5[/cell][cell]4 млрд $[/cell][cell]2 млрд $[/cell][cell]500 000[/cell]
[/table]
* Военная помощь и помощь повстанцам; денежные суммы указаны за год.

[color=#eddaa8][b]Почему уровень недоступен[/b][/color]

[b]Отношения.[/b] Правительство не примет неограниченную помощь от державы, которой не доверяет. Сначала улучшите отношения.

[b]Ресурсы.[/b] Помощь и войска используют конечные бюджеты, общие для всех получателей. Поставки оружия расходуют военный бюджет, вмешательство связывает личный состав. Расходы на разведку уменьшают средства, доступные для помощи.

[b]Опорные базы.[/b] Помощь повстанцам и вмешательство на их стороне зависят от войск, поддерживающих правительство в соседней стране с общей границей. Предел — на один уровень выше наибольшего правительственного вмешательства по соседству. Без опорной базы возможны не более первого уровня оружия и второго уровня войск для повстанцев. Общая граница с самой сверхдержавой также учитывается.

[b]Соотношение сил.[/b] Нельзя неограниченно вооружать восстание, которое уже терпит поражение. Чем сильнее правительство относительно повстанцев, тем ниже допустимый уровень помощи.

Окно политики показывает текущее обязательство, допустимые варианты и причину ограничения. Ориентируйтесь на эти фактические пределы: теоретический максимум доступен не всегда.""",
"""[font_size=23][color=#eddaa8]Решения под давлением[/color][/font_size]

Сверхдержава может оспорить действие соперника. Её готовность зависит от отношений со страной, договоров, сфер влияния и склонности к риску. Кнопка в Донесениях показывает, какое действие можно оспорить.

[b]Лестница кризиса идёт от наиболее безопасной ступени 9 вниз к ступени 1.[/b] В свой момент решения сторона может стоять на своём или отступить. Твёрдая позиция продвигает противостояние дальше и повышает цену последующего отступления.

[b]Ступени 9–7:[/b] закрытые каналы. [b]Отступление бесплатно на ступенях 9 и 8.[/b] Потеря престижа начинается со ступени 7.

[b]Ступени 6–5:[/b] публичный дипломатический кризис; на кону престиж.

[b]Ступени 4–2:[/b] DEFCON 4, 3 и 2. [b]Риск случайного пуска появляется на ступени 4.[/b] При дружественных отношениях сверхдержав он равен нулю и растёт по мере ухудшения отношений.

[b]Ступень 1:[/b] DEFCON 1. Ядерная война; победителя нет.

[color=#eddaa8][b]Цена отступления[/b][/color]

Начиная со ступени 7, отступление отнимает престиж в зависимости от глубины эскалации. Отношение каждой малой страны сдвигается в пользу победителя, а не только отношение спорной страны. При крупном вмешательстве одно отступление может стоить тысяч очков и надолго испортить возможности предлагать помощь.

Перед решением прочитайте [b]Престиж под угрозой[/b]. Правило действует и в игре вдвоём. Если отступает сторона, совершившая первоначальное действие, оно отменяется: помощь отзывается, войска возвращаются. Если отступает оспаривающая сторона, действие сохраняется.

[color=#eddaa8][b]Саммиты в игре вдвоём[/b][/color]

Каждая сторона может один раз за кризис предложить саммит в фазе эскалации. Предложение уже означает согласие предлагающего; другая сторона отвечает. Согласие сохраняет спорное действие, снижает напряжение кризиса на одну ступень и завершает его без потери лица. Отказ снижает авторитет отказавшей стороны и возвращает решение инициатору.

Четыре советника по-разному оценивают отношения, договоры, влияние и решимость. Их разногласия закономерны. Объяснения советников не заменяют реальные последствия вашего решения.""",
"""[font_size=23][color=#eddaa8]Пять уровней сложности[/color][/font_size]

[b]Начальный[/b] включает военную помощь, помощь повстанцам и оба вида вмешательства. Мир относительно предсказуем.

[b]Средний[/b] добавляет экономическую помощь и дестабилизацию; моделируются перевороты.

[b]Экспертный[/b] добавляет договоры и дипломатическое давление; моделируется финляндизация.

[b]Многополярный[/b] добавляет торговлю. Все 78 малых стран ведут собственную внешнюю политику и могут воевать друг с другом, вовлекая сверхдержавы в конфликты.

[b]Адаптивный[/b] использует Многополярные правила с соперником на основе языковой модели. Адрес сервиса, модель и ключ задаются в Настройках ИИ. При недоступности модели игра явно сообщает о переходе к встроенному сопернику. Ответы модели не обходят допустимые пределы политики.

На более высоких уровнях начальный мир сильнее изменяется случайным образом. Поэтому положение одной страны в начале разных кампаний может различаться.

[color=#eddaa8][b]Разведка и неопределённость[/b][/color]

Показываемая мировая напряжённость — оценка, а не скрытое истинное значение. Погрешность может достигать примерно четверти шкалы. Разведка уменьшает неопределённость, но расходует средства, которые иначе можно было бы направить на помощь. Откройте Разведку через Настройки, чтобы проверить выделение ресурсов.

Настройки ИИ отдельно задают модели советников и соперника, бюджеты, тайм-ауты и автономный режим. Чтение и сохранение настроек не обращается к провайдеру. Проверка соединения явно связывается с выбранным сервисом. Без сети остаются советы на основе правил игры.""",
"""[font_size=23][color=#eddaa8]Ваш командный пункт[/color][/font_size]

[b]Меню[/b] открывает меню кампании. Здесь можно начать Новую игру, Продолжить последнее сохранение, открыть Загрузку, пройти обучение, изменить Настройки или выбрать Игру вдвоём. Обычный запуск ждёт вашего выбора и сам не начинает кампанию.

[b]Выберите страну[/b] левой кнопкой на карте. В её панели показаны отношения, престиж и доступная политика. Выберите меру, допустимый уровень и нажмите Применить. Сведения о стране открывают отчёт и историю. Закройте панель, чтобы снова видеть всю карту.

[b]Исследуйте карту:[/b] колесо или +/− меняют масштаб, средняя кнопка перемещает карту. Двойной щелчок приближает страну; F или Вся карта возвращают общий вид. Стрелки меняют выбранную страну. Слои включают городские модели, рельеф, конфликты и связи помощи и торговли. Щёлкните город, чтобы открыть страну, значок события — для обзора обстановки, линию связи — для сведений о политике. Общая карта выделяет главные события; небольшие волнения видны при увеличении. Города и улицы — условные модели стран, а связи отражают политику, не маршруты снабжения. Выберите группу и показатель для сравнения отношений, политики или статистики стран. Зависимые от точки зрения показатели используют выбранную страну.

[b]Донесения[/b] открывают список новостей. Изучайте события и оспаривайте подходящие действия соперника. Закройте или переключите панель, чтобы вернуться к карте. Доступные решения дипломатического кризиса появляются в панели страны.

[b]Завершить год[/b] запускает расчёт после принятия решений. Сначала разрешите незаконченный кризис. Счёт и Обязательства объясняют положение кампании; Советники открывают консультации и историю разговоров.

[b]Сохранения[/b] хранятся в именованных слотах окна загрузки и сохранения. Выберите слот для записи или чтения; удаление требует подтверждения. Экспорт создаёт переносимый файл .bopg, Импорт открывает такой файл. Локальная отмена доступна только в поддерживаемом состоянии игры и не заменяет сохранение.

[b]Учиться играть[/b] запускает отдельную тренировку с подготовленным учебным кризисом. Следуйте подсказкам и кнопке подтверждения. Возврат в кампанию восстанавливает исходное положение, случайную последовательность и незавершённый кризис. Во время обучения сохранение, загрузка и замена кампании заблокированы.

[b]Настройки[/b] содержат язык, музыку и громкость, выбор композиции, уменьшение движения, доступные цвета карты и параметры моделей. Смена языка обновляет интерфейс. Уменьшение движения отключает необязательные анимации.""",
"""[font_size=23][color=#eddaa8]Две сверхдержавы, два игрока[/color][/font_size]

Откройте [b]Игру вдвоём[/b] из Меню. Выберите режим до начала кампании. Панель сеанса показывает подключение, очередь хода и доступные действия.

[b]За одним компьютером[/b] каждый игрок управляет своей сверхдержавой. Следите за активной стороной и кнопками передачи управления и завершения хода: обе стороны принимают решения в пределах одного года, прежде чем он сменится. Передайте компьютер указанному игроку; сама передача не означает наступление следующего года.

[b]Локальная сеть[/b] позволяет одному игроку создать сеанс, а другому подключиться по адресу и порту хозяина. Главная копия игры находится у хозяина. Начните партию после подключения соперника, когда это разрешает комната ожидания. Компьютер хозяина должен работать во время всей партии. Для сообщений используйте чат сеанса, для проверки подключения — его статус.

[b]Игра по почте[/b] использует файлы ходов в общей папке. Оба игрока должны указать одинаковый идентификатор партии и выбрать свою сторону. Создайте партию или присоединитесь к существующей, примите решения в свою очередь и опубликуйте ход. Обновление получает доступный ход партнёра. Одинаковое имя локальной папки на двух компьютерах не делает её общей: игрокам нужно организовать обмен файлами или общее хранилище.

Игра проверяет полученное состояние и последовательность ходов. Прежде чем действовать, дождитесь принятия хода партнёра. Обычное одиночное сохранение не заменяет файлы ходов сетевого сеанса.

В кризисе двух игроков следуйте указанной очереди решения и доступным действиям эскалации, отступления и саммита. Обычные правила престижа и ядерного риска сохраняются. Завершая игру, покиньте сеанс; не выключайте хозяина, пока второй игрок рассчитывает на подключение.""",
"""[font_size=23][color=#eddaa8]Авторы и благодарности[/color][/font_size]

[b]Автор оригинала:[/b] Крис Кроуфорд, 1985 и 1988 годы; издатель Mindscape. Эта игра следует Balance of Power: The 1990 Edition.

[b]Перенос на Python:[/b] Томаш Циборский, 2020 год, адаптация исходного Pascal с использованием Python и PyQt5.

[b]Автор ответвления:[/b] Василий Виноградов: соперник на основе модели, советники, саммиты, промежуточные обязательства и сетевая игра.

Оригинальные исходники Pascal использовались для проверки правил:
https://github.com/balance-of-power/bop2-pascal-source

Графика взята из оригинальной игры. Фотографии советников получены из Wikimedia Commons; сведения об авторах находятся в img/advisors/ATTRIBUTION.md. Авторы музыки указаны в music/ATTRIBUTION.md.

Настольный интерфейс работает на Godot; проверенная симуляция на Python остаётся основой правил. Godot распространяется по лицензии MIT. Лицензии включённых сред исполнения и сведения об авторах ресурсов сопровождают автономные сборки."""
]
