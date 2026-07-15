import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from backend.app.db.database import SessionLocal
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense

def normalize_text(value: str) -> str:
    return re.sub(
        r"\s+",
        "",
        str(value or "").strip().lower(),
    )


def canonical_part_of_speech(
    part_of_speech: str,
    korean_meaning: str,
    sense_key: str,
) -> str:
    clean_pos = str(
        part_of_speech or ""
    ).strip().lower()

    aliases = {
        "명사": "Noun",
        "noun": "Noun",
        "n": "Noun",
        "동사": "Verb",
        "verb": "Verb",
        "v": "Verb",
        "형용사": "Adjective",
        "adjective": "Adjective",
        "adj": "Adjective",
        "부사": "Adverb",
        "adverb": "Adverb",
        "adv": "Adverb",
        "표현": "Expression",
        "expression": "Expression",
        "phrase": "Expression",
    }

    result = aliases.get(
        clean_pos,
        str(part_of_speech or "Unknown").strip(),
    )

    meaning = normalize_text(
        korean_meaning
    )

    key = str(
        sense_key or ""
    ).strip().lower()

    direction_adverb_markers = (
        "오른쪽으로",
        "왼쪽으로",
        "위로",
        "아래로",
        "앞으로",
        "뒤로",
    )

    if (
        result == "Verb"
        and (
            any(
                marker in meaning
                for marker in direction_adverb_markers
            )
            or key == "turning_right"
            or key.endswith("_adverb")
        )
    ):
        return "Adverb"

    return result


def normalize_meaning(
    korean_meaning: str,
    part_of_speech: str,
) -> str:
    clean = str(
        korean_meaning or ""
    ).strip()

    if (
        part_of_speech == "Adverb"
        and clean == "오른쪽으로 돌다"
    ):
        return "오른쪽으로"

    return clean


def main():
    db = SessionLocal()

    try:
        senses = (
            db.query(WordSense)
            .order_by(WordSense.id.asc())
            .all()
        )

        changed = 0

        for sense in senses:
            new_pos = canonical_part_of_speech(
                sense.part_of_speech,
                sense.korean_meaning,
                sense.sense_key,
            )

            new_meaning = normalize_meaning(
                sense.korean_meaning,
                new_pos,
            )

            if (
                new_pos == sense.part_of_speech
                and new_meaning == sense.korean_meaning
            ):
                continue

            print(
                f"[{sense.id}] "
                f"{sense.part_of_speech} / "
                f"{sense.korean_meaning} "
                f"-> {new_pos} / {new_meaning}"
            )

            sense.part_of_speech = new_pos
            sense.korean_meaning = new_meaning
            changed += 1

        db.commit()

        print("=" * 60)
        print(f"수정된 sense: {changed}")
        print("품사 정규화 완료")

    except Exception as exc:
        db.rollback()
        print(
            "NORMALIZE WORD SENSE POS ERROR:",
            repr(exc),
        )
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
