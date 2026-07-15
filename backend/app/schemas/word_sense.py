from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WordSenseBase(BaseModel):
    sense_key: str
    part_of_speech: str
    korean_meaning: str

    english_definition: Optional[str] = None
    sentence: Optional[str] = None

    usage_note: Optional[str] = None

    conversation_json: Optional[str] = None
    writing_examples_json: Optional[str] = None

    synonyms: Optional[str] = None
    antonyms: Optional[str] = None

    examples_json: Optional[str] = None
    search_keywords_json: Optional[str] = None

    display_order: int = 0
    is_primary: bool = False

    priority: int = 0
    memorize_count: int = 0
    total_correct: int = 0
    total_wrong: int = 0
    ease_factor: float = 2.5
    review_interval: int = 0
    review_count: int = 0
    last_reviewed_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None


class WordSenseCreate(WordSenseBase):
    word_id: int


class WordSenseUpdate(BaseModel):
    sense_key: Optional[str] = None
    part_of_speech: Optional[str] = None
    korean_meaning: Optional[str] = None

    english_definition: Optional[str] = None
    sentence: Optional[str] = None

    usage_note: Optional[str] = None

    conversation_json: Optional[str] = None
    writing_examples_json: Optional[str] = None

    synonyms: Optional[str] = None
    antonyms: Optional[str] = None

    examples_json: Optional[str] = None
    search_keywords_json: Optional[str] = None

    display_order: Optional[int] = None
    is_primary: Optional[bool] = None

    priority: Optional[int] = None
    memorize_count: Optional[int] = None
    total_correct: Optional[int] = None
    total_wrong: Optional[int] = None
    ease_factor: Optional[float] = None
    review_interval: Optional[int] = None
    review_count: Optional[int] = None
    last_reviewed_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None


class WordSenseRead(WordSenseBase):
    id: int
    word_id: int

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True