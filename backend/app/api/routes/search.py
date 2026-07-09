import re
import json
import asyncio
import os
from urllib.parse import quote_plus

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from openai import AsyncOpenAI

from backend.app.core.templates import templates
from backend.app.db.database import get_db, SessionLocal
from backend.app.services.word_service import search_word
from backend.app.crud.word import get_word_by_vocabulary


router = APIRouter()
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def base_context(
    request: Request,
    query: str = "",
    searched_word=None,
    word=None,
    words=None,
    candidates=None,
    source=None,
    error=None,
):
    return {
        "request": request,
        "query": query,
        "searched_word": searched_word,
        "word": word,
        "words": words or [],
        "candidates": candidates or [],
        "source": source,
        "error": error,
    }


def is_valid_input(vocabulary: str) -> bool:
    if not vocabulary:
        return False

    if len(vocabulary) > 80:
        return False

    if not re.match(r"^[a-zA-Z\s\-']+$", vocabulary):
        return False

    return True


def has_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def looks_like_question_or_sentence(text: str) -> bool:
    text = text.strip()

    if "?" in text:
        return True

    if len(text.split()) >= 6:
        return True

    question_keywords = [
        "이거",
        "내가",
        "전에",
        "물어본",
        "적 있",
        "뭐야",
        "무슨 뜻",
        "왜",
        "차이",
        "어떻게",
        "문장",
        "분석",
        "해석",
        "문법",
    ]

    return any(k in text for k in question_keywords)


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


async def korean_to_english_candidates(korean_query: str) -> list[dict]:
    prompt = f"""
너는 영어 단어장 앱의 한국어 검색 후보 생성기다.

사용자가 한국어 단어 또는 짧은 표현을 입력하면,
영어로 번역될 수 있는 자연스러운 후보를 3~6개 반환한다.

중요:
- 절대 하나로 단정하지 마라.
- 특히 한국어가 다의어이면 여러 후보를 보여줘라.
- 사용자가 나중에 선택할 수 있도록 후보별 차이를 한국어로 설명해라.
- word는 실제 영어 단어장 검색에 넣을 수 있는 영어 단어 또는 짧은 표현이어야 한다.
- word에는 한국어를 넣지 마라.
- usage에는 대표적인 collocation이나 사용 상황을 넣어라.
- part_of_speech는 noun, verb, adjective, expression 등으로 넣어라.

예시:
거치대 ->
stand / 받침대, 세워두는 거치대 / monitor stand, bike stand
holder / 물건을 끼우거나 잡아주는 거치대 / phone holder, cup holder
mount / 벽, 차량, 카메라 등에 장착하는 거치대 / camera mount, car mount
rack / 여러 물건을 얹거나 걸어두는 선반형 거치대 / dish rack, bike rack

반환 형식:
{{
  "candidates": [
    {{
      "word": "stand",
      "meaning_ko": "받침대, 세워두는 거치대",
      "usage": "monitor stand, bike stand",
      "part_of_speech": "noun"
    }}
  ]
}}

규칙:
- 반드시 JSON만 반환한다.
- markdown을 쓰지 마라.
- candidates는 최대 6개.
- 의미가 불확실하면 그래도 가능한 후보를 넓게 제시한다.

입력:
{korean_query}
"""

    try:
        response = await openai_client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()
        print("KOREAN CANDIDATES OPENAI RAW:", content)

        data = json.loads(content)

    except Exception as e:
        print("KOREAN CANDIDATES ERROR:", repr(e))
        return []

    candidates = data.get("candidates", [])

    if not isinstance(candidates, list):
        return []

    cleaned_candidates = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        word = str(candidate.get("word", "")).strip().lower()

        if not is_valid_input(word):
            continue

        cleaned_candidates.append(
            {
                "word": word,
                "meaning_ko": str(candidate.get("meaning_ko", "")).strip(),
                "usage": str(candidate.get("usage", "")).strip(),
                "part_of_speech": str(candidate.get("part_of_speech", "")).strip(),
            }
        )

    return cleaned_candidates[:6]


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
        context=base_context(request=request),
    )


@router.post("/search")
async def search_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    query: str = Form(...),
    db: Session = Depends(get_db),
):
    raw_query = query.strip()
    clean_query = raw_query.lower()

    if looks_like_question_or_sentence(raw_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request=request,
                query=raw_query,
                error="문장이나 질문은 '질문' 탭에서 입력해주세요. 단어 검색에는 단어 또는 짧은 표현만 입력해주세요.",
            ),
        )

    # 한국어 검색: 바로 영어 1개로 확정하지 않고 후보 목록 표시
    if has_korean(raw_query):
        candidates = await korean_to_english_candidates(raw_query)

        if not candidates:
            return templates.TemplateResponse(
                request=request,
                name="search.html",
                context=base_context(
                    request=request,
                    query=raw_query,
                    error="한국어 검색 후보를 만들지 못했습니다.",
                ),
            )

        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request=request,
                query=raw_query,
                candidates=candidates,
                source="korean_candidates",
            ),
        )

    if not is_valid_input(clean_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request=request,
                query=raw_query,
                error="올바른 영어 단어 또는 표현을 입력해주세요.",
            ),
        )

    existing_word = get_word_by_vocabulary(
        db=db,
        vocabulary=clean_query,
    )

    if existing_word:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request=request,
                query=clean_query,
                word=word_to_dict(existing_word),
                source="db",
            ),
        )

    try:
        result = await search_word(
            db=db,
            vocabulary=clean_query,
        )

    except Exception as e:
        print("SEARCH ERROR:", repr(e))

        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context=base_context(
                request=request,
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
                request=request,
                query=clean_query,
                error="단어를 찾지 못했습니다.",
            ),
        )

    return RedirectResponse(
        url=f"/search/result?query={quote_plus(word.vocabulary)}",
        status_code=303,
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
    display: str | None = Query(None),
    db: Session = Depends(get_db),
):
    clean_query = query.strip().lower()
    display_query = display.strip() if display else None

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
                "query": display_query or clean_query,
                "searched_word": clean_query if display_query else None,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context=base_context(
            request=request,
            query=display_query or clean_query,
            searched_word=clean_query if display_query else None,
            word=word_to_dict(word),
            source="korean_ai" if display_query else "db",
        ),
    )