from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.models.daily_paragraph import DailyParagraph
from backend.app.schemas.daily_paragraph import DailyParagraphCreate


def get_daily_paragraph(db: Session, target_date: date):
    return (
        db.query(DailyParagraph)
        .filter(DailyParagraph.date == target_date)
        .first()
    )


def create_daily_paragraph(
    db: Session,
    paragraph: DailyParagraphCreate,
):
    db_paragraph = DailyParagraph(
        **paragraph.model_dump()
    )

    db.add(db_paragraph)
    try:
        db.commit()
    except IntegrityError as exc:
        # Another request may have saved today's paragraph while AI was running.
        # Roll back the failed transaction before reading the committed winner.
        db.rollback()
        original = exc.orig
        code = getattr(original, "args", (None,))[0]
        message = str(original).lower()
        date_conflict = (
            code == 1062 and "for key" in message
            and ("'date'" in message or "'.date'" in message
                 or ".date'" in message or "`date`" in message)
        ) or (
            "unique constraint failed: daily_paragraphs.date" in message
        )
        if date_conflict:
            existing = get_daily_paragraph(db, paragraph.date)
            if existing is not None:
                return existing
        raise
    db.refresh(db_paragraph)

    return db_paragraph


def get_latest_daily_paragraph(db: Session):
    return (
        db.query(DailyParagraph)
        .order_by(DailyParagraph.date.desc())
        .first()
    )


def get_recent_daily_paragraphs(
    db: Session,
    limit: int = 7,
):
    return (
        db.query(DailyParagraph)
        .order_by(DailyParagraph.date.desc())
        .limit(limit)
        .all()
    )
