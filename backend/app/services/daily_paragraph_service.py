import re
from datetime import date

from sqlalchemy.orm import Session
from markupsafe import Markup, escape

from backend.app.crud.daily_paragraph import (
    get_daily_paragraph,
    create_daily_paragraph,
)
from backend.app.schemas.daily_paragraph import DailyParagraphCreate
from backend.app.services.openai_service import generate_daily_paragraph


def highlight_focus_words(text: str, focus_words: str | None):
    if not text:
        return ""

    safe_text = escape(text)

    if not focus_words:
        return Markup(safe_text)

    highlighted_text = str(safe_text)

    words = [
        word.strip()
        for word in focus_words.split(",")
        if word.strip()
    ]

    # 긴 표현부터 먼저 처리해야 "time management" 같은 구문이 깨지지 않음
    words = sorted(words, key=len, reverse=True)

    for word in words:
        escaped_word = escape(word)
        pattern = re.compile(
            r"(?<!\w)(" + re.escape(str(escaped_word)) + r")(?!\w)",
            re.IGNORECASE,
        )

        replacement = (
            '<a href="#" '
            'class="reading-highlight" '
            f'data-search-word="{word}">'
            r'\1'
            '</a>'
        )

        highlighted_text = pattern.sub(
            replacement,
            highlighted_text,
        )

    return Markup(highlighted_text)


def attach_highlighted_content(paragraph):
    if not paragraph:
        return None

    paragraph.highlighted_english_content = highlight_focus_words(
        text=paragraph.english_content,
        focus_words=paragraph.focus_words,
    )

    return paragraph


def get_or_create_today_paragraph(db: Session):
    today = date.today()

    paragraph = get_daily_paragraph(
        db=db,
        target_date=today,
    )

    if paragraph:
        return attach_highlighted_content(paragraph)

    ai_result = generate_daily_paragraph()

    if not ai_result:
        return None

    paragraph_create = DailyParagraphCreate(
        date=today,
        title=ai_result["title"],
        english_content=ai_result["english_content"],
        korean_translation=ai_result["korean_translation"],
        focus_words=", ".join(ai_result["focus_words"]),
        level=ai_result["level"],
    )

    created_paragraph = create_daily_paragraph(
        db=db,
        paragraph=paragraph_create,
    )

    return attach_highlighted_content(created_paragraph)