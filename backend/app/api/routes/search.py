import re
import json
import asyncio
import os

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

    # 영어/한글 섞인 긴 문장은 검색이 아니라 질문/문장분석으로 보냄
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


async def korean_to_best_english(korean_query: str) -> str | None:
    prompt = f"""
한국어 입력을 영어 학습용 단어 또는 자연스러운 영어 표현 하나로 변환해줘.

규칙:
- 반드시 영어 단어 또는 짧은 영어 표현 하나만 선택
- 설명 금지
- JSON만 출력
- 사물/도구/기기 이름이면 형용사보다 명사구를 우선
- 너무 넓은 단어보다 실제로 쓰는 표현 우선
- "리모콘", "리모컨"은 "remote control" 우선
- "드론 조종기"는 "remote controller" 또는 "controller" 우선
- 오타가 있어도 자연스럽게 보정

예시:
리모콘 -> {{"word": "remote control"}}
추상적 -> {{"word": "abstract"}}
평판 -> {{"word": "reputation"}}
연기하다 -> {{"word": "postpone"}}
사생활 -> {{"word": "privacy"}}
핸드폰 -> {{"word": "smartphone"}}

입력: {korean_query}
"""

    response = await openai_client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": "You convert Korean search queries into one natural English vocabulary item or short phrase. Return JSON only.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.1,
    )

    content = response.choices[0].message.content.strip()

    try:
        data = json.loads(content)
    except Exception:
        print("KOREAN TO ENGLISH JSON PARSE ERROR:", content)
        return None

    word = data.get("word")

    if not word or not isinstance(word, str):
        return None

    clean_word = word.strip().lower()

    if not is_valid_input(clean_word):
        return None

    return clean_word


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
            "words": [],
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
    raw_query = query.strip()
    clean_query = raw_query.lower()

    # 검색창에는 단어/짧은 표현만 허용
    # 문장이나 질문은 /questions에서 처리하도록 막음
    if looks_like_question_or_sentence(raw_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "request": request,
                "query": raw_query,
                "word": None,
                "words": [],
                "source": None,
                "error": "문장이나 질문은 '질문' 탭에서 입력해주세요. 단어 검색에는 단어 또는 짧은 표현만 입력해주세요.",
            },
        )

    # 한국어 단어 검색
    # 예: 리모콘 -> remote control -> DB 검색 -> 없으면 생성
    if has_korean(raw_query):
        english_query = await korean_to_best_english(raw_query)

        if not english_query:
            return templates.TemplateResponse(
                request=request,
                name="search.html",
                context={
                    "request": request,
                    "query": raw_query,
                    "word": None,
                    "words": [],
                    "source": None,
                    "error": "한국어 검색어를 영어 단어로 변환하지 못했습니다.",
                },
            )

        existing_word = get_word_by_vocabulary(
            db=db,
            vocabulary=english_query,
        )

        if existing_word:
            return RedirectResponse(
                url=f"/search/result?query={existing_word.vocabulary}",
                status_code=303,
            )

        try:
            result = await search_word(
                db=db,
                vocabulary=english_query,
            )

        except Exception as e:
            print("KOREAN SEARCH WORD CREATE ERROR:", repr(e))

            return templates.TemplateResponse(
                request=request,
                name="search.html",
                context={
                    "request": request,
                    "query": raw_query,
                    "word": None,
                    "words": [],
                    "source": None,
                    "error": f"'{english_query}' 단어 생성 중 오류가 발생했습니다.",
                },
            )

        word = result.get("word") if result else None

        if not word:
            return templates.TemplateResponse(
                request=request,
                name="search.html",
                context={
                    "request": request,
                    "query": raw_query,
                    "word": None,
                    "words": [],
                    "source": None,
                    "error": f"'{english_query}' 단어를 찾지 못했습니다.",
                },
            )

        return RedirectResponse(
            url=f"/search/result?query={word.vocabulary}",
            status_code=303,
        )

    # 영어 단어/짧은 표현 검색
    if not is_valid_input(clean_query):
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "request": request,
                "query": raw_query,
                "word": None,
                "words": [],
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
                "words": [],
                "source": "db",
                "error": None,
            },
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
            context={
                "request": request,
                "query": clean_query,
                "word": None,
                "words": [],
                "source": None,
                "error": "단어 생성 중 오류가 발생했습니다.",
            },
        )

    word = result.get("word") if result else None

    if not word:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "request": request,
                "query": clean_query,
                "word": None,
                "words": [],
                "source": None,
                "error": "단어를 찾지 못했습니다.",
            },
        )

    return RedirectResponse(
        url=f"/search/result?query={word.vocabulary}",
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
            "words": [],
            "source": "db",
            "error": None,
        },
    )