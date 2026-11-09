"""Durable conversation queue, ordered turns, and the current topic summaries."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from backend.app.db.database import Base


class AutoConversation(Base):
    __tablename__ = "english_auto_conversations"
    key = Column(String(64), primary_key=True)
    conversation_id = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    processed_revision = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="waiting", index=True)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    lease = Column(String(64))
    leased_at = Column(DateTime)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text)
    cached_plan = Column(JSON)


class AutoTurn(Base):
    __tablename__ = "english_auto_turns"
    __table_args__ = (UniqueConstraint("conversation_key", "question_id", name="uq_auto_question"),)
    id = Column(Integer, primary_key=True)
    conversation_key = Column(String(64), ForeignKey("english_auto_conversations.key"), nullable=False, index=True)
    question_id = Column(String(255), nullable=False)
    source_id = Column(Integer, ForeignKey("english_note_sources.id"), nullable=False)
    previous_question_id = Column(String(255))
    order_known = Column(Boolean, nullable=False, default=False)
    stable = Column(Boolean, nullable=False, default=False)
    channel = Column(String(16), nullable=False)
    observed_at = Column(DateTime().with_variant(MySQLDateTime(fsp=6), "mysql", "mariadb"), nullable=False, default=datetime.utcnow)
    active = Column(Boolean, nullable=False, default=True)


class AutoTopic(Base):
    __tablename__ = "english_auto_topics"
    key = Column(String(64), primary_key=True)
    conversation_key = Column(String(64), ForeignKey("english_auto_conversations.key"), nullable=False, index=True)
    anchor_question_id = Column(String(255), nullable=False)
    note_id = Column(Integer, ForeignKey("english_notes.id"), index=True)
    section_id = Column(Integer, ForeignKey("english_note_sections.id"))
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=0)
    data = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
