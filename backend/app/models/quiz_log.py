from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.sql import func

from backend.app.db.database import Base


class QuizLog(Base):
    __tablename__ = "quiz_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
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

    word_sense_id = Column(
        Integer,
        ForeignKey(
            "word_senses.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    question_id = Column(
        Integer,
        ForeignKey(
            "quiz_questions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    user_answer = Column(
        String(255),
        nullable=True,
    )

    correct_answer = Column(
        String(255),
        nullable=False,
    )

    is_correct = Column(
        Boolean,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
