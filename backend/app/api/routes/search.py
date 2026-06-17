import json

from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.services.word_service import search_word

router = APIRouter()


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

    entries = safe_json_loads(word.entries_json, [])
    examples = safe_json_loads(word.examples_json, [])

    return {
        "id": word.id,
        "vocabulary": word.vocabulary,
        "definition": word.definition,
        "sentence": word.sentence,
        "synonyms": word.synonyms,
        "pronunciation": word.pronunciation,
        "antonyms": word.antonyms,
        "usage_note": word.usage_note,
        "entries": entries,
        "examples": examples,
        "etymology_summary": word.etymology_summary,
    }


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
    query: str = Form(...),
    db: Session = Depends(get_db),
):
    result = await search_word(
        db=db,
        vocabulary=query,
    )

    word_obj = result.get("word")

    if word_obj is None:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "request": request,
                "query": query,
                "word": None,
                "source": None,
                "error": result.get("message", "단어를 찾지 못했습니다."),
            },
        )

    word = word_to_dict(word_obj)

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "request": request,
            "query": query,
            "word": word,
            "source": result.get("source"),
            "error": None,
        },
    )