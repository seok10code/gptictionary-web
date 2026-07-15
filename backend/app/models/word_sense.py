
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.db.database import Base


class WordSense(Base):
    __tablename__ = "word_senses"
    __table_args__ = (
        UniqueConstraint(
            "word_id",
            "sense_key",
            name="uq_word_sense_key",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    word_id = Column(
        Integer,
        ForeignKey(
            "words.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    sense_key = Column(
        String(255),
        nullable=False,
    )

    part_of_speech = Column(
        String(100),
        nullable=False,
        index=True,
    )

    korean_meaning = Column(
        Text,
        nullable=False,
    )

    english_definition = Column(
        Text,
        nullable=True,
    )

    sentence = Column(
        Text,
        nullable=True,
    )

    usage_note = Column(
        Text,
        nullable=True,
    )

    conversation_json = Column(
        Text,
        nullable=True,
    )

    writing_examples_json = Column(
        Text,
        nullable=True,
    )

    synonyms = Column(
        Text,
        nullable=True,
    )

    antonyms = Column(
        Text,
        nullable=True,
    )

    examples_json = Column(
        Text,
        nullable=True,
    )

    search_keywords_json = Column(
        Text,
        nullable=True,
    )

    display_order = Column(
        Integer,
        nullable=False,
        default=0,
    )

    is_primary = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    priority = Column(
        Integer,
        nullable=False,
        default=0,
    )

    memorize_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    total_correct = Column(
        Integer,
        nullable=False,
        default=0,
    )

    total_wrong = Column(
        Integer,
        nullable=False,
        default=0,
    )
    ease_factor = Column(
        Float,
        nullable=False,
        default=2.5,
    )

    review_interval = Column(
        Integer,
        nullable=False,
        default=0,
    )

    review_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    last_reviewed_at = Column(
        DateTime,
        nullable=True,
    )

    next_review_at = Column(
        DateTime,
        nullable=True,
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    word = relationship(
        "Word",
        back_populates="senses",
    )