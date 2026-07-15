from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.sql import func

from backend.app.db.database import Base


class SenseCoachNote(Base):
    __tablename__ = "sense_coach_notes"

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
        unique=True,
        index=True,
    )

    coach_tip = Column(
        Text,
        nullable=False,
    )

    memory_tip = Column(
        Text,
        nullable=True,
    )

    pattern_tip = Column(
        Text,
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
