import json
import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense
from backend.app.schemas.word import WordCreate, WordUpdate
from backend.app.services.openai_service import generate_word_info
from backend.app.crud.quiz import generate_quiz_question_for_word
from backend.app.crud.word_sense import (
    get_sense_by_key,
    get_senses_by_word_id,
    normalize_korean_text,
)


def get_words(db: Session):
    return db.query(Word).all()


def get_word_by_id(db: Session, word_id: int):
    return db.query(Word).filter(Word.id == word_id).first()


def get_word_by_vocabulary(db: Session, vocabulary: str):
    clean_vocabulary = vocabulary.strip().lower()

    return (
        db.query(Word)
        .filter(Word.vocabulary == clean_vocabulary)
        .first()
    )


def create_word(db: Session, word: WordCreate):
    db_word = Word(**word.model_dump())
    db.add(db_word)
    db.flush()
    return db_word


def update_word(db: Session, word_id: int, word: WordUpdate):
    db_word = get_word_by_id(db, word_id)

    if not db_word:
        return None

    for key, value in word.model_dump(exclude_unset=True).items():
        setattr(db_word, key, value)

    db.commit()
    db.refresh(db_word)

    return db_word


def _normalize_text_list(value) -> str:
    if isinstance(value, list):
        return ", ".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    return str(value or "").strip()


def _split_korean_meanings(value: str) -> set[str]:
    values = re.split(
        r"[,/;·]| 또는 | 혹은 |\(|\)",
        str(value or ""),
    )

    return {
        normalize_korean_text(item)
        for item in values
        if normalize_korean_text(item)
    }


def _normalize_part_of_speech(value: str) -> str:
    clean = str(value or "").strip().lower()

    aliases = {
        "명사": "noun",
        "n": "noun",
        "동사": "verb",
        "v": "verb",
        "형용사": "adjective",
        "adj": "adjective",
        "부사": "adverb",
        "adv": "adverb",
        "표현": "expression",
        "구": "expression",
        "숙어": "expression",
        "phrase": "expression",
        "phrasal verb": "verb",
    }

    return aliases.get(clean, clean)


def _canonical_part_of_speech(
    value: str,
    korean_meaning: str = "",
    sense_key: str = "",
) -> str:
    normalized = _normalize_part_of_speech(value)
    meaning = normalize_korean_text(korean_meaning)
    key = str(sense_key or "").strip().lower()

    adverb_markers = (
        "오른쪽으로",
        "왼쪽으로",
        "위로",
        "아래로",
        "앞으로",
        "뒤로",
    )

    if (
        normalized == "verb"
        and (
            any(marker in meaning for marker in adverb_markers)
            or "turning_right" in key
            or key.endswith("_adverb")
        )
    ):
        return "adverb"

    display_names = {
        "noun": "Noun",
        "verb": "Verb",
        "adjective": "Adjective",
        "adverb": "Adverb",
        "expression": "Expression",
    }

    return display_names.get(
        normalized,
        str(value or "Unknown").strip() or "Unknown",
    )


def _make_sense_key(entry: dict, index: int) -> str:
    explicit_key = str(
        entry.get("sense_key") or ""
    ).strip().lower()

    if explicit_key:
        return re.sub(
            r"[^a-z0-9가-힣_]+",
            "_",
            explicit_key,
        )[:220]

    raw = (
        f"{entry.get('part_of_speech', 'unknown')}_"
        f"{entry.get('korean_meaning', '')}"
    ).lower()

    key = re.sub(
        r"[^a-z0-9가-힣]+",
        "_",
        raw,
    ).strip("_")

    return (key or f"sense_{index + 1}")[:220]


def _meaning_similarity(
    left: str,
    right: str,
) -> float:
    left_tokens = _split_korean_meanings(left)
    right_tokens = _split_korean_meanings(right)

    if not left_tokens or not right_tokens:
        return 0.0

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

            ratio = SequenceMatcher(
                None,
                left_token,
                right_token,
            ).ratio()

            best = max(best, ratio)

    return best


def _find_equivalent_sense(
    db: Session,
    word_id: int,
    part_of_speech: str,
    korean_meaning: str,
    exclude_sense_id: int | None = None,
) -> WordSense | None:
    normalized_pos = _normalize_part_of_speech(
        part_of_speech
    )

    senses = get_senses_by_word_id(
        db,
        word_id,
    )

    best_match = None
    best_score = 0.0

    for sense in senses:
        if (
            exclude_sense_id is not None
            and sense.id == exclude_sense_id
        ):
            continue

        sense_pos = _normalize_part_of_speech(
            sense.part_of_speech
        )

        if sense_pos != normalized_pos:
            continue

        score = _meaning_similarity(
            sense.korean_meaning,
            korean_meaning,
        )

        if score > best_score:
            best_match = sense
            best_score = score

    if best_score >= 0.78:
        return best_match

    return None


def _sense_matches_requested(
    sense: WordSense,
    requested_meaning: str,
    requested_part_of_speech: str,
) -> bool:
    requested_meaning_norm = normalize_korean_text(
        requested_meaning
    )

    meaning_matches = (
        not requested_meaning_norm
        or _meaning_similarity(
            sense.korean_meaning,
            requested_meaning,
        ) >= 0.78
    )

    requested_pos_norm = _normalize_part_of_speech(
        requested_part_of_speech
    )
    sense_pos_norm = _normalize_part_of_speech(
        sense.part_of_speech
    )

    pos_matches = (
        not requested_pos_norm
        or requested_pos_norm == sense_pos_norm
    )

    return meaning_matches and pos_matches


def find_matching_sense(
    db: Session,
    word: Word,
    requested_meaning: str = "",
    requested_part_of_speech: str = "",
) -> WordSense | None:
    for sense in get_senses_by_word_id(db, word.id):
        if _sense_matches_requested(
            sense,
            requested_meaning,
            requested_part_of_speech,
        ):
            return sense

    return None


def _prefer_longer_text(
    current: str | None,
    incoming: str | None,
) -> str | None:
    current_clean = str(current or "").strip()
    incoming_clean = str(incoming or "").strip()

    if len(incoming_clean) > len(current_clean):
        return incoming_clean or None

    return current_clean or None


def _merge_csv_text(
    current: str | None,
    incoming: str | None,
) -> str | None:
    values = []

    for source in [current, incoming]:
        for value in str(source or "").split(","):
            clean = value.strip()

            if clean and clean.lower() not in {
                item.lower()
                for item in values
            }:
                values.append(clean)

    return ", ".join(values) or None


def _merge_json_lists(
    current_json: str | None,
    incoming_values,
) -> str:
    current_values = []

    if current_json:
        try:
            parsed = json.loads(current_json)

            if isinstance(parsed, list):
                current_values = parsed
        except (json.JSONDecodeError, TypeError):
            current_values = []

    if not isinstance(incoming_values, list):
        incoming_values = []

    merged = []

    for value in current_values + incoming_values:
        clean = str(value).strip()

        if clean and clean not in merged:
            merged.append(clean)

    return json.dumps(
        merged,
        ensure_ascii=False,
    )


def _merge_json_items(
    current_json: str | None,
    incoming_values,
) -> str:
    """
    JSON 배열을 구조를 보존한 채 병합한다.

    conversation처럼 dict가 들어 있는 배열과
    writing_examples처럼 문자열이 들어 있는 배열 모두 지원한다.
    """
    current_values = []

    if current_json:
        try:
            parsed = json.loads(current_json)

            if isinstance(parsed, list):
                current_values = parsed
        except (json.JSONDecodeError, TypeError):
            current_values = []

    if not isinstance(incoming_values, list):
        incoming_values = []

    merged = []
    seen = set()

    for value in current_values + incoming_values:
        try:
            key = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
        except (TypeError, ValueError):
            key = str(value)

        if key in seen:
            continue

        seen.add(key)
        merged.append(value)

    return json.dumps(
        merged,
        ensure_ascii=False,
    )


def _merge_korean_meanings(
    current: str,
    incoming: str,
) -> str:
    values = []

    for source in [current, incoming]:
        for value in re.split(
            r"[,/;·]",
            str(source or ""),
        ):
            clean = value.strip()

            if (
                clean
                and normalize_korean_text(clean)
                not in {
                    normalize_korean_text(item)
                    for item in values
                }
            ):
                values.append(clean)

    return ", ".join(values)


def _update_existing_sense(
    sense: WordSense,
    entry: dict,
    index: int,
):
    incoming_meaning = str(
        entry.get("korean_meaning") or ""
    ).strip()

    sense.korean_meaning = _merge_korean_meanings(
        sense.korean_meaning,
        incoming_meaning,
    )

    definitions = entry.get("definitions") or []

    if isinstance(definitions, list):
        incoming_definition = "\n".join(
            str(value).strip()
            for value in definitions
            if str(value).strip()
        )
    else:
        incoming_definition = str(
            definitions or ""
        ).strip()

    sense.english_definition = _prefer_longer_text(
        sense.english_definition,
        incoming_definition,
    )

    sense.sentence = _prefer_longer_text(
        sense.sentence,
        entry.get("sentence"),
    )

    sense.usage_note = _prefer_longer_text(
        sense.usage_note,
        entry.get("usage_note"),
    )

    sense.conversation_json = _merge_json_items(
        sense.conversation_json,
        entry.get("conversation") or [],
    )

    sense.writing_examples_json = _merge_json_items(
        sense.writing_examples_json,
        entry.get("writing_examples") or [],
    )

    sense.synonyms = _merge_csv_text(
        sense.synonyms,
        _normalize_text_list(
            entry.get("synonyms")
        ),
    )

    sense.antonyms = _merge_csv_text(
        sense.antonyms,
        _normalize_text_list(
            entry.get("antonyms")
        ),
    )

    sense.examples_json = _merge_json_lists(
        sense.examples_json,
        entry.get("examples") or [],
    )

    keywords = entry.get("search_keywords") or []

    if not keywords:
        keywords = [
            value.strip()
            for value in re.split(
                r"[,/;·]",
                incoming_meaning,
            )
            if value.strip()
        ]

    sense.search_keywords_json = _merge_json_lists(
        sense.search_keywords_json,
        keywords,
    )

    sense.display_order = min(
        sense.display_order,
        index,
    )

    if index == 0:
        sense.is_primary = True

    return sense


def _merge_ai_senses(
    db: Session,
    word: Word,
    ai_result: dict,
) -> list[WordSense]:
    entries = ai_result.get("entries") or []
    merged = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

        korean_meaning = str(
            entry.get("korean_meaning") or ""
        ).strip()

        if not korean_meaning:
            continue

        raw_part_of_speech = str(
            entry.get("part_of_speech")
            or "Unknown"
        ).strip()

        sense_key = _make_sense_key(
            entry,
            index,
        )

        part_of_speech = _canonical_part_of_speech(
            raw_part_of_speech,
            korean_meaning,
            sense_key,
        )

        existing = get_sense_by_key(
            db,
            word.id,
            sense_key,
        )

        if not existing:
            existing = _find_equivalent_sense(
                db=db,
                word_id=word.id,
                part_of_speech=part_of_speech,
                korean_meaning=korean_meaning,
            )

        if existing:
            merged.append(
                _update_existing_sense(
                    existing,
                    entry,
                    index,
                )
            )
            continue

        definitions = entry.get("definitions") or []

        if isinstance(definitions, list):
            english_definition = "\n".join(
                str(value).strip()
                for value in definitions
                if str(value).strip()
            )
        else:
            english_definition = str(
                definitions or ""
            ).strip()

        keywords = entry.get(
            "search_keywords"
        ) or [
            value.strip()
            for value in re.split(
                r"[,/;·]",
                korean_meaning,
            )
            if value.strip()
        ]

        sense = WordSense(
            word_id=word.id,
            sense_key=sense_key,
            part_of_speech=part_of_speech,
            korean_meaning=korean_meaning,
            english_definition=(
                english_definition or None
            ),
            sentence=(
                str(
                    entry.get("sentence") or ""
                ).strip()
                or None
            ),
            usage_note=(
                str(
                    entry.get("usage_note") or ""
                ).strip()
                or None
            ),
            conversation_json=json.dumps(
                entry.get("conversation") or [],
                ensure_ascii=False,
            ),
            writing_examples_json=json.dumps(
                entry.get("writing_examples") or [],
                ensure_ascii=False,
            ),
            synonyms=(
                _normalize_text_list(
                    entry.get("synonyms")
                )
                or None
            ),
            antonyms=(
                _normalize_text_list(
                    entry.get("antonyms")
                )
                or None
            ),
            examples_json=json.dumps(
                entry.get("examples") or [],
                ensure_ascii=False,
            ),
            search_keywords_json=json.dumps(
                keywords,
                ensure_ascii=False,
            ),
            display_order=index,
            is_primary=index == 0,
        )

        db.add(sense)
        merged.append(sense)

    return merged


async def search_word(
    db: Session,
    vocabulary: str,
    requested_meaning: str | None = None,
    requested_part_of_speech: str | None = None,
    requested_usage: str | None = None,
):
    vocabulary = vocabulary.strip().lower()

    requested_meaning = (
        requested_meaning or ""
    ).strip()

    requested_part_of_speech = (
        requested_part_of_speech or ""
    ).strip()

    requested_usage = (
        requested_usage or ""
    ).strip()

    existing_word = get_word_by_vocabulary(
        db,
        vocabulary,
    )

    if existing_word:
        matching_sense = find_matching_sense(
            db,
            existing_word,
            requested_meaning,
            requested_part_of_speech,
        )

        if matching_sense or not (
            requested_meaning
            or requested_part_of_speech
            or requested_usage
        ):
            return {
                "found": True,
                "created": False,
                "word": existing_word,
                "selected_sense": matching_sense,
            }

    ai_result = await generate_word_info(
        vocabulary=vocabulary,
        requested_meaning=requested_meaning,
        requested_part_of_speech=(
            requested_part_of_speech
        ),
        requested_usage=requested_usage,
    )

    if not ai_result.get("valid"):
        return {
            "found": False,
            "created": False,
            "message": (
                "유효한 영어 단어 또는 표현을 "
                "찾지 못했습니다."
            ),
        }

    corrected_vocabulary = (
        ai_result.get(
            "vocabulary",
            vocabulary,
        )
        .strip()
        .lower()
    )

    word = get_word_by_vocabulary(
        db,
        corrected_vocabulary,
    )

    if not word:
        word = create_word(
            db,
            WordCreate(
                vocabulary=corrected_vocabulary,
                definition=ai_result.get(
                    "definition",
                    "",
                ),
                sentence=ai_result.get(
                    "sentence",
                    "",
                ),
                synonyms=_normalize_text_list(
                    ai_result.get("synonyms")
                ),
                usage_note=ai_result.get(
                    "usage_note",
                    "",
                ),
                entries_json=json.dumps(
                    ai_result.get("entries") or [],
                    ensure_ascii=False,
                ),
                pronunciation=ai_result.get(
                    "pronunciation",
                    "",
                ),
                antonyms=_normalize_text_list(
                    ai_result.get("antonyms")
                ),
                examples_json=json.dumps(
                    ai_result.get("examples") or [],
                    ensure_ascii=False,
                ),
                etymology_summary=ai_result.get(
                    "etymology_summary",
                    "",
                ),
                raw_wiktionary_json=json.dumps(
                    ai_result.get(
                        "raw_wiktionary"
                    )
                    or {},
                    ensure_ascii=False,
                ),
                corrected_from=ai_result.get(
                    "corrected_from"
                )
                or None,
            ),
        )

        created = True

    else:
        created = False

        if not word.pronunciation:
            word.pronunciation = ai_result.get(
                "pronunciation",
                "",
            )

        if not word.etymology_summary:
            word.etymology_summary = (
                ai_result.get(
                    "etymology_summary",
                    "",
                )
            )

        if not word.raw_wiktionary_json:
            word.raw_wiktionary_json = json.dumps(
                ai_result.get(
                    "raw_wiktionary"
                )
                or {},
                ensure_ascii=False,
            )

    _merge_ai_senses(
        db,
        word,
        ai_result,
    )

    db.commit()
    db.refresh(word)

    selected_sense = find_matching_sense(
        db,
        word,
        requested_meaning,
        requested_part_of_speech,
    )

    if created:
        try:
            generate_quiz_question_for_word(
                db,
                word,
            )
        except Exception as exc:
            print(
                "QUIZ AUTO CREATE ERROR:",
                repr(exc),
            )

    return {
        "found": True,
        "created": created,
        "word": word,
        "selected_sense": selected_sense,
    }


def save_extracted_word(
    db: Session,
    word: WordCreate,
):
    clean_vocabulary = (
        word.vocabulary
        .strip()
        .lower()
    )

    existing_word = get_word_by_vocabulary(
        db,
        clean_vocabulary,
    )

    if existing_word:
        return {
            "valid": True,
            "word": existing_word,
            "source": "db",
            "message": "이미 저장된 단어입니다.",
        }

    word.vocabulary = clean_vocabulary

    new_word = create_word(
        db,
        word,
    )

    db.commit()
    db.refresh(new_word)

    try:
        generate_quiz_question_for_word(
            db,
            new_word,
        )
    except Exception as exc:
        print(
            "QUIZ AUTO CREATE ERROR:",
            repr(exc),
        )

    return {
        "valid": True,
        "word": new_word,
        "source": "question_note",
        "message": "저장되었습니다.",
    }