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


class WordSenseRead(WordSenseBase):
    id: int
    word_id: int

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True