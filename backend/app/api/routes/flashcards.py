import random
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense
from backend.app.services.tts_service import generate_tts_audio


router = APIRouter()


def get_flashcard_senses(
    db: Session,
    mode: str,
):
    query = (
        db.query(WordSense, Word)
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            Word.vocabulary.isnot(None),
            Word.vocabulary != "",
            WordSense.korean_meaning.isnot(None),
            WordSense.korean_meaning != "",
        )
    )

    if mode == "today":
        start = datetime.combine(
            date.today(),
            time.min,
        )

        query = query.filter(
            WordSense.created_at >= start
        )

    if mode == "priority":
        query = query.order_by(
            WordSense.priority.desc(),
            WordSense.total_wrong.desc(),
            WordSense.id.desc(),
        )

    elif mode == "memorize":
        query = query.order_by(
            WordSense.memorize_count.asc(),
            WordSense.total_wrong.desc(),
            WordSense.id.desc(),
        )

    elif mode == "wrong":
        query = (
            query
            .filter(
                WordSense.total_wrong > 0
            )
            .order_by(
                WordSense.total_wrong.desc(),
                WordSense.memorize_count.asc(),
                WordSense.id.desc(),
            )
        )

    elif mode == "recent":
        query = query.order_by(
            WordSense.id.desc()
        )

    else:
        query = query.order_by(
            WordSense.id.asc()
        )

    rows = query.all()

    if mode == "random":
        random.shuffle(rows)

    return rows


def build_flashcard_items(rows):
    cards = []

    for sense, word in rows:
        has_detail = any(
            [
                sense.sentence,
                sense.english_definition,
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
                "priority": sense.priority or 0,
                "memorize_count": (
                    sense.memorize_count or 0
                ),
                "correct_count": (
                    sense.total_correct or 0
                ),
                "wrong_count": (
                    sense.total_wrong or 0
                ),
            }
        )

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

    rows = get_flashcard_senses(
        db=db,
        mode=mode,
    )

    cards = build_flashcard_items(rows)

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
    text: str = Field(
        min_length=1,
        max_length=500,
    )
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
