from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


LIST_FIELDS = ("categories", "event_formats", "languages", "busy_dates")
STOP_WORDS = {
    "для", "нужен", "нужна", "нужно", "хочу", "ищу", "который", "которая",
    "мероприятие", "мероприятия", "событие", "события", "подрядчик",
}
PROMOTIONAL = re.compile(
    r"\b(?:лучш\w*|топ[- ]?\d+|идеальн\w*|безупречн\w*|профессионал\w*|премиальн\w*)\b",
    re.I,
)
FORMAT_CONCEPTS = {
    "свадьба": {"свадьба"},
    "корпоратив": {"корпоратив"},
    "конференция": {"конференц"},
    "юбилей": {"юбиле"},
    "той": {"той"},
    "день рождения": {"день", "рожд"},
}


def _list(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split("|") if item.strip())


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class Profile:
    id: str
    anon_name: str
    categories: tuple[str, ...]
    city: str
    city_imputed: bool
    synthetic: bool
    price_from_kzt: int
    price_imputed: bool
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: float | None
    busy_dates: tuple[str, ...]
    description: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Profile":
        missing = {
            "id", "anon_name", "categories", "city", "city_imputed",
            "synthetic", "price_from_kzt", "price_imputed", "event_formats",
            "languages", "max_hours", "busy_dates", "description",
        } - row.keys()
        if missing:
            raise ValueError(f"В CSV отсутствуют поля: {', '.join(sorted(missing))}")
        return cls(
            id=row["id"].strip(),
            anon_name=row["anon_name"].strip(),
            categories=_list(row["categories"]),
            city=row["city"].strip(),
            city_imputed=_bool(row["city_imputed"]),
            synthetic=_bool(row["synthetic"]),
            price_from_kzt=int(row["price_from_kzt"]),
            price_imputed=_bool(row["price_imputed"]),
            event_formats=_list(row["event_formats"]),
            languages=_list(row["languages"]),
            max_hours=float(row["max_hours"]) if row["max_hours"].strip() else None,
            busy_dates=_list(row["busy_dates"]),
            description=row["description"].strip(),
        )


class Recommender:
    def __init__(self, csv_path: str | Path):
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
            self.profiles = [Profile.from_row(row) for row in csv.DictReader(handle)]
        if not self.profiles:
            raise ValueError("CSV не содержит профилей")
        all_dates = sorted({d for p in self.profiles for d in p.busy_dates})
        if not all_dates:
            raise ValueError("В CSV нет дат для определения допустимого диапазона")
        self.date_min, self.date_max = all_dates[0], all_dates[-1]

    def metadata(self) -> dict[str, Any]:
        return {
            "profile_count": len(self.profiles),
            "cities": sorted({p.city for p in self.profiles}),
            "categories": sorted({x for p in self.profiles for x in p.categories}),
            "formats": sorted({x for p in self.profiles for x in p.event_formats}),
            "languages": sorted({x for p in self.profiles for x in p.languages}),
            "date_min": self.date_min,
            "date_max": self.date_max,
        }

    def _validate(self, request: dict[str, Any]) -> dict[str, Any]:
        required = ("city", "event_date", "event_format", "category", "budget_kzt")
        missing = [key for key in required if request.get(key) in (None, "")]
        if missing:
            raise ValueError(f"Заполните обязательные поля: {', '.join(missing)}")
        try:
            parsed = date.fromisoformat(str(request["event_date"]))
        except ValueError as exc:
            raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД") from exc
        if not date.fromisoformat(self.date_min) <= parsed <= date.fromisoformat(self.date_max):
            raise ValueError(f"Дата должна быть между {self.date_min} и {self.date_max}")
        try:
            budget = int(request["budget_kzt"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Бюджет должен быть целым числом") from exc
        if budget < 0:
            raise ValueError("Бюджет не может быть отрицательным")
        duration = request.get("duration_hours")
        if duration in (None, ""):
            duration_value = None
        else:
            try:
                duration_value = float(duration)
            except (TypeError, ValueError) as exc:
                raise ValueError("Длительность должна быть числом") from exc
            if duration_value <= 0:
                raise ValueError("Длительность должна быть больше нуля")
        wishes = str(request.get("wishes") or "").strip()
        if len(wishes) > 300:
            raise ValueError("Пожелания должны быть не длиннее 300 символов")
        return {
            "city": str(request["city"]),
            "event_date": parsed.isoformat(),
            "event_format": str(request["event_format"]),
            "category": str(request["category"]),
            "budget_kzt": budget,
            "duration_hours": duration_value,
            "language": str(request.get("language") or ""),
            "wishes": wishes,
        }

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-zа-я0-9]+", " ", text.casefold().replace("ё", "е")).strip()

    @staticmethod
    def _concept(token: str) -> str:
        if token.startswith(("делов", "бизнес")):
            return "business"
        for prefix, concept in (
            ("репортаж", "репортаж"), ("съем", "съемка"), ("форум", "форум"),
            ("корпоратив", "корпоратив"), ("конференц", "конференц"),
            ("свад", "свадьба"), ("юбиле", "юбиле"), ("рожд", "рожд"),
        ):
            if token.startswith(prefix):
                return concept
        return token[:5] if len(token) >= 6 else token

    @classmethod
    def _concepts(cls, text: str) -> set[str]:
        return {
            cls._concept(token)
            for token in cls._normalize(text).split()
            if len(token) >= 3 and token not in STOP_WORDS
        }

    @staticmethod
    def _fragments(description: str) -> list[str]:
        normalized = " ".join(description.split())
        return [
            part.strip(" -–—:;,.!")
            for part in re.split(r"(?<=[.!?])\s+|\s*•\s*", normalized)
            if 18 <= len(part.strip()) <= 240 and not PROMOTIONAL.search(part)
        ]

    @classmethod
    def _source_for_concepts(cls, profile: Profile, concepts: set[str]) -> str | None:
        candidates = []
        for index, fragment in enumerate(cls._fragments(profile.description)):
            matched = len(concepts & cls._concepts(fragment))
            if matched:
                candidates.append((matched, -index, fragment))
        if not candidates or max(candidates)[0] < len(concepts):
            return None
        return max(candidates)[2]

    @classmethod
    def _score(cls, profile: Profile, req: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        score = 0
        reasons: list[dict[str, Any]] = []

        format_concepts = FORMAT_CONCEPTS.get(
            req["event_format"], cls._concepts(req["event_format"])
        )
        format_source = cls._source_for_concepts(profile, format_concepts)
        if format_source:
            score += 30
            reasons.append({
                "kind": "format_description", "points": 30,
                "label": f"описание подтверждает формат «{req['event_format']}»",
                "source_fragment": format_source,
            })

        if req["wishes"]:
            ignored = cls._concepts(req["category"] + " " + req["event_format"])
            wish_concepts = cls._concepts(req["wishes"]) - ignored
            if wish_concepts:
                wish_source = cls._source_for_concepts(profile, wish_concepts)
                if wish_source:
                    exact = cls._normalize(req["wishes"]) in cls._normalize(profile.description)
                    points = 60 if exact else 45
                    score += points
                    reasons.append({
                        "kind": "wishes_description", "points": points,
                        "label": "описание соответствует пожеланиям",
                        "source_fragment": wish_source,
                    })

        if req["language"]:
            score += 10
            reasons.append({
                "kind": "language", "points": 10,
                "label": f"запрошенный язык «{req['language']}» указан в languages",
                "source_fragment": f"languages: {' | '.join(profile.languages)}",
            })
        if req["duration_hours"] is not None and profile.max_hours is not None:
            headroom = min(5, max(0, int(profile.max_hours - req["duration_hours"])))
            points = 10 + headroom
            score += points
            reasons.append({
                "kind": "duration", "points": points,
                "label": "указанный лимит покрывает длительность",
                "source_fragment": f"max_hours: {profile.max_hours:g}",
            })
        return score, reasons

    @staticmethod
    def _structured_evidence(profile: Profile, req: dict[str, Any]) -> str:
        duration = "без заданного лимита" if profile.max_hours is None else f"до {profile.max_hours:g} ч"
        return (
            f"структурные поля: формат «{req['event_format']}», languages: "
            f"{' | '.join(profile.languages)}, длительность {duration}"
        )

    @classmethod
    def _reason(
        cls, profile: Profile, req: dict[str, Any], score: int, reasons: list[dict[str, Any]],
    ) -> str:
        price = f"{profile.price_from_kzt:,}".replace(",", " ")
        first = (
            f"Профиль «{profile.anon_name}» свободен {req['event_date']}, работает в городе "
            f"{profile.city} и принимает формат «{req['event_format']}» по категории "
            f"«{req['category']}»; цена от {price} ₸ укладывается в бюджет, релевантность — {score}."
        )
        if reasons:
            details = "; ".join(
                f"{reason['label']} (+{reason['points']}): «{reason['source_fragment']}»"
                for reason in reasons
            )
            second = f"На баллы повлияли: {details}."
        else:
            second = (
                "Описание не дало подтверждённого совпадения; рекомендацию обосновывают "
                + cls._structured_evidence(profile, req) + "."
            )
        return first + " " + second

    def recommend(self, request: dict[str, Any]) -> dict[str, Any]:
        req = self._validate(request)
        base = [p for p in self.profiles if p.city == req["city"] and req["category"] in p.categories]
        failures = {
            "busy": sum(req["event_date"] in p.busy_dates for p in base),
            "format": sum(req["event_format"] not in p.event_formats for p in base),
            "budget": sum(p.price_from_kzt > req["budget_kzt"] for p in base),
            "language": sum(bool(req["language"]) and req["language"] not in p.languages for p in base),
            "duration": sum(
                req["duration_hours"] is not None
                and p.max_hours is not None
                and req["duration_hours"] > p.max_hours
                for p in base
            ),
        }
        eligible = [
            p for p in base
            if req["event_date"] not in p.busy_dates
            and req["event_format"] in p.event_formats
            and p.price_from_kzt <= req["budget_kzt"]
            and (not req["language"] or req["language"] in p.languages)
            and (req["duration_hours"] is None or p.max_hours is None or req["duration_hours"] <= p.max_hours)
        ]
        scored = [(p, *self._score(p, req)) for p in eligible]
        scored.sort(key=lambda item: (-item[1], item[0].price_from_kzt, item[0].id))
        cards = []
        for p, score, score_reasons in scored[:3]:
            cards.append({
                "id": p.id,
                "name": p.anon_name,
                "matching_category": req["category"],
                "city": p.city,
                "price_from_kzt": p.price_from_kzt,
                "synthetic": p.synthetic,
                "city_imputed": p.city_imputed,
                "price_imputed": p.price_imputed,
                "relevance_score": score,
                "score_reasons": score_reasons,
                "explanation": self._reason(p, req, score, score_reasons),
            })
        if not base:
            outcome = "no_city_category"
            summary = f"В городе {req['city']} нет подрядчиков категории «{req['category']}»."
        elif not eligible:
            outcome = "none_eligible"
            summary = "Подрядчики есть, но ни один не соответствует всем условиям."
        else:
            outcome = "found"
            count = len(cards)
            summary = f"Найдено рекомендаций: {count}."
            if count < 3:
                summary += f" Меньше трёх, потому что всем условиям соответствуют только {len(eligible)}."
        return {
            "outcome": outcome,
            "summary": summary,
            "base_count": len(base),
            "eligible_count": len(eligible),
            "rejections": failures,
            "recommendations": cards,
            "request": req,
        }

    def compare(self, request: dict[str, Any], comparison_date: str) -> dict[str, Any]:
        first = self.recommend(request)
        second_request = dict(request)
        second_request["event_date"] = comparison_date
        second = self.recommend(second_request)
        first_ids = {x["id"]: x for x in first["recommendations"]}
        second_ids = {x["id"]: x for x in second["recommendations"]}
        entered_top3 = sorted(second_ids[x]["name"] for x in second_ids.keys() - first_ids.keys())
        left_top3 = sorted(first_ids[x]["name"] for x in first_ids.keys() - second_ids.keys())
        d1, d2 = first["request"]["event_date"], second["request"]["event_date"]
        base = [
            p for p in self.profiles
            if p.city == first["request"]["city"]
            and first["request"]["category"] in p.categories
        ]
        became_free = sorted(p.anon_name for p in base if d1 in p.busy_dates and d2 not in p.busy_dates)
        became_busy = sorted(p.anon_name for p in base if d1 not in p.busy_dates and d2 in p.busy_dates)
        return {
            "primary": first,
            "comparison": second,
            "ranking_changes": {
                "entered_top3": entered_top3,
                "left_top3": left_top3,
            },
            "availability_changes": {
                "became_free": became_free,
                "became_busy": became_busy,
                "text": self._change_text(first, second, entered_top3, left_top3, became_free, became_busy),
            },
        }

    @staticmethod
    def _change_text(
        first: dict[str, Any], second: dict[str, Any],
        entered: list[str], left: list[str], became_free: list[str], became_busy: list[str],
    ) -> str:
        d1, d2 = first["request"]["event_date"], second["request"]["event_date"]
        ranking = []
        if entered:
            ranking.append(f"вошли: {', '.join(entered)}")
        if left:
            ranking.append(f"вышли: {', '.join(left)}")
        parts = ["Изменение топ-3 — " + "; ".join(ranking) + "."] if ranking else ["Состав топ-3 не изменился."]
        calendar = []
        if became_free:
            calendar.append(f"стали свободны: {', '.join(became_free)}")
        if became_busy:
            calendar.append(f"стали заняты: {', '.join(became_busy)}")
        if calendar:
            parts.append(f"По busy_dates между {d1} и {d2} " + "; ".join(calendar) + ".")
        else:
            parts.append(f"По busy_dates между {d1} и {d2} смены занятости нет.")
        return " ".join(parts)
