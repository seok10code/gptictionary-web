"""Reversible exclusion of confirmed erroneous senses; original rows and history stay intact."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, event, select
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql import func
from backend.app.db.database import Base


class WordSenseExclusion(Base):
    __tablename__ = 'word_sense_exclusions'
    sense_id = Column(Integer, ForeignKey('word_senses.id'), primary_key=True)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


def install_sense_filter(sense_class):
    # Applies equally to wordbook relationships, search/counts, flashcards and quiz joins.
    # Explicit maintenance reads may opt in to the preserved original rows.
    @event.listens_for(Session, 'do_orm_execute')
    def filter_senses(state):
        if not state.is_select or state.execution_options.get('include_excluded_senses'):
            return
        state.statement = state.statement.options(with_loader_criteria(
            sense_class,
            lambda cls: cls.id.not_in(select(WordSenseExclusion.sense_id)),
            include_aliases=True))
