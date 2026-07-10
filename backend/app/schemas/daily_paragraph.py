from datetime import date, datetime

from pydantic import BaseModel


class DailyParagraphCreate(BaseModel):
    date: date
    title: str
    english_content: str
    korean_translation: str
    focus_words: str | None = None
    level: str = "intermediate"


class DailyParagraphResponse(BaseModel):
    id: int
    date: date
    title: str
    english_content: str
    korean_translation: str
    focus_words: str | None = None
    level: str
    created_at: datetime

    class Config:
        from_attributes = True