from datetime import date, datetime, time, timedelta
from sqlalchemy import func

from backend.app.models.word import Word
from backend.app.models.quiz_log import QuizLog


def get_dashboard_data(db):
    today_start = datetime.combine(date.today(), time.min)
    today_end = datetime.combine(date.today(), time.max)
    recent_since = datetime.now() - timedelta(hours=24)

    total_words = db.query(Word).count()

    review_words = (
        db.query(Word)
        .filter(Word.priority > Word.memorize_count)
        .count()
    )

    today_added = (
    db.query(Word)
    .filter(Word.created_at >= recent_since)
    .count()
)

    # 일단 전체 퀴즈 로그 개수
    today_quiz = (
    db.query(QuizLog)
    .filter(QuizLog.created_at >= recent_since)
    .count()
)

    today_review_words = (
        db.query(Word)
        .filter(Word.priority > Word.memorize_count)
        .order_by(Word.priority.desc())
        .limit(5)
        .all()
    )

    recent_words = (
        db.query(Word)
        .order_by(Word.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "total_words": total_words,
        "review_words": review_words,
        "today_added": today_added,
        "today_quiz": today_quiz,
        "today_review_words": today_review_words,
        "recent_words": recent_words,
    }


def get_stats(db):
    total_words = db.query(Word).count()

    memorized_words = (
        db.query(Word)
        .filter(Word.memorize_count >= 5)
        .count()
    )

    review_words = (
        db.query(Word)
        .filter(Word.priority > Word.memorize_count)
        .count()
    )

    return {
        "total_words": total_words,
        "memorized_words": memorized_words,
        "review_words": review_words,
    }


def get_top_wrong_words(db, limit=10):
    return (
        db.query(Word)
        .order_by(Word.priority.desc())
        .limit(limit)
        .all()
    )


def get_top_memorized_words(db, limit=10):
    return (
        db.query(Word)
        .order_by(Word.memorize_count.desc())
        .limit(limit)
        .all()
    )


def get_recent_words(db, limit=10):
    return (
        db.query(Word)
        .order_by(Word.created_at.desc())
        .limit(limit)
        .all()
    )


def get_daily_added_words(db, days=7):
    start_date = date.today() - timedelta(days=days - 1)

    rows = (
        db.query(
            func.date(Word.created_at).label("day"),
            func.count(Word.id).label("count"),
        )
        .filter(func.date(Word.created_at) >= start_date)
        .group_by(func.date(Word.created_at))
        .order_by(func.date(Word.created_at))
        .all()
    )

    data_map = {str(row.day): row.count for row in rows}

    labels = []
    data = []

    for i in range(days):
        d = start_date + timedelta(days=i)
        key = str(d)

        labels.append(key[5:])
        data.append(data_map.get(key, 0))

    return labels, data