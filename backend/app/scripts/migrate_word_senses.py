import json
import re
import sys
from pathlib import Path

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.database import SessionLocal
from backend.app.models.word import Word
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


def normalize_part_of_speech(value: str) -> str:
    return str(value or "").strip() or "Unknown"


def make_sense_key(part_of_speech: str, korean_meaning: str, index: int) -> str:
    raw_value = f"{part_of_speech}_{korean_meaning}".lower()
    normalized = re.sub(r"[^a-z0-9가-힣]+", "_", raw_value).strip("_")
    return (normalized or f"sense_{index + 1}")[:220]


def build_search_keywords(korean_meaning: str) -> list[str]:
    if not korean_meaning:
        return []
    values = re.split(r"[,/;·]| 또는 | 혹은 ", korean_meaning)
    keywords = []
    for value in values:
        clean_value = value.strip()
        if clean_value and clean_value not in keywords:
            keywords.append(clean_value)
    return keywords


def migrate_word(db: Session, word: Word) -> tuple[int, int]:
    entries = safe_json_loads(word.entries_json, [])
    if not isinstance(entries, list):
        entries = []
    if not entries:
        entries = [{
            "part_of_speech": "Unknown",
            "korean_meaning": word.definition,
            "definitions": [],
        }]

    created_count = 0
    skipped_count = 0

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            skipped_count += 1
            continue

        part_of_speech = normalize_part_of_speech(entry.get("part_of_speech"))
        korean_meaning = str(
            entry.get("korean_meaning") or word.definition or ""
        ).strip()

        if not korean_meaning:
            skipped_count += 1
            continue

        definitions = entry.get("definitions") or []
        if isinstance(definitions, list):
            english_definition = "\n".join(
                str(value).strip() for value in definitions if str(value).strip()
            )
        else:
            english_definition = str(definitions).strip()

        sense_key = make_sense_key(part_of_speech, korean_meaning, index)

        existing_sense = (
            db.query(WordSense)
            .filter(
                WordSense.word_id == word.id,
                WordSense.sense_key == sense_key,
            )
            .first()
        )
        if existing_sense:
            skipped_count += 1
            continue

        is_primary = korean_meaning == word.definition or index == 0

        db.add(
            WordSense(
                word_id=word.id,
                sense_key=sense_key,
                part_of_speech=part_of_speech,
                korean_meaning=korean_meaning,
                english_definition=english_definition or None,
                sentence=word.sentence if is_primary else None,
                usage_note=word.usage_note if is_primary else None,
                synonyms=word.synonyms if is_primary else None,
                antonyms=word.antonyms if is_primary else None,
                examples_json=word.examples_json if is_primary else None,
                search_keywords_json=json.dumps(
                    build_search_keywords(korean_meaning),
                    ensure_ascii=False,
                ),
                display_order=index,
                is_primary=is_primary,
            )
        )
        created_count += 1

    return created_count, skipped_count


def main():
    db = SessionLocal()
    try:
        words = db.query(Word).order_by(Word.id.asc()).all()
        total_created = 0
        total_skipped = 0
        print(f"총 단어 수: {len(words)}")

        for word in words:
            created_count, skipped_count = migrate_word(db, word)
            total_created += created_count
            total_skipped += skipped_count
            print(
                f"[{word.id}] {word.vocabulary}: "
                f"생성 {created_count}, 건너뜀 {skipped_count}"
            )

        db.commit()
        print("=" * 60)
        print(f"생성된 sense: {total_created}")
        print(f"건너뛴 sense: {total_skipped}")
        print("마이그레이션 완료")
    except Exception as exc:
        db.rollback()
        print("WORD SENSE MIGRATION ERROR:", repr(exc))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
