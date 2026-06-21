from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.models.word import Word
from backend.app.models.writing_submission import WritingSubmission
from backend.app.services.openai_service import (
    generate_writing_challenge,
    correct_writing_challenge,
)


def get_required_words(db: Session, limit: int = 3) -> list[str]:
    words = (
        db.query(Word)
        .filter(Word.vocabulary.isnot(None))
        .order_by(
            (Word.priority - Word.memorize_count).desc(),
            func.rand()
        )
        .limit(limit)
        .all()
    )

    return [word.vocabulary for word in words if word.vocabulary]


def create_writing_challenge(db: Session) -> dict:
    required_words = get_required_words(db)

    if not required_words:
        return {
            "topic": "Describe your day in English.",
            "required_words": [],
            "recommended_grammar": "past tense",
            "target_words": "80-120 words",
            "instruction_ko": "단어장이 비어 있습니다. 오늘 하루를 영어로 작성해보세요.",
        }

    return generate_writing_challenge(required_words)


def submit_writing_challenge(
    db: Session,
    topic: str,
    required_words_text: str,
    original_text: str,
) -> dict:
    required_words = [
        word.strip()
        for word in required_words_text.split(",")
        if word.strip()
    ]

    feedback = correct_writing_challenge(
        original_text=original_text,
        topic=topic,
        required_words=required_words,
    )

    submission = WritingSubmission(
        topic=topic,
        required_words=required_words,
        original_text=original_text,
        corrected_text=feedback.get("corrected_text"),
        natural_text=feedback.get("natural_text"),
        feedback_json=feedback.get("feedback"),
        grammar_tags=feedback.get("grammar_tags"),
        used_words=feedback.get("used_words"),
        missing_words=feedback.get("missing_words"),
        grammar_score=feedback.get("grammar_score"),
        vocab_score=feedback.get("vocab_score"),
    )

    db.add(submission)
    db.commit()
    db.refresh(submission)

    challenge = {
        "topic": topic,
        "required_words": required_words,
        "recommended_grammar": None,
        "target_words": "80-120 words",
        "instruction_ko": "아래 첨삭 결과를 확인하세요.",
    }

    return {
        "challenge": challenge,
        "feedback": feedback,
        "submission": submission,
    }