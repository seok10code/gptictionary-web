import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.database import SessionLocal
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense


def normalize(value: str) -> str:
    return re.sub(
        r"\s+",
        "",
        str(value or "").strip(),
    )


def normalize_pos(value: str) -> str:
    clean = str(value or "").strip().lower()

    aliases = {
        "명사": "noun",
        "동사": "verb",
        "형용사": "adjective",
        "부사": "adverb",
        "표현": "expression",
        "phrasal verb": "verb",
    }

    return aliases.get(clean, clean)


def split_meanings(value: str) -> set[str]:
    return {
        normalize(item)
        for item in re.split(
            r"[,/;·]| 또는 | 혹은 |\(|\)",
            str(value or ""),
        )
        if normalize(item)
    }


def similarity(left: str, right: str) -> float:
    left_tokens = split_meanings(left)
    right_tokens = split_meanings(right)

    if left_tokens & right_tokens:
        return 1.0

    best = 0.0

    for left_token in left_tokens:
        for right_token in right_tokens:
            if (
                left_token in right_token
                or right_token in left_token
            ):
                best = max(best, 0.9)
                continue

            best = max(
                best,
                SequenceMatcher(
                    None,
                    left_token,
                    right_token,
                ).ratio(),
            )

    return best


def merge_csv(left, right):
    result = []

    for source in [left, right]:
        for item in str(source or "").split(","):
            clean = item.strip()

            if clean and clean.lower() not in {
                value.lower()
                for value in result
            }:
                result.append(clean)

    return ", ".join(result) or None


def merge_json_list(left, right):
    values = []

    for raw in [left, right]:
        if not raw:
            continue

        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = []

        if not isinstance(parsed, list):
            continue

        for item in parsed:
            clean = str(item).strip()

            if clean and clean not in values:
                values.append(clean)

    return json.dumps(
        values,
        ensure_ascii=False,
    )


def prefer_longer(left, right):
    left_clean = str(left or "").strip()
    right_clean = str(right or "").strip()

    if len(right_clean) > len(left_clean):
        return right_clean or None

    return left_clean or None


def merge_meanings(left, right):
    values = []

    for source in [left, right]:
        for item in re.split(
            r"[,/;·]",
            str(source or ""),
        ):
            clean = item.strip()

            if (
                clean
                and normalize(clean)
                not in {
                    normalize(value)
                    for value in values
                }
            ):
                values.append(clean)

    return ", ".join(values)


def merge_into(
    target: WordSense,
    duplicate: WordSense,
):
    target.korean_meaning = merge_meanings(
        target.korean_meaning,
        duplicate.korean_meaning,
    )

    target.english_definition = prefer_longer(
        target.english_definition,
        duplicate.english_definition,
    )

    target.sentence = prefer_longer(
        target.sentence,
        duplicate.sentence,
    )

    target.usage_note = prefer_longer(
        target.usage_note,
        duplicate.usage_note,
    )

    target.synonyms = merge_csv(
        target.synonyms,
        duplicate.synonyms,
    )

    target.antonyms = merge_csv(
        target.antonyms,
        duplicate.antonyms,
    )

    target.examples_json = merge_json_list(
        target.examples_json,
        duplicate.examples_json,
    )

    target.search_keywords_json = merge_json_list(
        target.search_keywords_json,
        duplicate.search_keywords_json,
    )

    target.display_order = min(
        target.display_order,
        duplicate.display_order,
    )

    target.is_primary = bool(
        target.is_primary
        or duplicate.is_primary
    )


def main():
    db = SessionLocal()

    try:
        words = (
            db.query(Word)
            .order_by(Word.id.asc())
            .all()
        )

        deleted_count = 0

        for word in words:
            senses = (
                db.query(WordSense)
                .filter(
                    WordSense.word_id == word.id
                )
                .order_by(
                    WordSense.display_order.asc(),
                    WordSense.id.asc(),
                )
                .all()
            )

            consumed_ids = set()

            for index, target in enumerate(senses):
                if target.id in consumed_ids:
                    continue

                for duplicate in senses[index + 1:]:
                    if duplicate.id in consumed_ids:
                        continue

                    if normalize_pos(
                        target.part_of_speech
                    ) != normalize_pos(
                        duplicate.part_of_speech
                    ):
                        continue

                    score = similarity(
                        target.korean_meaning,
                        duplicate.korean_meaning,
                    )

                    if score < 0.78:
                        continue

                    print(
                        f"[{word.vocabulary}] "
                        f"병합: {target.id} "
                        f"'{target.korean_meaning}' "
                        f"<- {duplicate.id} "
                        f"'{duplicate.korean_meaning}' "
                        f"(score={score:.2f})"
                    )

                    merge_into(
                        target,
                        duplicate,
                    )

                    db.delete(duplicate)
                    consumed_ids.add(duplicate.id)
                    deleted_count += 1

        db.commit()

        print("=" * 60)
        print(f"삭제된 중복 sense: {deleted_count}")
        print("중복 sense 정리 완료")

    except Exception as exc:
        db.rollback()
        print(
            "DEDUPLICATE WORD SENSES ERROR:",
            repr(exc),
        )
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
