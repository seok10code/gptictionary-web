from sqlalchemy import Column, Integer, Text, DateTime, JSON
from sqlalchemy.sql import func

from backend.app.db.database import Base


class WritingSubmission(Base):
    __tablename__ = "writing_submissions"

    id = Column(Integer, primary_key=True, index=True)

    topic = Column(Text, nullable=False)
    required_words = Column(JSON, nullable=True)

    original_text = Column(Text, nullable=False)
    corrected_text = Column(Text, nullable=True)
    natural_text = Column(Text, nullable=True)

    feedback_json = Column(JSON, nullable=True)
    grammar_tags = Column(JSON, nullable=True)

    used_words = Column(JSON, nullable=True)
    missing_words = Column(JSON, nullable=True)

    grammar_score = Column(Integer, nullable=True)
    vocab_score = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())