from sqlalchemy.orm import Session
from backend.app.models.sense_coach_note import SenseCoachNote
from backend.app.models.sense_confusion import SenseConfusion
from backend.app.models.word_sense import WordSense


def get_confusions_by_sense_id(db: Session, word_sense_id: int):
    return (db.query(SenseConfusion)
            .filter(SenseConfusion.word_sense_id == word_sense_id)
            .order_by(SenseConfusion.display_order.asc(), SenseConfusion.id.asc()).all())


def get_coach_note_by_sense_id(db: Session, word_sense_id: int):
    return (db.query(SenseCoachNote)
            .filter(SenseCoachNote.word_sense_id == word_sense_id).first())


def replace_sense_learning_data(
    db: Session, word_sense_id: int, coach_tip: str,
    memory_tip: str, pattern_tip: str, comparisons: list[dict],
):
    """Save a missing coaching bundle once; another completed request wins intact.

    API work happens before this function. Lock the existing parent sense so even
    an absent child row has a shared lock target. Both lookups are locking current
    reads on MySQL/MariaDB, independent of an earlier repeatable-read snapshot.
    Commit the complete bundle and release the lock together.
    """
    parent = (db.query(WordSense).filter(WordSense.id == word_sense_id)
              .populate_existing().with_for_update().first())
    if parent is None:
        raise ValueError('학습 대상 뜻을 찾지 못했습니다.')
    coach_note = (db.query(SenseCoachNote)
                  .filter(SenseCoachNote.word_sense_id == word_sense_id)
                  .populate_existing().with_for_update().first())
    if coach_note is not None:
        # Do not overwrite the winning request or delete its comparison rows.
        db.commit()
        return coach_note
    coach_note = SenseCoachNote(word_sense_id=word_sense_id,
        coach_tip=coach_tip, memory_tip=memory_tip, pattern_tip=pattern_tip)
    db.add(coach_note)
    # No blanket delete: pre-existing comparison records also remain intact.
    existing = get_confusions_by_sense_id(db, word_sense_id)
    if not existing:
        for index, item in enumerate(comparisons[:4]):
            if not isinstance(item, dict):
                continue
            word = str(item.get('word') or '').strip()
            explanation = str(item.get('explanation') or '').strip()
            example = str(item.get('example') or '').strip()
            if word and explanation:
                db.add(SenseConfusion(word_sense_id=word_sense_id,
                    comparison_word=word, korean_explanation=explanation,
                    example_sentence=example or None, display_order=index))
    db.commit()
    db.refresh(coach_note)
    return coach_note
