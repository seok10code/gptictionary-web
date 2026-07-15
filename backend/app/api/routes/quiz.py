from fastapi import (
    APIRouter,
    Depends,
    Form,
    Request,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.crud.quiz import (
    generate_all_quiz_questions,
    generate_quiz_question,
    get_active_question,
    get_review_progress,
    make_hint,
    review_question,
    submit_answer,
)
from backend.app.db.database import get_db
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense


router = APIRouter()


def get_hint_for_question(
    db: Session,
    question,
):
    if (
        not question
        or not question.word_sense_id
    ):
        return None

    word = (
        db.query(Word)
        .filter(
            Word.id == question.word_id
        )
        .first()
    )

    sense = (
        db.query(WordSense)
        .filter(
            WordSense.id
            == question.word_sense_id
        )
        .first()
    )

    if not word or not sense:
        return None

    return make_hint(
        word=word,
        sense=sense,
    )


@router.get("/quiz")
def quiz_page(
    request: Request,
    db: Session = Depends(get_db),
):
    question = get_active_question(db)

    if not question:
        question = generate_quiz_question(db)

    hint = get_hint_for_question(
        db,
        question,
    )

    review_progress = get_review_progress(db)

    return templates.TemplateResponse(
        request=request,
        name="quiz.html",
        context={
            "question": question,
            "hint": hint,
            "result": None,
            "review_progress": review_progress,
        },
    )


@router.post("/quiz")
def quiz_submit(
    request: Request,
    question_id: int = Form(...),
    user_answer: str = Form(...),
    db: Session = Depends(get_db),
):
    result = submit_answer(
        db=db,
        question_id=question_id,
        user_answer=user_answer,
    )

    return templates.TemplateResponse(
        request=request,
        name="quiz.html",
        context={
            "question": None,
            "hint": None,
            "result": result,
            "review_progress": get_review_progress(db),
        },
    )


@router.post("/quiz/review")
def quiz_review(
    question_id: int = Form(...),
    rating: str = Form(...),
    db: Session = Depends(get_db),
):
    review_question(
        db=db,
        question_id=question_id,
        rating=rating,
    )

    return RedirectResponse(
        url="/quiz",
        status_code=303,
    )


@router.post("/quiz/generate-all")
def quiz_generate_all(
    db: Session = Depends(get_db),
):
    return generate_all_quiz_questions(db)
