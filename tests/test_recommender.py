import unittest
import re
import time
from pathlib import Path

from app.recommender import Recommender


class RecommenderChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Recommender("data/profiles.csv")

    def request(self, **overrides):
        base = {
            "city": "Алматы",
            "event_date": "2026-09-23",
            "event_format": "корпоратив",
            "category": "Ведущий",
            "budget_kzt": 10_000_000,
        }
        base.update(overrides)
        return base

    def test_dataset_and_pipe_separated_fields(self):
        self.assertEqual(len(self.engine.profiles), 66)
        bulma = next(p for p in self.engine.profiles if p.anon_name == "Буллма")
        self.assertIn("Ведущий", bulma.categories)
        self.assertIn("английский", bulma.languages)
        self.assertIn("корпоратив", bulma.event_formats)
        self.assertIn("2026-09-23", bulma.busy_dates)

    def test_stable_order_and_contractor_specific_explanations(self):
        req = self.request(event_date="2026-11-15")
        first = self.engine.recommend(req)
        second = self.engine.recommend(req)
        self.assertEqual(
            [x["id"] for x in first["recommendations"]],
            [x["id"] for x in second["recommendations"]],
        )
        normalized = []
        profiles = {p.id: p for p in self.engine.profiles}
        for card in first["recommendations"]:
            description = " ".join(profiles[card["id"]].description.split())
            for reason in card["score_reasons"]:
                if reason["kind"].endswith("description"):
                    self.assertIn(reason["source_fragment"], description)
            self.assertNotRegex(card["explanation"].casefold(), r"топ[- ]?10|лучший")
            without_identity_or_price = card["explanation"].replace(card["name"], "<имя>")
            without_identity_or_price = re.sub(
                r"Начальная цена от [\d ]+ ₸ не превышает бюджет; итоговую стоимость нужно уточнить",
                "цена подходит",
                without_identity_or_price,
            )
            normalized.append(without_identity_or_price)
        self.assertEqual(len(normalized), len(set(normalized)))
        by_name = {card["name"]: card for card in first["recommendations"]}
        self.assertEqual(by_name["Куррапика"]["relevance_score"], 25)
        self.assertIn("деловых встреч", by_name["Куррапика"]["explanation"])
        self.assertIn("мультимедийное оборудование", by_name["Мицури Канроджи"]["explanation"])
        self.assertIn("казахском, русском и английском языках", by_name["Кики"]["explanation"])

    def test_live_band_explanations_remain_distinct_without_contractor_names(self):
        result = self.engine.recommend(self.request(
            event_format="корпоратив", category="Лайв-бэнд", budget_kzt=10_000_000
        ))
        by_name = {card["name"]: card["explanation"] for card in result["recommendations"]}
        self.assertIn("два вокалиста", by_name["Дзэнъицу Агацума"])
        self.assertIn("тромбон", by_name["Дзэнъицу Агацума"])
        self.assertIn("4 вокалиста", by_name["Рей Аянами"])
        self.assertIn("струнный квартет", by_name["Рей Аянами"])
        without_names = [
            explanation.replace(name, "<имя>")
            for name, explanation in by_name.items()
        ]
        self.assertEqual(len(without_names), len(set(without_names)))

    def test_national_ensemble_uses_distinct_safe_description_fragments(self):
        result = self.engine.recommend(self.request(
            event_date="2026-12-26", event_format="свадьба",
            category="Национальный ансамбль", budget_kzt=10_000_000,
        ))
        by_name = {card["name"]: card["explanation"] for card in result["recommendations"]}
        self.assertEqual(list(by_name), ["Эдвард Ван Хог", "Рамь", "Поньо"])
        self.assertIn("казахскую песню", by_name["Эдвард Ван Хог"])
        self.assertIn("перед главой государства", by_name["Рамь"])
        self.assertIn("Ансамбль Sailor Dala", by_name["Поньо"])

        normalized = []
        for name, explanation in by_name.items():
            self.assertNotRegex(explanation.casefold(), r"№\s*1|украс\w*|топ[- ]?\d+|лучш\w*")
            self.assertEqual(explanation.count("."), 2)
            without_name_or_price = explanation.replace(name, "<имя>")
            without_name_or_price = re.sub(
                r"Начальная цена от [\d ]+ ₸ не превышает бюджет; итоговую стоимость нужно уточнить\. ",
                "",
                without_name_or_price,
            )
            normalized.append(without_name_or_price)
        self.assertEqual(len(normalized), len(set(normalized)))

    def test_related_show_categories_keep_explanations_distinct(self):
        for category in ("Танцевальный коллектив", "Шоу-программа"):
            with self.subTest(category=category):
                result = self.engine.recommend(self.request(
                    event_date="2026-12-26", event_format="свадьба",
                    category=category, budget_kzt=10_000_000,
                ))
                normalized = []
                for card in result["recommendations"]:
                    explanation = card["explanation"].replace(card["name"], "<имя>")
                    explanation = re.sub(
                        r"Начальная цена от [\d ]+ ₸ не превышает бюджет; итоговую стоимость нужно уточнить\. ",
                        "",
                        explanation,
                    )
                    normalized.append(explanation)
                self.assertEqual(len(normalized), len(set(normalized)))

    def test_relevance_beats_cheaper_eligible_contractor(self):
        result = self.engine.recommend(self.request(
            event_date="2026-11-15", wishes="ведущий для делового форума"
        ))
        first, second = result["recommendations"][:2]
        self.assertEqual(first["name"], "Буллма")
        self.assertEqual(second["name"], "Куррапика")
        self.assertGreater(first["price_from_kzt"], second["price_from_kzt"])
        self.assertGreater(first["relevance_score"], second["relevance_score"])
        wish_reason = next(r for r in first["score_reasons"] if r["kind"] == "wishes_description")
        self.assertIn("бизнес форумы на 3000 человек", wish_reason["source_fragment"])

    def test_scores_are_individual_zero_to_one_hundred_without_blank_penalties(self):
        result = self.engine.recommend(self.request(event_date="2026-11-15"))
        for card in result["recommendations"]:
            self.assertGreaterEqual(card["relevance_score"], 0)
            self.assertLessEqual(card["relevance_score"], 100)
            components = {item["kind"]: item for item in card["score_breakdown"]}
            self.assertEqual(components["language"]["points"], 0)
            self.assertIn("штрафа нет", components["language"]["label"])
            self.assertEqual(components["duration"]["points"], 0)
            self.assertIn("штрафа нет", components["duration"]["label"])
            self.assertEqual(components["wishes_description"]["points"], 0)

    def test_wishes_never_override_busy_date(self):
        result = self.engine.recommend(self.request(
            event_date="2026-09-23", wishes="ведущий для делового форума"
        ))
        self.assertNotIn("Буллма", [card["name"] for card in result["recommendations"]])
        bulma = next(p for p in self.engine.profiles if p.anon_name == "Буллма")
        self.assertIn("2026-09-23", bulma.busy_dates)

    def test_budget_suggestion_reruns_all_hard_filters(self):
        req = self.request(
            category="Ресторан", event_format="свадьба", budget_kzt=1_000
        )
        empty = self.engine.recommend(req)
        self.assertEqual(empty["outcome"], "none_eligible")
        self.assertEqual(empty["rejections"]["budget"], empty["base_count"])
        self.assertEqual(empty["guidance"]["lowest_price_kzt"], 2_000_000)
        suggested_budget = empty["guidance"]["suggested_budget_kzt"]
        self.assertEqual(suggested_budget, 2_000_000)

        retried = self.engine.recommend({**req, "budget_kzt": suggested_budget})
        profiles = {p.id: p for p in self.engine.profiles}
        self.assertGreater(retried["eligible_count"], 0)
        for card in retried["recommendations"]:
            profile = profiles[card["id"]]
            self.assertLessEqual(profile.price_from_kzt, suggested_budget)
            self.assertNotIn(req["event_date"], profile.busy_dates)
            self.assertIn(req["event_format"], profile.event_formats)

    def test_budget_guidance_explains_why_button_exceeds_category_minimum(self):
        result = self.engine.recommend(self.request(
            category="Банкетный зал", event_format="конференция", budget_kzt=1_000
        ))
        guidance = result["guidance"]
        self.assertEqual(guidance["lowest_price_kzt"], 2_000_000)
        self.assertEqual(guidance["suggested_budget_kzt"], 3_500_000)
        self.assertIn("Самая низкая начальная цена в категории — от 2 000 000 ₸", guidance["plain_reason"])
        self.assertIn(
            "Бюджет 3 500 000 ₸ — это минимальная начальная цена профиля, который свободен",
            guidance["plain_reason"],
        )

    def test_date_suggestions_rerun_all_hard_filters(self):
        req = self.request(
            category="Инструменталист", event_format="свадьба",
            event_date="2026-11-15", budget_kzt=10_000_000,
        )
        empty = self.engine.recommend(req)
        self.assertEqual(empty["outcome"], "none_eligible")
        self.assertTrue(empty["guidance"]["suggested_dates"])
        profiles = {p.id: p for p in self.engine.profiles}
        for suggestion in empty["guidance"]["suggested_dates"]:
            retried = self.engine.recommend({**req, "event_date": suggestion["date"]})
            self.assertEqual(retried["eligible_count"], suggestion["eligible_count"])
            for card in retried["recommendations"]:
                profile = profiles[card["id"]]
                self.assertNotIn(suggestion["date"], profile.busy_dates)
                self.assertLessEqual(profile.price_from_kzt, req["budget_kzt"])
                self.assertIn(req["event_format"], profile.event_formats)

    def test_optional_constraint_removal_is_a_query_change_not_a_bypass(self):
        req = self.request(
            event_format="день рождения", category="Банкетный зал", language="казахский"
        )
        empty = self.engine.recommend(req)
        suggestion = next(
            item for item in empty["guidance"]["removable_constraints"]
            if item["key"] == "language"
        )
        self.assertEqual(empty["outcome"], "none_eligible")
        retried = self.engine.recommend({key: value for key, value in req.items() if key != "language"})
        self.assertEqual(retried["eligible_count"], suggestion["eligible_count"])
        profiles = {p.id: p for p in self.engine.profiles}
        for card in retried["recommendations"]:
            profile = profiles[card["id"]]
            self.assertNotIn(req["event_date"], profile.busy_dates)
            self.assertIn(req["event_format"], profile.event_formats)
            self.assertLessEqual(profile.price_from_kzt, req["budget_kzt"])

    def test_dense_query_completes_under_ten_seconds(self):
        started = time.perf_counter()
        result = self.engine.recommend(self.request(event_date="2026-11-15"))
        self.assertEqual(len(result["recommendations"]), 3)
        self.assertLess(time.perf_counter() - started, 10)

    def test_never_recommends_busy_contractor(self):
        result = self.engine.recommend(self.request())
        profiles = {p.id: p for p in self.engine.profiles}
        for card in result["recommendations"]:
            self.assertNotIn("2026-09-23", profiles[card["id"]].busy_dates)

    def test_optional_language_and_duration_are_hard_filters(self):
        req = self.request(
            event_date="2026-11-15", language="английский", duration_hours=7
        )
        result = self.engine.recommend(req)
        profiles = {p.id: p for p in self.engine.profiles}
        self.assertGreater(result["rejections"]["language"], 0)
        self.assertGreater(result["rejections"]["duration"], 0)
        for card in result["recommendations"]:
            profile = profiles[card["id"]]
            self.assertIn("английский", profile.languages)
            self.assertTrue(profile.max_hours is None or profile.max_hours >= 7)

    def test_date_changes_result(self):
        req = self.request(category="Инструменталист", event_format="свадьба")
        comparison = self.engine.compare(req, "2026-09-24")
        self.assertEqual(comparison["primary"]["eligible_count"], 3)
        self.assertEqual(comparison["comparison"]["eligible_count"], 1)
        self.assertEqual(
            comparison["ranking_changes"]["left_top3"],
            ["Джет Блэк", "Сакура Харуно"],
        )
        self.assertEqual(
            comparison["availability_changes"]["became_busy"],
            ["Джет Блэк", "Сакура Харуно"],
        )

    def test_leaving_top3_does_not_imply_became_busy(self):
        comparison = self.engine.compare(self.request(
            category="Банкетный зал", event_format="корпоратив", event_date="2026-09-25"
        ), "2026-09-26")
        self.assertIn("Дарквнесс", comparison["ranking_changes"]["left_top3"])
        self.assertNotIn("Дарквнесс", comparison["availability_changes"]["became_busy"])
        self.assertIn("Иноскэ Хашибира", comparison["availability_changes"]["became_free"])

    def test_dense_autumn_category(self):
        result = self.engine.recommend(self.request(event_date="2026-11-15"))
        self.assertEqual(result["eligible_count"], 7)
        self.assertEqual(len(result["recommendations"]), 3)

    def test_rare_category_and_exact_count(self):
        result = self.engine.recommend(self.request(
            city="Астана", category="Фото и видеобудки", event_format="свадьба"
        ))
        self.assertEqual(result["eligible_count"], 1)
        self.assertIn("Найдено рекомендаций: 1", result["summary"])
        self.assertIn("Меньше трёх", result["summary"])

    def test_eligible_rare_candidate_can_have_zero_additional_matches(self):
        result = self.engine.recommend(self.request(
            city="Астана", category="Фото и видеобудки", event_format="свадьба"
        ))
        self.assertEqual(result["outcome"], "found")
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["recommendations"][0]["relevance_score"], 0)

    def test_zero_score_ui_distinguishes_eligibility_from_additional_matches(self):
        html = Path("static/index.html").read_text(encoding="utf-8")
        script = Path("static/app.js").read_text(encoding="utf-8")
        self.assertIn("Соответствует обязательным условиям", html)
        self.assertIn("Дополнительные совпадения:", script)
        self.assertIn("не вероятность и не оценка выполнения обязательных условий", script)

    def test_empty_because_busy(self):
        result = self.engine.recommend(self.request(
            city="Алматы", category="Инструменталист",
            event_format="свадьба", event_date="2026-11-15"
        ))
        self.assertEqual(result["outcome"], "none_eligible")
        self.assertEqual(result["rejections"]["busy"], 3)

    def test_no_city_category_is_distinct(self):
        request = self.request(city="Астана", category="Ресторан")
        result = self.engine.recommend(request)
        self.assertEqual(result["outcome"], "no_city_category")
        suggestion = result["guidance"]["suggested_cities"][0]
        self.assertEqual(suggestion, {"city": "Алматы", "profile_count": 7})

        retried = self.engine.recommend({**request, "city": suggestion["city"]})
        self.assertEqual(retried["request"]["city"], "Алматы")
        self.assertGreater(retried["eligible_count"], 0)
        self.assertTrue(all(card["city"] == "Алматы" for card in retried["recommendations"]))

    def test_price_explanation_treats_price_from_as_a_starting_price(self):
        result = self.engine.recommend(self.request())
        self.assertTrue(result["recommendations"])
        for card in result["recommendations"]:
            self.assertIn(
                f"Начальная цена от {card['price_from_kzt']:,} ₸".replace(",", " "),
                card["explanation"],
            )
            self.assertIn("итоговую стоимость нужно уточнить", card["explanation"])
            self.assertNotIn("цена укладывается в бюджет", card["explanation"])

    def test_empty_max_hours_does_not_restrict_duration(self):
        candidate = next(p for p in self.engine.profiles if p.max_hours is None)
        req = self.request(
            city=candidate.city,
            category=candidate.categories[0],
            event_format=candidate.event_formats[0],
            event_date=next(d for d in ("2026-09-23", "2026-09-24", "2026-09-25") if d not in candidate.busy_dates),
            duration_hours=100,
            budget_kzt=10_000_000,
        )
        result = self.engine.recommend(req)
        self.assertIn(candidate.id, [p["id"] for p in result["recommendations"]])

    def test_date_range_validation(self):
        with self.assertRaisesRegex(ValueError, "между 2026-09-23 и 2026-12-31"):
            self.engine.recommend(self.request(event_date="2027-01-01"))

    def test_venue_calendar_is_enforced(self):
        result = self.engine.recommend(self.request(
            category="Банкетный зал", event_format="свадьба", event_date="2026-09-23"
        ))
        profiles = {p.id: p for p in self.engine.profiles}
        self.assertGreater(result["rejections"]["busy"], 0)
        self.assertTrue(all("2026-09-23" not in profiles[x["id"]].busy_dates for x in result["recommendations"]))


if __name__ == "__main__":
    unittest.main()
