
import random
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session, selectinload

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.models.quiz_log import QuizLog
from backend.app.models.word import Word
from backend.app.services.tts_service import generate_tts_audio


router = APIRouter()


def get_wrong_counts(db: Session) -> dict[int, int]:
    """
    아직 퀴즈가 word_sense_id 기준으로 완전히 전환되지 않았으므로,
    현재 단계에서는 기존 word_id별 오답 수를 사용한다.
    """
    rows = (
        db.query(
            QuizLog.word_id,
            func.sum(
                case(
                    (QuizLog.is_correct.is_(False), 1),
                    else_=0,
                )
            ).label("wrong_count"),
        )
        .group_by(QuizLog.word_id)
        .all()
    )

    return {
        word_id: int(wrong_count or 0)
        for word_id, wrong_count in rows
    }


def get_words_with_senses(db: Session) -> list[Word]:
    return (
        db.query(Word)
        .options(selectinload(Word.senses))
        .all()
    )


def sort_words(
    words: list[Word],
    mode: str,
    wrong_counts: dict[int, int],
) -> list[Word]:
    if mode == "today":
        today = date.today()

        words = [
            word
            for word in words
            if getattr(word, "created_at", None)
            and word.created_at.date() == today
        ]

    if mode == "priority":
        words.sort(
            key=lambda word: (
                getattr(word, "priority", 0) or 0,
                word.id,
            ),
            reverse=True,
        )

    elif mode == "memorize":
        words.sort(
            key=lambda word: (
                getattr(word, "memorize_count", 0) or 0,
                -word.id,
            )
        )

    elif mode == "wrong":
        words.sort(
            key=lambda word: (
                wrong_counts.get(word.id, 0),
                word.id,
            ),
            reverse=True,
        )

        words = [
            word
            for word in words
            if wrong_counts.get(word.id, 0) > 0
        ]

    elif mode == "recent":
        words.sort(
            key=lambda word: word.id,
            reverse=True,
        )

    elif mode == "random":
        random.shuffle(words)

    return words


def build_flashcard_items(
    words: list[Word],
    wrong_counts: dict[int, int],
    mode: str,
) -> list[dict]:
    cards = []

    for word in words:
        if not word.vocabulary:
            continue

        senses = list(word.senses or [])

        if not senses:
            cards.append(
                {
                    "id": f"word-{word.id}",
                    "word_id": word.id,
                    "sense_id": None,
                    "vocabulary": word.vocabulary or "",
                    "definition": word.definition or "",
                    "sentence": word.sentence or "",
                    "synonyms": word.synonyms or "",
                    "usage_note": word.usage_note or "",
                    "part_of_speech": "",
                    "english_definition": "",
                    "priority": getattr(word, "priority", 0) or 0,
                    "memorize_count": (
                        getattr(word, "memorize_count", 0) or 0
                    ),
                    "wrong_count": wrong_counts.get(word.id, 0),
                }
            )
            continue

        for sense in senses:
            # 오른쪽 패널에 보여줄 정보가 하나도 없는 sense는 제외한다.
            has_detail = any(
                [
                    sense.sentence,
                    sense.synonyms,
                    sense.usage_note,
                ]
            )

            if not has_detail:
                continue

            cards.append(
                {
                    "id": sense.id,
                    "word_id": word.id,
                    "sense_id": sense.id,
                    "vocabulary": word.vocabulary or "",
                    "definition": sense.korean_meaning or "",
                    "sentence": sense.sentence or "",
                    "synonyms": sense.synonyms or "",
                    "usage_note": sense.usage_note or "",
                    "part_of_speech": sense.part_of_speech or "",
                    "english_definition": (
                        sense.english_definition or ""
                    ),
                    "is_primary": bool(sense.is_primary),
                    "display_order": sense.display_order or 0,
                    "priority": getattr(word, "priority", 0) or 0,
                    "memorize_count": (
                        getattr(word, "memorize_count", 0) or 0
                    ),
                    "wrong_count": wrong_counts.get(word.id, 0),
                }
            )

    if mode == "random":
        random.shuffle(cards)

    return cards


@router.get("/flashcards")
def flashcards_page(
    request: Request,
    mode: str = Query("random"),
    db: Session = Depends(get_db),
):
    allowed_modes = {
        "random",
        "priority",
        "memorize",
        "wrong",
        "recent",
        "today",
    }

    if mode not in allowed_modes:
        mode = "random"

    db_words = get_words_with_senses(db)
    wrong_counts = get_wrong_counts(db)

    sorted_words = sort_words(
        words=db_words,
        mode=mode,
        wrong_counts=wrong_counts,
    )

    cards = build_flashcard_items(
        words=sorted_words,
        wrong_counts=wrong_counts,
        mode=mode,
    )

    return templates.TemplateResponse(
        request=request,
        name="flashcards.html",
        context={
            "request": request,
            "words": cards,
            "mode": mode,
        },
    )


class FlashcardTTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    audio_type: str = "word"


@router.post("/api/flashcards/tts")
def flashcard_tts(
    payload: FlashcardTTSRequest,
):
    allowed_audio_types = {
        "word",
        "sentence",
    }

    audio_type = (
        payload.audio_type
        if payload.audio_type in allowed_audio_types
        else "word"
    )

    audio_path = generate_tts_audio(
        text=payload.text,
        audio_type=audio_type,
        voice="marin",
    )

    return FileResponse(
        path=audio_path,
        media_type="audio/mpeg",
        filename=audio_path.name,
    )