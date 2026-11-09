from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)

from backend.app.db.database import Base


class NoteSource(Base):
    __tablename__ = "english_note_sources"

    id = Column(Integer, primary_key=True)
    source_key = Column(String(64), unique=True, nullable=False)
    conversation_id = Column(String(255), nullable=False, index=True)
    message_id = Column(String(255), nullable=False)
    collection = Column(String(255), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    context = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="pending", index=True)
    processing_at = Column(DateTime)
    error = Column(Text)
    extraction = Column(JSON)
    notes_applied = Column(Boolean, nullable=False, default=False)
    word_links = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class EnglishNote(Base):
    __tablename__ = "english_notes"

    id = Column(Integer, primary_key=True)
    topic_key = Column(String(64), unique=True, nullable=False)
    title = Column(String(255), nullable=False, index=True)
    kind = Column(String(30), nullable=False, index=True)
    subject = Column(String(100), nullable=False, index=True)
    keywords = Column(Text, nullable=False, default="")
    version = Column(Integer, nullable=False, default=0)
    studied_version = Column(Integer, nullable=False, default=0)
    favorite = Column(Boolean, nullable=False, default=False)
    next_review_at = Column(DateTime, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


class NoteSection(Base):
    __tablename__ = "english_note_sections"
    __table_args__ = (
        UniqueConstraint(
            "note_id", "content_hash",
            name="uq_english_note_section_content",
        ),
        UniqueConstraint(
            "note_id", "version",
            name="uq_english_note_section_version",
        ),
    )

    id = Column(Integer, primary_key=True)
    note_id = Column(
        Integer, ForeignKey("english_notes.id"), nullable=False, index=True
    )
    source_id = Column(
        Integer, ForeignKey("english_note_sources.id"), nullable=False
    )
    version = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    heading = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    recall_question = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NoteSourceLink(Base):
    __tablename__ = "english_note_source_links"
    __table_args__ = (
        UniqueConstraint(
            "note_id", "source_id",
            name="uq_english_note_source_link",
        ),
    )

    id = Column(Integer, primary_key=True)
    note_id = Column(
        Integer, ForeignKey("english_notes.id"), nullable=False, index=True
    )
    source_id = Column(
        Integer, ForeignKey("english_note_sources.id"),
        nullable=False, index=True,
    )
