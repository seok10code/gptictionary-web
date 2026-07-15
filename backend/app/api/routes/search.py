import json
import os
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.crud.word import get_word_by_vocabulary
from backend.app.crud.word_sense import (
    get_sense_by_id,
    get_senses_by_word_id,
    search_senses_by_korean,
    word_sense_to_candidate,
)
from backend.app.db.database import get_db
from backend.app.services.word_service import search_word


router = APIRouter()
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def base_context(request: Request, **kwargs):
    context = {
        "request": request,
        "query": "",
        "searched_word": None,
        "word": None,
        "words": [],
        "candidates": [],
        "source": None,
        "error": None,
        "selected_meaning": None,
        "selected_part_of_speech": None,
    }
    context.update(kwargs)
    return context


def is_valid_input(vocabulary: str) -> bool:
    return bool(
        vocabulary
        and len(vocabulary) <= 80
        and re.match(r"^[a-zA-Z\s\-']+$", vocabulary)
    )


def has_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def looks_like_question_or_sentence(text: str) -> bool:
    text = text.strip()
    if "?" in text or len(text.split()) >= 6:
        return True
    return any(
        keyword in text
        for keyword in [
            "이거", "내가", "전에", "물어본", "적 있", "뭐야",
            "무슨 뜻", "왜", "차이", "어떻게", "문장", "분석",
            "해석", "문법",
        ]
    )


def safe_json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def sense_to_dict(sense):
    return {
        "id": sense.id,
        "sense_key": sense.sense_key,
        "part_of_speech": sense.part_of_speech,
        "korean_meaning": sense.korean_meaning,
        "english_definition": sense.english_definition,
        "sentence": sense.sentence,
        "usage_note": sense.usage_note,
        "conversation": safe_json_loads(
            sense.conversation_json,
            [],
        ),
        "writing_examples": safe_json_loads(
            sense.writing_examples_json,
            [],
        ),
        "synonyms": sense.synonyms,
        "antonyms": sense.antonyms,
        "examples": safe_json_loads(sense.examples_json, []),
        "search_keywords": safe_json_loads(
            sense.search_keywords_json,
            [],
        ),
        "is_primary": bool(sense.is_primary),
        "display_order": sense.display_order,
    }


def word_to_dict(db: Session, word, selected_sense_id: int | None = None):
    if word is None:
        return None

    senses = get_senses_by_word_id(db, word.id)
    selected = None

    if selected_sense_id:
        selected = next(
            (sense for sense in senses if sense.id == selected_sense_id),
            None,
        )

    if selected:
        senses = [selected] + [
            sense for sense in senses if sense.id != selected.id
        ]

    primary = selected or (senses[0] if senses else None)

    return {
        "id": word.id,
        "vocabulary": word.vocabulary,
        "definition": (
            primary.korean_meaning if primary else word.definition
        ),
        "sentence": primary.sentence if primary else word.sentence,
        "synonyms": primary.synonyms if primary else word.synonyms,
        "pronunciation": word.pronunciation,
        "antonyms": primary.antonyms if primary else word.antonyms,
        "usage_note": primary.usage_note if primary else word.usage_note,
        "examples": (
            safe_json_loads(primary.examples_json, [])
            if primary
            else safe_json_loads(word.examples_json, [])
        ),
        "etymology_summary": word.etymology_summary,
        "senses": [sense_to_dict(sense) for sense in senses],
        "selected_sense_id": selected.id if selected else None,
    }


async def korean_to_english_candidates(korean_query: str) -> list[dict]:
    prompt = f"""
Return 3 to 6 natural English candidates for this Korean word or
short expression: {korean_query}

Return JSON only:
{{
  "candidates": [
    {{
      "word": "right",
      "meaning_ko": "권리, 권한",
      "usage": "human rights, legal right",
      "part_of_speech": "noun"
    }}
  ]
}}
"""
    try:
        response = await openai_client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content.strip())
    except Exception as exc:
        print("KOREAN CANDIDATES ERROR:", repr(exc))
        return []

    candidates = []
    for candidate in data.get("candidates", []):
        word = str(candidate.get("word") or "").strip().lower()
        if not is_valid_input(word):
            continue
        candidates.append({
            "word": word,
            "meaning_ko": str(
                candidate.get("meaning_ko") or ""
            ).strip(),
            "usage": str(candidate.get("usage") or "").strip(),
            "part_of_speech": str(
                candidate.get("part_of_speech") or ""
            ).strip(),
            "source": "ai",
        })
    return candidates[:6]


@router.get("/search")
def search_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context=base_context(request),
    )


@router.post("/search")
async def search_submit(
    request: Request,
    query: str = Form(...),
    display: str | None = Form(None),
    meaning_ko: str | None = Form(None),
    usage: str | None = Form(None),
    part_of_speech: str | None = Form(None),
    sense_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    raw_query = query.strip()
    clean_query = raw_query.lower()

    if looks_like_question_or_sentence(raw_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=raw_query,
                error="문장이나 질문은 '질문' 탭에서 입력해주세요.",
            ),
        )

    if sense_id:
        sense = get_sense_by_id(db, sense_id)
        if sense and sense.word:
            params = {
                "query": sense.word.vocabulary,
                "display": display or raw_query,
                "sense_id": sense.id,
            }
            return RedirectResponse(
                url=f"/search/result?{urlencode(params)}",
                status_code=303,
            )

    if has_korean(raw_query):
        db_senses = search_senses_by_korean(db, raw_query)

        if db_senses:
            candidates = [
                word_sense_to_candidate(sense)
                for sense in db_senses
            ]
            return templates.TemplateResponse(
                request=request,
                name="search.html",
                context=base_context(
                    request,
                    query=raw_query,
                    candidates=candidates,
                    source="korean_db",
                ),
            )

        candidates = await korean_to_english_candidates(raw_query)
        if not candidates:
            return templates.TemplateResponse(
                request=request,
                name="search.html",
                context=base_context(
                    request,
                    query=raw_query,
                    error="한국어 검색 후보를 만들지 못했습니다.",
                ),
            )

        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=raw_query,
                candidates=candidates,
                source="korean_ai_candidates",
            ),
        )

    if not is_valid_input(clean_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=raw_query,
                error="올바른 영어 단어 또는 표현을 입력해주세요.",
            ),
        )

    existing_word = get_word_by_vocabulary(db, clean_query)

    if existing_word and not (meaning_ko or part_of_speech or usage):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=clean_query,
                word=word_to_dict(db, existing_word),
                source="db",
            ),
        )

    try:
        result = await search_word(
            db=db,
            vocabulary=clean_query,
            requested_meaning=meaning_ko,
            requested_part_of_speech=part_of_speech,
            requested_usage=usage,
        )
    except Exception as exc:
        print("SEARCH ERROR:", repr(exc))
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=clean_query,
                error="단어 생성 중 오류가 발생했습니다.",
            ),
        )

    word = result.get("word") if result else None
    if not word:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=clean_query,
                error="단어를 찾지 못했습니다.",
            ),
        )

    selected = result.get("selected_sense")
    params = {"query": word.vocabulary}

    if display:
        params["display"] = display
    if selected:
        params["sense_id"] = selected.id

    return RedirectResponse(
        url=f"/search/result?{urlencode(params)}",
        status_code=303,
    )


@router.get("/search/result")
def search_result(
    request: Request,
    query: str = Query(...),
    display: str | None = Query(None),
    sense_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    clean_query = query.strip().lower()
    word = get_word_by_vocabulary(db, clean_query)

    if not word:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request,
                query=display or clean_query,
                error="단어를 찾지 못했습니다.",
            ),
        )

    selected_sense = (
        get_sense_by_id(db, sense_id)
        if sense_id
        else None
    )

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context=base_context(
            request,
            query=display or clean_query,
            searched_word=clean_query if display else None,
            word=word_to_dict(db, word, sense_id),
            source="korean_db" if display else "db",
            selected_meaning=(
                selected_sense.korean_meaning
                if selected_sense
                else None
            ),
            selected_part_of_speech=(
                selected_sense.part_of_speech
                if selected_sense
                else None
            ),
        ),
    )