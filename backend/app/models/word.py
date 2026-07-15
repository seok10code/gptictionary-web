from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.db.database import Base
from backend.app.models.word_sense import WordSense


class Word(Base):
    __tablename__ = "words"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    vocabulary = Column(String(255), nullable=False)
    definition = Column(Text, nullable=False)
    sentence = Column(Text, nullable=True)
    synonyms = Column(Text, nullable=True)
    priority = Column(Integer, default=0)
    memorize_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    usage_note = Column(Text, nullable=True)
    total_correct = Column(Integer, default=0)
    total_wrong = Column(Integer, default=0)
    entries_json = Column(Text, nullable=True)
    pronunciation = Column(String(255), nullable=True)
    antonyms = Column(Text, nullable=True)
    examples_json = Column(Text, nullable=True)
    etymology_summary = Column(Text, nullable=True)
    raw_wiktionary_json = Column(Text, nullable=True)
    corrected_from = Column(String(255), nullable=True)

    senses = relationship(
        "WordSense",
        back_populates="word",
        cascade="all, delete-orphan",
        order_by="WordSense.display_order",
    )
