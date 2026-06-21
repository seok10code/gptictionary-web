from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.core.templates import templates
from backend.app.services.writing_service import (
    create_writing_challenge,
    submit_writing_challenge,
)

router = APIRouter(prefix="/writing", tags=["writing"])


@router.get("")
def writing_page(
    request: Request,
    db: Session = Depends(get_db),
):
    challenge = create_writing_challenge(db)

    return templates.TemplateResponse(
        request,
        "writing.html",
        {
            "challenge": challenge,
            "result": None,
            "original_text": "",
        },
    )


@router.post("")
def submit_writing(
    request: Request,
    topic: str = Form(...),
    required_words: str = Form(""),
    original_text: str = Form(...),
    db: Session = Depends(get_db),
):
    data = submit_writing_challenge(
        db=db,
        topic=topic,
        required_words_text=required_words,
        original_text=original_text,
    )

    return templates.TemplateResponse(
        request,
        "writing.html",
        {
            "challenge": data["challenge"],
            "result": data["feedback"],
            "original_text": original_text,
        },
    )