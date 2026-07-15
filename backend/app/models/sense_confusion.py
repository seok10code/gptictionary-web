from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from backend.app.db.database import Base


class SenseConfusion(Base):
    __tablename__ = "sense_confusions"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    word_sense_id = Column(
        Integer,
        ForeignKey(
            "word_senses.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    comparison_word = Column(
        String(255),
        nullable=False,
    )

    korean_explanation = Column(
        Text,
        nullable=False,
    )

    example_sentence = Column(
        Text,
        nullable=True,
    )

    display_order = Column(
        Integer,
        nullable=False,
        default=0,
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
