"""Living map uses public simulation facts without affecting the campaign."""
import _isolate  # noqa: F401
import random
import unittest
from EngineBridge import GameService
from EngineBridge.map_scene import build_map_scene
from Net.State import world_to_state


def seeded_visual_qa_service():
    """Real campaign fixture: seed 27 already produces all five event kinds.

    No status/flag/policy is injected. Never install this fixture into a user's
    campaign; export its detached DTO for isolated rendering checks instead.
    """
    service = GameService()
    result = service.handle({"id": "start", "command": "new_game",
                                      "expected_revision": 0,
                                      "args": {"level": 4, "side": 0, "seed": 27}})
    if not result["ok"]:
        raise AssertionError(result)
    return service


class MapSceneTests(unittest.TestCase):
    def setUp(self):
        self.service = seeded_visual_qa_service()
        self.world = self.service.world

    def test_real_seeded_fixture_has_visual_qa_events(self):
        scene = build_map_scene(self.world)
        self.assertEqual(len(scene["countries"]), 80)
        self.assertTrue({"civil_war", "insurgency", "unrest", "coup", "revolution"}
                        <= {event["kind"] for event in scene["events"]})
        self.assertTrue(scene["routes"])
        self.assertTrue(any(e["country_id"] == 40 and e["kind"] == "civil_war"
                            for e in scene["events"]))

    def test_read_only_and_detached(self):
        before, rng, engine_rng = world_to_state(self.world), random.getstate(), self.service._rng
        scene = build_map_scene(self.world)
        self.assertEqual(scene, build_map_scene(self.world))
        scene["countries"][0]["war_with"].append(79)
        self.assertEqual(before, world_to_state(self.world))
        self.assertEqual(rng, random.getstate())
        self.assertEqual(engine_rng, self.service._rng)

    def test_exact_original_insurgency_boundaries(self):
        c = self.world.country[2]
        for ratio, expected in ((0, 0), (1, 0), (2, 1), (7, 1), (8, 2),
                                (31, 2), (32, 3), (127, 3), (128, 4),
                                (511, 4), (512, 5), (2047, 5), (2048, 6)):
            c.strengthRatio = ratio
            scene = build_map_scene(self.world)
            self.assertEqual(scene["countries"][2]["insurgency"], expected)
            statuses = [e for e in scene["events"] if e["country_id"] == 2
                        and e["source"] == "insurgency_status"]
            self.assertEqual(len(statuses), int(expected < 6))
            if statuses:
                self.assertEqual(statuses[0]["kind"], "civil_war" if expected == 0
                                 else "insurgency" if expected <= 2 else "unrest")

    def test_actual_status_and_flags(self):
        c = self.world.country[2]
        c.strengthRatio, c.hasCoup, c.hasRevolution = 0, True, True
        c.diplOpinion[3] = -127
        scene = build_map_scene(self.world)
        row = scene["countries"][2]
        self.assertEqual(row["insurgency"], c.getInsurgency())
        self.assertEqual(row["war_with"], [3])
        events = [e for e in scene["events"] if e["country_id"] == 2]
        self.assertEqual({e["kind"] for e in events}, {"civil_war", "coup", "revolution"})
        self.assertTrue(all(e["label"] and e["label_ru"] for e in events))

    def test_only_own_policy_links_and_no_reference_riots(self):
        own, opponent = self.world.country[:2]
        own.govtIntv[2], own.trade[3], opponent.govtIntv[4] = 3, 4, 5
        scene = build_map_scene(self.world)
        self.assertTrue(all(r["actor"] == self.world.human for r in scene["routes"]))
        route = next(r for r in scene["routes"] if r["kind"] == "government_intervention" and r["target"] == 2)
        self.assertEqual(route["step"], 3)
        self.assertIn("20", route["value_label_ru"])
        self.assertTrue(all(r["label_ru"] and r["value_label_ru"] for r in scene["routes"]))
        self.assertFalse(any(e["kind"] == "riot" for e in scene["events"]))
        self.assertNotIn("encyclopedia", str(scene))


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--export-scene":
        import json
        from pathlib import Path
        Path(sys.argv[2]).write_text(json.dumps(
            build_map_scene(seeded_visual_qa_service().world), ensure_ascii=False), encoding="utf-8")
    else:
        unittest.main()
