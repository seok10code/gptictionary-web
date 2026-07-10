from datetime import date

from sqlalchemy.orm import Session

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
    db.commit()
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