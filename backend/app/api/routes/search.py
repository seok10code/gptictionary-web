import re
import json
import asyncio

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db, SessionLocal
from backend.app.services.word_service import search_word
from backend.app.crud.word import get_word_by_vocabulary


router = APIRouter()


def is_valid_input(vocabulary: str) -> bool:
    if not vocabulary:
        return False

    if len(vocabulary) > 50:
        return False

    if not re.match(r"^[a-zA-Z\s\-']+$", vocabulary):
        return False

    return True


def safe_json_loads(value, default):
    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


def word_to_dict(word):
    if word is None:
        return None

    return {
        "id": word.id,
        "vocabulary": word.vocabulary,
        "definition": word.definition,
        "sentence": word.sentence,
        "synonyms": word.synonyms,
        "pronunciation": word.pronunciation,
        "antonyms": word.antonyms,
        "usage_note": word.usage_note,
        "entries": safe_json_loads(word.entries_json, []),
        "examples": safe_json_loads(word.examples_json, []),
        "etymology_summary": word.etymology_summary,
    }


def create_word_background(query: str):
    db = SessionLocal()

    try:
        clean_query = query.strip().lower()

        existing_word = get_word_by_vocabulary(
            db=db,
            vocabulary=clean_query,
        )

        if existing_word:
            return

        asyncio.run(
            search_word(
                db=db,
                vocabulary=clean_query,
            )
        )

    except Exception as e:
        print("BACKGROUND WORD CREATE ERROR:", e)

    finally:
        db.close()


@router.get("/search")
def search_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "request": request,
            "query": "",
            "word": None,
            "source": None,
            "error": None,
        },
    )


@router.post("/search")
async def search_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    query: str = Form(...),
    db: Session = Depends(get_db),
):
    clean_query = query.strip().lower()

    if not is_valid_input(clean_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "request": request,
                "query": query,
                "word": None,
                "source": None,
                "error": "올바른 영어 단어 또는 표현을 입력해주세요.",
            },
        )

    existing_word = get_word_by_vocabulary(
        db=db,
        vocabulary=clean_query,
    )

    if existing_word:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "request": request,
                "query": clean_query,
                "word": word_to_dict(existing_word),
                "source": "db",
                "error": None,
            },
        )

    background_tasks.add_task(
        create_word_background,
        clean_query,
    )

    return templates.TemplateResponse(
        request=request,
        name="search_loading.html",
        context={
            "request": request,
            "query": clean_query,
        },
    )


@router.get("/search/status")
def search_status(
    query: str = Query(...),
    db: Session = Depends(get_db),
):
    clean_query = query.strip().lower()

    word = get_word_by_vocabulary(
        db=db,
        vocabulary=clean_query,
    )

    return JSONResponse(
        {
            "ready": word is not None,
            "query": clean_query,
        }
    )


@router.get("/search/result")
def search_result(
    request: Request,
    query: str = Query(...),
    db: Session = Depends(get_db),
):
    clean_query = query.strip().lower()

    word = get_word_by_vocabulary(
        db=db,
        vocabulary=clean_query,
    )

    if not word:
        return templates.TemplateResponse(
            request=request,
            name="search_loading.html",
            context={
                "request": request,
                "query": clean_query,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "request": request,
            "query": clean_query,
            "word": word_to_dict(word),
            "source": "db",
            "error": None,
        },
    )