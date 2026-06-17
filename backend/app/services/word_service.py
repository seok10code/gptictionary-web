import json
from sqlalchemy.orm import Session

from backend.app.models.word import Word
from backend.app.schemas.word import WordCreate, WordUpdate
from backend.app.services.openai_service import generate_word_info


def get_words(db: Session):
    return db.query(Word).all()


def get_word_by_id(db: Session, word_id: int):
    return db.query(Word).filter(Word.id == word_id).first()


def get_word_by_vocabulary(db: Session, vocabulary: str):
    return db.query(Word).filter(Word.vocabulary == vocabulary).first()


def create_word(db: Session, word: WordCreate):
    db_word = Word(**word.model_dump())
    db.add(db_word)
    db.commit()
    db.refresh(db_word)
    return db_word


def update_word(db: Session, word_id: int, word: WordUpdate):
    db_word = get_word_by_id(db, word_id)

    if not db_word:
        return None

    update_data = word.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_word, key, value)

    db.commit()
    db.refresh(db_word)

    return db_word


async def search_word(db: Session, vocabulary: str):
    vocabulary = vocabulary.strip()

    existing_word = get_word_by_vocabulary(db, vocabulary)

    if existing_word:
        return {
            "found": True,
            "created": False,
            "word": existing_word
        }

    ai_result = await generate_word_info(vocabulary)

    if not ai_result.get("valid"):
        return {
            "found": False,
            "created": False,
            "message": "유효한 영어 단어 또는 표현을 찾지 못했습니다."
        }

    synonyms = ai_result.get("synonyms") or []
    antonyms = ai_result.get("antonyms") or []
    examples = ai_result.get("examples") or []
    entries = ai_result.get("entries") or []
    raw_wiktionary = ai_result.get("raw_wiktionary") or {}

    if isinstance(synonyms, list):
        synonyms_text = ", ".join(synonyms)
    else:
        synonyms_text = synonyms

    if isinstance(antonyms, list):
        antonyms_text = ", ".join(antonyms)
    else:
        antonyms_text = antonyms

    word_create = WordCreate(
        vocabulary=ai_result.get("vocabulary", vocabulary),
        definition=ai_result.get("definition", ""),
        sentence=ai_result.get("sentence", ""),
        synonyms=synonyms_text,
        usage_note=ai_result.get("usage_note", ""),

        entries_json=json.dumps(entries, ensure_ascii=False),
        pronunciation=ai_result.get("pronunciation", ""),
        antonyms=antonyms_text,
        examples_json=json.dumps(examples, ensure_ascii=False),
        etymology_summary=ai_result.get("etymology_summary", ""),
        raw_wiktionary_json=json.dumps(raw_wiktionary, ensure_ascii=False),
    )

    created_word = create_word(db, word_create)

    return {
        "found": True,
        "created": True,
        "word": created_word
    }


def save_extracted_word(db: Session, word: WordCreate):
    clean_vocabulary = word.vocabulary.strip().lower()

    if not is_valid_input(clean_vocabulary):
        return {
            "valid": False,
            "message": "올바른 영어 단어 또는 표현이 아닙니다."
        }

    existing_word = get_word_by_vocabulary(
        db=db,
        vocabulary=clean_vocabulary
    )

    if existing_word:
        return {
            "valid": True,
            "word": existing_word,
            "source": "db",
            "message": "이미 저장된 단어입니다."
        }

    word.vocabulary = clean_vocabulary

    new_word = create_word(
        db=db,
        word=word
    )

    return {
        "valid": True,
        "word": new_word,
        "source": "question_note",
        "message": "저장되었습니다."
    }