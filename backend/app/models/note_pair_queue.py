"""Durable, versioned question/answer jobs; independent of legacy conversation plans."""
from datetime import datetime
from sqlalchemy import Column,Integer,String,Text,DateTime,JSON,ForeignKey,UniqueConstraint
from backend.app.db.database import Base

class NotePairLane(Base):
    __tablename__='english_note_pair_lanes'
    key=Column(String(64),primary_key=True)
    lease=Column(String(64))
    expires_at=Column(DateTime)

class NotePairJob(Base):
    __tablename__='english_note_pair_jobs'
    __table_args__=(UniqueConstraint('source_id',name='uq_note_pair_source'),)
    id=Column(Integer,primary_key=True)
    source_id=Column(Integer,ForeignKey('english_note_sources.id'),nullable=False)
    conversation_id=Column(String(255),nullable=False,index=True)
    question_id=Column(String(255),nullable=False,index=True)
    previous_question_id=Column(String(255))
    channel=Column(String(16),nullable=False)
    stable=Column(Integer,nullable=False,default=0)
    order_known=Column(Integer,nullable=False,default=0)
    status=Column(String(24),nullable=False,default='waiting',index=True)
    attempts=Column(Integer,nullable=False,default=0)
    available_at=Column(DateTime,nullable=False,default=datetime.utcnow,index=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    observed_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    updated_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    lease=Column(String(64))
    note_id=Column(Integer,ForeignKey('english_notes.id'),index=True)
    result=Column(JSON,nullable=False,default=dict)
    error=Column(Text)

class NotePairDocument(Base):
    __tablename__='english_note_pair_documents'
    note_id=Column(Integer,ForeignKey('english_notes.id'),primary_key=True)
    revision=Column(Integer,nullable=False,default=0)
    document=Column(JSON,nullable=False,default=dict)
    updated_at=Column(DateTime,nullable=False,default=datetime.utcnow)
