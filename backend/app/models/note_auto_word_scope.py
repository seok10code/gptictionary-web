"""Reversible visibility for mistakenly auto-added words; no word/history deletion."""
from datetime import datetime
from sqlalchemy import Column,Integer,String,DateTime,Boolean,ForeignKey
from backend.app.db.database import Base


class AutoWordScope(Base):
    __tablename__='english_auto_word_scope'
    word_id=Column(Integer,ForeignKey('words.id'),primary_key=True)
    excluded=Column(Boolean,nullable=False,default=False)
    reason=Column(String(255),nullable=False,default='')
    updated_at=Column(DateTime,nullable=False,default=datetime.utcnow)
