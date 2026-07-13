import random
from datetime import date

from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.models.quiz_log import QuizLog
from backend.app.models.word import Word
from backend.app.services.tts_service import generate_tts_audio



router = APIRouter()


def get_wrong_counts(db: Session) -> dict[int, int]:
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

    db_words = db.query(Word).all()
    wrong_counts = get_wrong_counts(db)

    if mode == "today":
        today = date.today()

        db_words = [
            word
            for word in db_words
            if getattr(word, "created_at", None)
            and word.created_at.date() == today
        ]

    if mode == "priority":
        db_words.sort(
            key=lambda word: (
                getattr(word, "priority", 0) or 0,
                word.id,
            ),
            reverse=True,
        )

    elif mode == "memorize":
        db_words.sort(
            key=lambda word: (
                getattr(word, "memorize_count", 0) or 0,
                -word.id,
            )
        )

    elif mode == "wrong":
        db_words.sort(
            key=lambda word: (
                wrong_counts.get(word.id, 0),
                word.id,
            ),
            reverse=True,
        )

        db_words = [
            word
            for word in db_words
            if wrong_counts.get(word.id, 0) > 0
        ]

    elif mode == "recent":
        db_words.sort(
            key=lambda word: word.id,
            reverse=True,
        )

    else:
        random.shuffle(db_words)

    words = [
        {
            "id": word.id,
            "vocabulary": word.vocabulary or "",
            "definition": word.definition or "",
            "sentence": word.sentence or "",
            "synonyms": word.synonyms or "",
            "usage_note": word.usage_note or "",
            "priority": getattr(word, "priority", 0) or 0,
            "memorize_count": (
                getattr(word, "memorize_count", 0) or 0
            ),
            "wrong_count": wrong_counts.get(word.id, 0),
        }
        for word in db_words
        if word.vocabulary
    ]

    return templates.TemplateResponse(
        request=request,
        name="flashcards.html",
        context={
            "request": request,
            "words": words,
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