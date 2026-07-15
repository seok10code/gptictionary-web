from sqlalchemy.orm import Session

from backend.app.models.sense_coach_note import (
    SenseCoachNote,
)
from backend.app.models.sense_confusion import (
    SenseConfusion,
)


def get_confusions_by_sense_id(
    db: Session,
    word_sense_id: int,
):
    return (
        db.query(SenseConfusion)
        .filter(
            SenseConfusion.word_sense_id
            == word_sense_id
        )
        .order_by(
            SenseConfusion.display_order.asc(),
            SenseConfusion.id.asc(),
        )
        .all()
    )


def get_coach_note_by_sense_id(
    db: Session,
    word_sense_id: int,
):
    return (
        db.query(SenseCoachNote)
        .filter(
            SenseCoachNote.word_sense_id
            == word_sense_id
        )
        .first()
    )


def replace_sense_learning_data(
    db: Session,
    word_sense_id: int,
    coach_tip: str,
    memory_tip: str,
    pattern_tip: str,
    comparisons: list[dict],
):
    (
        db.query(SenseConfusion)
        .filter(
            SenseConfusion.word_sense_id
            == word_sense_id
        )
        .delete(
            synchronize_session=False
        )
    )

    coach_note = get_coach_note_by_sense_id(
        db=db,
        word_sense_id=word_sense_id,
    )

    if coach_note is None:
        coach_note = SenseCoachNote(
            word_sense_id=word_sense_id,
        )
        db.add(coach_note)

    coach_note.coach_tip = coach_tip
    coach_note.memory_tip = memory_tip
    coach_note.pattern_tip = pattern_tip

    for index, item in enumerate(
        comparisons[:4]
    ):
        comparison_word = str(
            item.get("word") or ""
        ).strip()

        explanation = str(
            item.get("explanation") or ""
        ).strip()

        example = str(
            item.get("example") or ""
        ).strip()

        if not comparison_word or not explanation:
            continue

        db.add(
            SenseConfusion(
                word_sense_id=word_sense_id,
                comparison_word=comparison_word,
                korean_explanation=explanation,
                example_sentence=example or None,
                display_order=index,
            )
        )

    db.commit()
    db.refresh(coach_note)

    return coach_note
