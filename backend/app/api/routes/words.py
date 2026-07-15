import math

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense
from backend.app.schemas.word import WordCreate
from backend.app.services.word_service import save_extracted_word


router = APIRouter()


def get_words_with_senses_paginated(
    db: Session,
    page: int,
    per_page: int,
    keyword: str,
    sort: str,
):
    clean_keyword = keyword.strip()

    query = (
        db.query(Word)
        .options(selectinload(Word.senses))
    )

    if clean_keyword:
        like_keyword = f"%{clean_keyword}%"

        query = (
            query
            .outerjoin(
                WordSense,
                WordSense.word_id == Word.id,
            )
            .filter(
                or_(
                    Word.vocabulary.ilike(like_keyword),
                    Word.definition.ilike(like_keyword),
                    WordSense.korean_meaning.ilike(like_keyword),
                    WordSense.search_keywords_json.ilike(like_keyword),
                )
            )
            .distinct()
        )

    total_count = query.count()

    if sort == "abc":
        query = query.order_by(
            Word.vocabulary.asc(),
            Word.id.asc(),
        )
    elif sort == "id":
        query = query.order_by(Word.id.asc())
    elif sort == "priority":
        query = query.order_by(
            Word.priority.desc(),
            Word.updated_at.desc(),
            Word.id.desc(),
        )
    elif sort == "memorize":
        query = query.order_by(
            Word.memorize_count.asc(),
            Word.updated_at.desc(),
            Word.id.desc(),
        )
    else:
        query = query.order_by(
            Word.created_at.desc(),
            Word.id.desc(),
        )

    words = (
        query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return words, total_count


@router.get("/words")
def words_page(
    request: Request,
    page: int = Query(1, ge=1),
    keyword: str = "",
    sort: str = "latest",
    db: Session = Depends(get_db),
):
    per_page = 12

    words, total_count = get_words_with_senses_paginated(
        db=db,
        page=page,
        per_page=per_page,
        keyword=keyword,
        sort=sort,
    )

    total_pages = max(
        1,
        math.ceil(total_count / per_page),
    )

    if page > total_pages:
        page = total_pages

    return templates.TemplateResponse(
        request=request,
        name="words.html",
        context={
            "words": words,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "keyword": keyword,
            "sort": sort,
        },
    )


@router.post("/api/words/save")
def save_word(
    word: WordCreate,
    db: Session = Depends(get_db),
):
    return save_extracted_word(
        db=db,
        word=word,
    )
