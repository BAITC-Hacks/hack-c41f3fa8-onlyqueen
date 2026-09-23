import json
import unittest

from app.ai_analysis import AIAnalyzer
from app.recommender import Recommender


class AIAnalysisChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Recommender("data/profiles.csv")

    def result(self, **overrides):
        request = {
            "city": "Алматы",
            "event_date": "2026-11-15",
            "event_format": "корпоратив",
            "category": "Ведущий",
            "budget_kzt": 10_000_000,
        }
        request.update(overrides)
        return self.engine.recommend(request)

    @staticmethod
    def response(value):
        return {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(value, ensure_ascii=False)}],
            }]
        }

    def success_transport(self, endpoint, api_key, payload, timeout):
        self.assertEqual(endpoint, "https://api.openai.com/v1/responses")
        self.assertEqual(api_key, "test-key")
        self.assertLessEqual(timeout, 8)
        context = json.loads(payload["input"])
        self.assertNotIn("busy_dates", payload["input"])
        self.assertTrue(payload["text"]["format"]["strict"])
        selection = {
            "mode": context["mode"],
            "card_insights": [
                {
                    "id": card["id"],
                    "fact_ids": [card["facts"][0]["id"]],
                    "wish_fit": card["wish_relation"],
                }
                for card in context["cards"]
            ],
            "reason_ids": [],
            "action_ids": [],
        }
        return self.response(selection)

    def test_successful_analysis_keeps_card_ids_and_uses_allowed_facts(self):
        result = self.result(wishes="ведущий для делового форума")
        order_before = [card["id"] for card in result["recommendations"]]
        analyzer = AIAnalyzer("test-key", "organizer-model", transport=self.success_transport)

        analysis = analyzer.analyze(result, self.engine.profiles)

        self.assertTrue(analysis["available"])
        self.assertEqual(analysis["model"], "organizer-model")
        self.assertEqual([note["id"] for note in analysis["card_notes"]], order_before)
        self.assertEqual([card["id"] for card in result["recommendations"]], order_before)
        self.assertTrue(all(note["text"] for note in analysis["card_notes"]))

    def test_successful_empty_analysis_uses_only_calculated_reasons_and_actions(self):
        result = self.result(
            event_date="2026-11-15", event_format="свадьба", category="Инструменталист"
        )
        self.assertEqual(result["outcome"], "none_eligible")

        def transport(_endpoint, _key, payload, _timeout):
            context = json.loads(payload["input"])
            selection = {
                "mode": "empty",
                "card_insights": [],
                "reason_ids": [context["reason_options"][0]["id"]],
                "action_ids": [context["action_options"][0]["id"]],
            }
            return self.response(selection)

        analysis = AIAnalyzer("test-key", "organizer-model", transport=transport).analyze(
            result, self.engine.profiles
        )
        self.assertTrue(analysis["available"])
        self.assertIn(result["guidance"]["plain_reason"], analysis["empty_note"])
        self.assertEqual(len(analysis["suggestions"]), 1)

    def test_invalid_json_falls_back_to_local_result(self):
        result = self.result()
        expected = [card["id"] for card in result["recommendations"]]

        def transport(*_args):
            return {"output": [{"content": [{"type": "output_text", "text": "{"}]}]}

        analysis = AIAnalyzer("test-key", "organizer-model", transport=transport).analyze(
            result, self.engine.profiles
        )
        self.assertFalse(analysis["available"])
        self.assertEqual(analysis["reason"], "invalid_response")
        self.assertEqual([card["id"] for card in result["recommendations"]], expected)

    def test_invented_card_id_is_rejected(self):
        result = self.result()

        def transport(_endpoint, _key, payload, _timeout):
            context = json.loads(payload["input"])
            selection = {
                "mode": "found",
                "card_insights": [
                    {
                        "id": "invented-id" if index == 0 else card["id"],
                        "fact_ids": [card["facts"][0]["id"]],
                        "wish_fit": card["wish_relation"],
                    }
                    for index, card in enumerate(context["cards"])
                ],
                "reason_ids": [],
                "action_ids": [],
            }
            return self.response(selection)

        analysis = AIAnalyzer("test-key", "organizer-model", transport=transport).analyze(
            result, self.engine.profiles
        )
        self.assertFalse(analysis["available"])
        self.assertEqual(analysis["reason"], "invalid_response")

    def test_timeout_falls_back(self):
        def transport(*_args):
            raise TimeoutError("mock timeout")

        analysis = AIAnalyzer("test-key", "organizer-model", transport=transport).analyze(
            self.result(), self.engine.profiles
        )
        self.assertFalse(analysis["available"])
        self.assertEqual(analysis["reason"], "timeout")

    def test_missing_key_or_model_never_calls_transport(self):
        calls = []

        def transport(*args):
            calls.append(args)
            raise AssertionError("transport must not be called")

        for analyzer in (
            AIAnalyzer("", "organizer-model", transport=transport),
            AIAnalyzer("test-key", "", transport=transport),
        ):
            analysis = analyzer.analyze(self.result(), self.engine.profiles)
            self.assertFalse(analysis["available"])
            self.assertEqual(analysis["reason"], "missing_configuration")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
