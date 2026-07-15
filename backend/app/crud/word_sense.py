import json
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.app.models.word_sense import WordSense


def safe_json_loads(value, default):
    if not value:
        return default

    if isinstance(value, (list, dict)):
        return value

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def normalize_korean_text(value: str) -> str:
    return re.sub(
        r"[\s,./;:·()\-_]+",
        "",
        str(value or "").strip(),
    )


def split_korean_terms(value: str) -> list[str]:
    terms = re.split(
        r"[,/;·]| 또는 | 혹은 |\(|\)",
        str(value or ""),
    )

    result = []

    for term in terms:
        clean = normalize_korean_text(term)

        if clean and clean not in result:
            result.append(clean)

    return result


def get_senses_by_word_id(
    db: Session,
    word_id: int,
) -> list[WordSense]:
    return (
        db.query(WordSense)
        .filter(WordSense.word_id == word_id)
        .order_by(
            WordSense.display_order.asc(),
            WordSense.id.asc(),
        )
        .all()
    )


def get_sense_by_id(
    db: Session,
    sense_id: int,
) -> WordSense | None:
    return (
        db.query(WordSense)
        .options(joinedload(WordSense.word))
        .filter(WordSense.id == sense_id)
        .first()
    )


def get_sense_by_key(
    db: Session,
    word_id: int,
    sense_key: str,
) -> WordSense | None:
    return (
        db.query(WordSense)
        .filter(
            WordSense.word_id == word_id,
            WordSense.sense_key == sense_key,
        )
        .first()
    )


def _calculate_match_score(
    sense: WordSense,
    normalized_query: str,
) -> int:
    meaning_terms = split_korean_terms(
        sense.korean_meaning
    )

    keywords = safe_json_loads(
        sense.search_keywords_json,
        [],
    )

    keyword_terms = [
        normalize_korean_text(value)
        for value in keywords
        if normalize_korean_text(value)
    ]

    all_terms = list(
        dict.fromkeys(
            meaning_terms + keyword_terms
        )
    )

    if normalized_query in meaning_terms:
        return 1000

    if normalized_query in keyword_terms:
        return 950

    if normalize_korean_text(
        sense.korean_meaning
    ) == normalized_query:
        return 900

    if any(
        term.startswith(normalized_query)
        for term in all_terms
    ):
        return 800

    if any(
        normalized_query.startswith(term)
        for term in all_terms
    ):
        return 750

    if any(
        normalized_query in term
        for term in all_terms
    ):
        return 650

    if any(
        term in normalized_query
        for term in all_terms
    ):
        return 600

    return 0


def search_senses_by_korean(
    db: Session,
    korean_query: str,
    limit: int = 20,
) -> list[WordSense]:
    clean_query = korean_query.strip()

    if not clean_query:
        return []

    normalized_query = normalize_korean_text(
        clean_query
    )

    broad_results = (
        db.query(WordSense)
        .options(joinedload(WordSense.word))
        .filter(
            or_(
                WordSense.korean_meaning.contains(
                    clean_query
                ),
                WordSense.search_keywords_json.contains(
                    clean_query
                ),
            )
        )
        .limit(max(limit * 5, 50))
        .all()
    )

    scored_results = []

    for sense in broad_results:
        score = _calculate_match_score(
            sense,
            normalized_query,
        )

        if score <= 0:
            continue

        scored_results.append(
            (
                score,
                bool(sense.is_primary),
                -int(sense.display_order or 0),
                -int(sense.id),
                sense,
            )
        )

    scored_results.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3],
        ),
        reverse=True,
    )

    seen_ids = set()
    results = []

    for _, _, _, _, sense in scored_results:
        if sense.id in seen_ids:
            continue

        seen_ids.add(sense.id)
        results.append(sense)

        if len(results) >= limit:
            break

    return results


def word_sense_to_candidate(
    sense: WordSense,
) -> dict:
    return {
        "word": sense.word.vocabulary,
        "meaning_ko": sense.korean_meaning,
        "usage": (
            sense.sentence
            or sense.english_definition
            or ""
        ),
        "part_of_speech": sense.part_of_speech,
        "sense_id": sense.id,
        "source": "db",
    }
