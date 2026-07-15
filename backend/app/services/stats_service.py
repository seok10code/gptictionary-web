from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_

from backend.app.models.quiz_log import QuizLog
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense


def _today_range():
    today_start = datetime.combine(
        date.today(),
        time.min,
    )

    tomorrow_start = today_start + timedelta(
        days=1
    )

    return today_start, tomorrow_start



def get_learning_streak(
    db,
    lookback_days=365,
):
    rows = (
        db.query(
            func.date(
                QuizLog.created_at
            ).label("day")
        )
        .filter(
            QuizLog.created_at
            >= datetime.now()
            - timedelta(days=lookback_days)
        )
        .group_by(
            func.date(
                QuizLog.created_at
            )
        )
        .order_by(
            func.date(
                QuizLog.created_at
            ).desc()
        )
        .all()
    )

    reviewed_dates = {
        row.day
        for row in rows
        if row.day is not None
    }

    if not reviewed_dates:
        return 0

    today = date.today()

    if today in reviewed_dates:
        cursor = today
    elif (
        today - timedelta(days=1)
        in reviewed_dates
    ):
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0

    while cursor in reviewed_dates:
        streak += 1
        cursor -= timedelta(days=1)

    return streak

def get_dashboard_data(db):
    now = datetime.now()
    today_start, tomorrow_start = _today_range()
    recent_since = now - timedelta(hours=24)

    total_words = db.query(Word).count()
    total_senses = db.query(WordSense).count()

    due_review_count = (
        db.query(WordSense)
        .filter(
            or_(
                WordSense.next_review_at.is_(None),
                WordSense.next_review_at <= now,
            )
        )
        .count()
    )

    today_added_senses = (
        db.query(WordSense)
        .filter(
            WordSense.created_at >= recent_since
        )
        .count()
    )

    today_quiz = (
        db.query(QuizLog)
        .filter(
            QuizLog.created_at >= today_start,
            QuizLog.created_at < tomorrow_start,
        )
        .count()
    )

    today_reviewed_senses = (
        db.query(
            func.count(
                func.distinct(
                    WordSense.id
                )
            )
        )
        .filter(
            WordSense.last_reviewed_at >= today_start,
            WordSense.last_reviewed_at < tomorrow_start,
        )
        .scalar()
        or 0
    )

    due_rows = (
        db.query(
            WordSense,
            Word,
        )
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            or_(
                WordSense.next_review_at.is_(None),
                WordSense.next_review_at <= now,
            )
        )
        .order_by(
            WordSense.next_review_at.asc(),
            WordSense.priority.desc(),
            WordSense.total_wrong.desc(),
            WordSense.id.asc(),
        )
        .limit(5)
        .all()
    )

    today_review_senses = [
        {
            "sense_id": sense.id,
            "vocabulary": word.vocabulary,
            "part_of_speech": sense.part_of_speech,
            "korean_meaning": sense.korean_meaning,
            "total_correct": sense.total_correct or 0,
            "total_wrong": sense.total_wrong or 0,
            "next_review_at": sense.next_review_at,
        }
        for sense, word in due_rows
    ]

    recent_rows = (
        db.query(
            WordSense,
            Word,
        )
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .order_by(
            WordSense.created_at.desc(),
            WordSense.id.desc(),
        )
        .limit(5)
        .all()
    )

    recent_senses = [
        {
            "sense_id": sense.id,
            "vocabulary": word.vocabulary,
            "part_of_speech": sense.part_of_speech,
            "korean_meaning": sense.korean_meaning,
        }
        for sense, word in recent_rows
    ]

    review_goal = (
        due_review_count
        + today_reviewed_senses
    )

    review_progress_percent = (
        round(
            (
                today_reviewed_senses
                / review_goal
            )
            * 100
        )
        if review_goal > 0
        else 100
    )

    return {
        "total_words": total_words,
        "total_senses": total_senses,
        "review_words": due_review_count,
        "today_added": today_added_senses,
        "today_quiz": today_quiz,
        "today_reviewed_senses": today_reviewed_senses,
        "review_goal": review_goal,
        "review_progress_percent": review_progress_percent,
        "learning_streak": get_learning_streak(db),
        "today_review_words": today_review_senses,
        "recent_words": recent_senses,
    }


def get_stats(db):
    now = datetime.now()
    today_start, tomorrow_start = _today_range()

    total_words = db.query(Word).count()
    total_senses = db.query(WordSense).count()

    due_today = (
        db.query(WordSense)
        .filter(
            or_(
                WordSense.next_review_at.is_(None),
                WordSense.next_review_at <= now,
            )
        )
        .count()
    )

    reviewed_today = (
        db.query(
            func.count(
                func.distinct(
                    WordSense.id
                )
            )
        )
        .filter(
            WordSense.last_reviewed_at >= today_start,
            WordSense.last_reviewed_at < tomorrow_start,
        )
        .scalar()
        or 0
    )

    new_senses = (
        db.query(WordSense)
        .filter(
            WordSense.review_count == 0
        )
        .count()
    )

    difficult_senses = (
        db.query(WordSense)
        .filter(
            WordSense.total_wrong
            > WordSense.total_correct
        )
        .count()
    )

    total_correct = (
        db.query(
            func.coalesce(
                func.sum(
                    WordSense.total_correct
                ),
                0,
            )
        )
        .scalar()
        or 0
    )

    total_wrong = (
        db.query(
            func.coalesce(
                func.sum(
                    WordSense.total_wrong
                ),
                0,
            )
        )
        .scalar()
        or 0
    )

    average_ease = (
        db.query(
            func.avg(
                WordSense.ease_factor
            )
        )
        .scalar()
    )

    average_interval = (
        db.query(
            func.avg(
                WordSense.review_interval
            )
        )
        .scalar()
    )

    return {
        "total_words": int(total_words or 0),
        "total_senses": int(total_senses or 0),
        "due_today": int(due_today or 0),
        "reviewed_today": int(reviewed_today or 0),
        "new_senses": int(new_senses or 0),
        "difficult_senses": int(difficult_senses or 0),
        "total_correct": int(total_correct or 0),
        "total_wrong": int(total_wrong or 0),
        "average_ease": round(
            float(average_ease or 2.5),
            2,
        ),
        "average_interval": round(
            float(average_interval or 0),
            1,
        ),
        "learning_streak": get_learning_streak(db),
    }


def get_top_wrong_senses(
    db,
    limit=10,
):
    rows = (
        db.query(
            WordSense,
            Word,
        )
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            WordSense.total_wrong > 0
        )
        .order_by(
            WordSense.total_wrong.desc(),
            WordSense.total_correct.asc(),
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "label": (
                f"{word.vocabulary} · "
                f"{sense.korean_meaning}"
            ),
            "value": sense.total_wrong or 0,
        }
        for sense, word in rows
    ]


def get_top_correct_senses(
    db,
    limit=10,
):
    rows = (
        db.query(
            WordSense,
            Word,
        )
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            WordSense.total_correct > 0
        )
        .order_by(
            WordSense.total_correct.desc(),
            WordSense.total_wrong.asc(),
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "label": (
                f"{word.vocabulary} · "
                f"{sense.korean_meaning}"
            ),
            "value": sense.total_correct or 0,
        }
        for sense, word in rows
    ]


def get_recent_senses(
    db,
    limit=10,
):
    rows = (
        db.query(
            WordSense,
            Word,
        )
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .order_by(
            WordSense.created_at.desc(),
            WordSense.id.desc(),
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "sense_id": sense.id,
            "vocabulary": word.vocabulary,
            "part_of_speech": sense.part_of_speech,
            "korean_meaning": sense.korean_meaning,
            "created_at": sense.created_at,
        }
        for sense, word in rows
    ]


def get_daily_review_activity(
    db,
    days=7,
):
    start_date = (
        date.today()
        - timedelta(days=days - 1)
    )

    rows = (
        db.query(
            func.date(
                QuizLog.created_at
            ).label("day"),
            func.count(
                QuizLog.id
            ).label("count"),
        )
        .filter(
            func.date(
                QuizLog.created_at
            ) >= start_date
        )
        .group_by(
            func.date(
                QuizLog.created_at
            )
        )
        .order_by(
            func.date(
                QuizLog.created_at
            )
        )
        .all()
    )

    data_map = {
        str(row.day): int(row.count or 0)
        for row in rows
    }

    labels = []
    data = []

    for index in range(days):
        target_date = (
            start_date
            + timedelta(days=index)
        )

        key = str(target_date)

        labels.append(key[5:])
        data.append(
            data_map.get(key, 0)
        )

    return labels, data
