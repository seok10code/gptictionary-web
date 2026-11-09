from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer,
    JSON, String, UniqueConstraint,
)

from backend.app.db.database import Base
from backend.app.models.english_note import NoteSource


class NoteSourceEvidence(Base):
    __tablename__ = "english_note_source_evidence"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "channel",
            name="uq_english_source_evidence_channel",
        ),
    )

    id = Column(Integer, primary_key=True)
    source_id = Column(
        Integer,
        ForeignKey("english_note_sources.id"),
        nullable=False,
        index=True,
    )
    question_key = Column(String(64), nullable=False, index=True)
    channel = Column(String(16), nullable=False)
    identity_state = Column(String(24), nullable=False)
    completion_state = Column(String(24), nullable=False)
    answer_ids = Column(JSON, nullable=False, default=list)
    first_seen_at = Column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    last_seen_at = Column(
        DateTime, nullable=False, default=datetime.utcnow
    )
