from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.app.db.database import Base


class MobileQuestion(Base):
    __tablename__ = "english_note_mobile_questions"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), nullable=False, unique=True)
    question = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
