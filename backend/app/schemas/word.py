from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class WordBase(BaseModel):
    vocabulary: str
    definition: str
    sentence: Optional[str] = None
    synonyms: Optional[str] = None
    usage_note: Optional[str] = None

    entries_json: Optional[str] = None
    pronunciation: Optional[str] = None
    antonyms: Optional[str] = None
    examples_json: Optional[str] = None
    etymology_summary: Optional[str] = None
    raw_wiktionary_json: Optional[str] = None


class WordCreate(WordBase):
    pass


class WordUpdate(BaseModel):
    vocabulary: Optional[str] = None
    definition: Optional[str] = None
    sentence: Optional[str] = None
    synonyms: Optional[str] = None
    usage_note: Optional[str] = None

    priority: Optional[int] = None
    memorize_count: Optional[int] = None
    total_correct: Optional[int] = None
    total_wrong: Optional[int] = None

    entries_json: Optional[str] = None
    pronunciation: Optional[str] = None
    antonyms: Optional[str] = None
    examples_json: Optional[str] = None
    etymology_summary: Optional[str] = None
    raw_wiktionary_json: Optional[str] = None


class WordRead(WordBase):
    id: int
    priority: int
    memorize_count: int
    total_correct: int
    total_wrong: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True