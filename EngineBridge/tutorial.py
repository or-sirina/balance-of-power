"""An isolated, offline training game with acknowledged-action progression."""

import copy

from GameLogic import CrisisHandler
from GameLogic.Globals import doPolicy
from GameLogic.PolicyRules import check_request, policy_info
import Local
from .localization import country_name, step_ru
from .conversations import ConversationBook


class TutorialSession:
    def __init__(self):
        self.active = False
        self.step = 0
        self._campaign = None
        self.target_country = None
        self.value = None
        self.action = 2
        self._practice = None

    def view(self):
        lesson_en, lesson_ru = self._lesson()
        return {"active": self.active, "step": self.step, "finished": self.step >= 10,
                "total_steps": 11, "target_country": self.target_country,
                "target_name": Local.countryName(self.target_country) if self.target_country is not None else "",
                "target_name_ru": country_name(self.target_country) if self.target_country is not None else "",
                "action": self.action, "value": self.value, "seed": 3,
                "value_label": Local.parseValue(0, self.value) if self.value is not None else "",
                "value_label_ru": step_ru(self.action, self.value) if self.value is not None else "",
                "lesson_key": "lesson_%d" % self.step,
                "lesson_en": lesson_en, "lesson_ru": lesson_ru,
                "crisis_practice": copy.deepcopy(self._practice)}

    def start(self, service):
        from .service import GameService
        training = GameService(save_dir=service._save_dir)
        with training._random_context():
            training._execute("new_game", {"side": 0, "level": 1, "seed": 3})
        # Build the isolated world first, so a failed construction cannot disturb
        # an existing campaign or the snapshot retained by a repeated restart.
        if not self.active:
            self._campaign = {"world": service.world, "rng": service._rng,
                              "presenter": service.presenter, "selection": service.selected_country,
                              "conversations": service.conversations,
                              "opponent_source": service._opponent_source}
        service.world, service._rng = training.world, training._rng
        service.presenter = training.presenter
        service.presenter.service = service
        service.selected_country = None
        service.conversations = ConversationBook()
        service._opponent_source = None
        self.active, self.step = True, 0
        self.action, self._practice = 2, None
        self.target_country, self.value = self._recommendation(service.world)
        service.emit("tutorial_started", seed=3, target_country=self.target_country, action=2, value=self.value)

    @staticmethod
    def _recommendation(world):
        for country in world.country[2:]:
            info = policy_info(world, world.USA, 2, country)
            raises = [step for step in info.steps() if step > info.old]
            if raises:
                return country.id, min(raises)
        for country in world.country[2:]:
            info = policy_info(world, world.USA, 2, country)
            changes = [step for step in info.steps() if step != info.old]
            if changes:
                return country.id, min(changes)
        raise ValueError("training fixture has no legal military aid change")

    def end(self, service):
        if not self.active:
            return False
        campaign = self._campaign
        service.world, service._rng = campaign["world"], campaign["rng"]
        service.presenter, service.selected_country = campaign["presenter"], campaign["selection"]
        service.conversations = campaign["conversations"]
        service.presenter.service = service
        service._opponent_source = campaign["opponent_source"]
        service._bind_opponent()
        self.active, self.step, self._campaign = False, 0, None
        self.target_country, self.value = None, None
        self.action, self._practice = 2, None
        service.emit("tutorial_ended", campaign_restored=service.world is not None)
        return True

    def acknowledge(self, service):
        if not self.active or self.step not in (1, 6):
            return False
        self.step += 1
        service.emit("tutorial_progress", step=self.step)
        return True

    def observe(self, service, command, args, events):
        """Consume committed results, never requested or rejected intentions."""
        if not self.active:
            return False
        kinds = {event["type"] for event in events}
        selected_minor = command == "select_country" and args.get("country_id", -1) >= 2
        advance = ((self.step == 0 and selected_minor and "country_selected" in kinds)
                   or (self.step == 2 and "policy_applied" in kinds)
                   or (self.step == 3 and "turn_completed" in kinds)
                   or (self.step == 4 and selected_minor and "country_selected" in kinds)
                   or (self.step == 5 and "advisor_reply" in kinds))
        if not advance:
            if self.step == 7 and command == "crisis_choice" and args.get("choice") == "tough" and "crisis_choice_applied" in kinds:
                self._record_escalation(service)
            elif self.step == 8 and command == "crisis_choice" and args.get("choice") == "loose" and "crisis_choice_applied" in kinds:
                self._record_concession(service)
            elif self.step == 9 and command == "crisis_choice" and args.get("choice") == "continue" and "crisis_choice_applied" in kinds:
                if service.presenter.newsWindow.locked:
                    raise ValueError("practice crisis did not close")
                self._practice = dict(self._practice, active=False)
            else:
                return False
        if self.step == 5:
            self._begin_crisis(service)
        self.step += 1
        service.emit("tutorial_progress", step=self.step)
        return True

    def crisis_choices(self, ordinary):
        """Bound only this isolated lesson; normal game choices are untouched."""
        if not self.active or not 6 <= self.step <= 9:
            return ordinary
        expected = {6: (), 7: ("tough",), 8: ("loose",), 9: ("continue",)}[self.step]
        return [choice for choice in ordinary if choice in expected]

    def _begin_crisis(self, service):
        """A prepared challenge, followed by unmodified single-player rules.

        The fixture is intentionally separate from the learner's free choices.
        Its legal policy and ordinary fixed-seed AI response are verified in the
        tests. We prepare the challenge; we never fake the ensuing outcomes.
        """
        from .service import GameService
        practice = GameService(save_dir=service._save_dir)
        with practice._random_context():
            practice._execute("new_game", {"side": 0, "level": 1, "seed": 3})
            world = practice.world
            world.news.clear()
            world.beingQuestioned = False
            target, action, value = 2, 3, 1  # Mexico, aid to rebels, $20m/year.
            valid, reason = check_request(world, world.USA, action, target, value)
            if not valid:
                raise ValueError("practice fixture policy is no longer legal: " + reason)
            old = world.USA.insgAid[target]
            before = world.USA.prestige(world)
            doPolicy(world, world.USA, world.country[target], action, value)
            headline = world.news[0]
            headline.isQuestioned = True  # Explicit prepared opponent challenge.
            CrisisHandler.doCrisis(practice.presenter.newsWindow, world, headline)
            if world.crisis.level != 9 or world.crisis.backDown:
                raise ValueError("practice fixture failed to open at rung nine")
            opening_risk = int(practice.presenter.newsWindow.leftInfoVal[0].text or 0)
        # Leave both the saved campaign and the learner's conversation book alone.
        service.world, service._rng = practice.world, practice._rng
        service.presenter = practice.presenter
        service.presenter.service = service
        service.selected_country = target
        service._opponent_source = None
        self.target_country, self.action, self.value = target, action, value
        self._practice = {"active": True, "source": "scripted_fixture", "seed": 3,
                          "country_id": target, "action": action, "opening_level": 9, "current_level": 9,
                          "lowest_allowed_level": 7, "opening_risk": opening_risk,
                          "risk_after_escalation": None, "policy_before": old, "policy_proposed": value,
                          "policy_current": value, "prestige_before": before, "prestige_after": None,
                          "observed_loss": None}
        service.emit("tutorial_crisis_started", source="scripted_fixture", country_id=target,
                     action=action, old=old, new=value, level=9, prestige_at_risk=opening_risk)

    def _record_escalation(self, service):
        world, panel = service.world, service.presenter.newsWindow
        if world.crisis.level != 7 or world.crisis.backDown or world.NWFlag or world.ANWFlag:
            raise ValueError("practice fixture must remain on its verified safe rung")
        risk = int(panel.leftInfoVal[0].text or 0)
        self._practice = dict(self._practice, current_level=world.crisis.level, risk_after_escalation=risk,
                              policy_current=world.USA.insgAid[self.target_country])
        service.emit("tutorial_crisis_escalated", level=world.crisis.level, prestige_at_risk=risk)

    def _record_concession(self, service):
        world = service.world
        current = world.USA.insgAid[self.target_country]
        if not world.crisis.backDown or current != self._practice["policy_before"]:
            raise ValueError("practice concession must enact the actual policy reversal")
        after = world.USA.prestige(world)
        self._practice = dict(self._practice, current_level=world.crisis.level, policy_current=current,
                              prestige_after=after, observed_loss=self._practice["prestige_before"] - after)
        service.emit("tutorial_crisis_conceded", level=world.crisis.level, policy_current=current,
                     prestige_before=self._practice["prestige_before"], prestige_after=after)

    def _lesson(self):
        facts = self._practice or {}
        if self.step == 6:
            return (
                "7. Read the challenge\nThis is a prepared, offline practice scenario: the USSR challenges our aid to rebels in Mexico. The crisis starts at rung 9, the safest rung. Read the opponent's reaction and the prestige at risk: %s. That number is prestige, not the probability of war. A retreat on rungs 9 and 8 has no prestige penalty. Acknowledge this before acting." % facts.get("opening_risk", 0),
                "7. Прочитайте возражение\nЭто подготовленная учебная ситуация без обращения к модели: СССР оспаривает нашу помощь повстанцам в Мексике. Кризис начинается на самой безопасной ступени 9. Прочитайте реакцию соперника и величину «Престиж под угрозой»: %s. Это баллы престижа, а не вероятность войны. На ступенях 9 и 8 отступление не штрафуется престижем. Подтвердите, что прочитали разбор." % facts.get("opening_risk", 0))
        if self.step == 7:
            return (
                "8. Stand firm once\nChoose Stand firm once. Your decision advances the crisis one rung, and the built-in opponent answers under the normal rules. This lesson permits only one escalation. Keeping a commitment can defend influence, but raising the stakes makes a later retreat more expensive.",
                "8. Один раз проявите твёрдость\nВыберите «Стоять на своём». Ваше решение сдвинет кризис на одну ступень, затем встроенный соперник ответит по обычным правилам. В этом упражнении разрешена только одна эскалация. Упорство может защитить влияние, но повышает цену последующего отступления.")
        if self.step == 8:
            return (
                "9. Compare the price\nBoth sides have stood firm: the actual crisis is now at rung %s. Displayed prestige at risk rose from %s to %s. Accidental nuclear risk begins at rung 4; this exercise stays above it. Choose Back down and observe the actual result. You are giving up the disputed increase, not endorsing nuclear escalation." % (facts.get("current_level"), facts.get("opening_risk"), facts.get("risk_after_escalation")),
                "9. Сравните цену\nОбе стороны настояли на своём: кризис действительно дошёл до ступени %s. Показанный престиж под угрозой вырос с %s до %s. Риск случайной ядерной войны появляется на ступени 4; упражнение до неё не доходит. Выберите «Отступить» и посмотрите на реальный результат. Вы отказываетесь от спорного увеличения помощи." % (facts.get("current_level"), facts.get("opening_risk"), facts.get("risk_after_escalation")))
        if self.step == 9:
            return (
                "10. Read the concession\nThe engine reverted aid to rebels from step %s to step %s. Base prestige changed from %s to %s: the observed loss is %s points (the earlier displayed estimate was %s). World opinion changed as well. The ordinary score panel is updated when the year is scored. Choose Continue to close this resolved crisis." % (facts.get("policy_proposed"), facts.get("policy_current"), facts.get("prestige_before"), facts.get("prestige_after"), facts.get("observed_loss"), facts.get("risk_after_escalation")),
                "10. Прочитайте результат уступки\nДвижок отменил увеличение помощи повстанцам: уровень %s → %s. Базовый престиж изменился с %s до %s: фактическая потеря — %s баллов (ранее показывалась оценка %s). Изменилось и отношение других стран. Обычный счёт обновляется при подведении итогов года. Выберите «Продолжить», чтобы закрыть завершённый кризис." % (facts.get("policy_proposed"), facts.get("policy_current"), facts.get("prestige_before"), facts.get("prestige_after"), facts.get("observed_loss"), facts.get("risk_after_escalation")))
        if self.step >= 10:
            return (
                "Practice complete\nYou read a challenge, compared prestige risk, escalated once and observed a real concession. All practice was offline and separate from your campaign. Return to campaign restores its exact position, random stream, conversations and any pending crisis. You can also restart this course.",
                "Практика завершена\nВы прочитали возражение, сравнили риск для престижа, один раз усилили кризис и увидели настоящие последствия уступки. Всё обучение шло без модели и отдельно от основной партии. «Вернуться в игру» восстановит точную позицию, последовательность случайных событий, разговоры и незавершённый кризис. Обучение можно начать заново.")
        return "", ""
