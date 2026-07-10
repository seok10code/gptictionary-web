from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Date, DateTime

from backend.app.db.database import Base


class DailyParagraph(Base):
    __tablename__ = "daily_paragraphs"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False)

    title = Column(String(255), nullable=False)
    english_content = Column(Text, nullable=False)
    korean_translation = Column(Text, nullable=False)

    focus_words = Column(Text)
    level = Column(String(30), nullable=False, default="intermediate")

    created_at = Column(DateTime, default=datetime.utcnow)