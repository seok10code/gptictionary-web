import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models.quiz_log import QuizLog
from backend.app.models.quiz_question import QuizQuestion
from backend.app.models.word import Word
from backend.app.models.word_sense import WordSense


def make_blank_question(
    sentence: str,
    answer: str,
) -> str | None:
    if not sentence or not answer:
        return None

    pattern = re.compile(
        re.escape(answer),
        re.IGNORECASE,
    )

    if not pattern.search(sentence):
        return None

    blank_sentence = pattern.sub(
        "_____",
        sentence,
        count=1,
    )

    return (
        "빈칸에 들어갈 영어 단어 또는 표현을 입력하세요."
        f"\n\n{blank_sentence}"
    )


def make_definition_question(
    sense: WordSense,
) -> str:
    return (
        "뜻을 보고 알맞은 영어 단어 또는 표현을 입력하세요."
        f"\n\n뜻: {sense.korean_meaning}"
    )


def make_hint(
    word: Word,
    sense: WordSense,
) -> dict:
    vocabulary = word.vocabulary or ""
    word_count = len(vocabulary.split())
    first_letter = vocabulary[0] if vocabulary else ""

    return {
        "definition": sense.korean_meaning,
        "part_of_speech": sense.part_of_speech,
        "word_count": word_count,
        "first_letter": first_letter,
        "sentence": sense.sentence,
    }


def get_active_question(
    db: Session,
) -> QuizQuestion | None:
    return (
        db.query(QuizQuestion)
        .join(
            Word,
            Word.id == QuizQuestion.word_id,
        )
        .filter(
            QuizQuestion.is_active.is_(True),
            QuizQuestion.word_sense_id.isnot(None),
        )
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand(),
        )
        .first()
    )


def get_question_by_id(
    db: Session,
    question_id: int,
) -> QuizQuestion | None:
    return (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.id == question_id
        )
        .first()
    )


def get_latest_logged_sense_id(
    db: Session,
) -> int | None:
    latest_log = (
        db.query(QuizLog)
        .filter(
            QuizLog.word_sense_id.isnot(None)
        )
        .order_by(
            QuizLog.id.desc()
        )
        .first()
    )

    if not latest_log:
        return None

    return latest_log.word_sense_id


def get_sense_for_quiz(
    db: Session,
) -> WordSense | None:
    latest_sense_id = get_latest_logged_sense_id(
        db
    )

    query = (
        db.query(WordSense)
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            Word.vocabulary.isnot(None),
            Word.vocabulary != "",
            WordSense.korean_meaning.isnot(None),
            WordSense.korean_meaning != "",
        )
    )

    if latest_sense_id:
        query = query.filter(
            WordSense.id != latest_sense_id
        )

    sense = (
        query
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand(),
        )
        .first()
    )

    if sense:
        return sense

    return (
        db.query(WordSense)
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            Word.vocabulary.isnot(None),
            Word.vocabulary != "",
            WordSense.korean_meaning.isnot(None),
            WordSense.korean_meaning != "",
        )
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand(),
        )
        .first()
    )


def get_existing_question_by_sense(
    db: Session,
    word_sense_id: int,
) -> QuizQuestion | None:
    return (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.word_sense_id
            == word_sense_id
        )
        .order_by(
            QuizQuestion.id.desc()
        )
        .first()
    )


def create_question_for_sense(
    db: Session,
    sense: WordSense,
    is_active: bool = True,
) -> QuizQuestion | None:
    if not sense:
        return None

    word = (
        db.query(Word)
        .filter(
            Word.id == sense.word_id
        )
        .first()
    )

    if (
        not word
        or not word.vocabulary
        or not sense.korean_meaning
    ):
        return None

    question_text = make_blank_question(
        sentence=sense.sentence or "",
        answer=word.vocabulary,
    )

    if not question_text:
        question_text = (
            make_definition_question(sense)
        )

    existing_question = (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.word_sense_id
            == sense.id,
            QuizQuestion.question
            == question_text,
        )
        .first()
    )

    if existing_question:
        existing_question.is_active = (
            is_active
        )

        db.commit()
        db.refresh(existing_question)

        return existing_question

    quiz_question = QuizQuestion(
        word_id=word.id,
        word_sense_id=sense.id,
        question=question_text,
        answer=word.vocabulary,
        is_active=is_active,
    )

    db.add(quiz_question)
    db.commit()
    db.refresh(quiz_question)

    return quiz_question


def generate_quiz_question_for_word(
    db: Session,
    word: Word,
):
    if not word:
        return []

    senses = (
        db.query(WordSense)
        .filter(
            WordSense.word_id == word.id
        )
        .order_by(
            WordSense.display_order.asc(),
            WordSense.id.asc(),
        )
        .all()
    )

    questions = []

    for sense in senses:
        existing = (
            get_existing_question_by_sense(
                db=db,
                word_sense_id=sense.id,
            )
        )

        if existing:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
            questions.append(existing)
            continue

        question = create_question_for_sense(
            db=db,
            sense=sense,
            is_active=True,
        )

        if question:
            questions.append(question)

    return questions


def get_active_question(
    db: Session,
) -> QuizQuestion | None:
    latest_log = (
        db.query(QuizLog)
        .filter(
            QuizLog.word_sense_id.isnot(None)
        )
        .order_by(
            QuizLog.id.desc()
        )
        .first()
    )

    query = (
        db.query(QuizQuestion)
        .join(
            Word,
            Word.id == QuizQuestion.word_id,
        )
        .filter(
            QuizQuestion.is_active.is_(True),
            QuizQuestion.word_sense_id.isnot(None),
        )
    )

    if latest_log and latest_log.word_sense_id:
        query = query.filter(
            QuizQuestion.word_sense_id
            != latest_log.word_sense_id
        )

    question = (
        query
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand(),
        )
        .first()
    )

    if question:
        return question

    return (
        db.query(QuizQuestion)
        .join(
            Word,
            Word.id == QuizQuestion.word_id,
        )
        .filter(
            QuizQuestion.is_active.is_(True),
            QuizQuestion.word_sense_id.isnot(None),
        )
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand(),
        )
        .first()
    )


def generate_all_quiz_questions(
    db: Session,
) -> dict:
    senses = (
        db.query(WordSense)
        .join(
            Word,
            Word.id == WordSense.word_id,
        )
        .filter(
            Word.vocabulary.isnot(None),
            Word.vocabulary != "",
            WordSense.korean_meaning.isnot(None),
            WordSense.korean_meaning != "",
        )
        .all()
    )

    created_count = 0
    activated_count = 0
    skipped_count = 0

    for sense in senses:
        existing = get_existing_question_by_sense(
            db=db,
            word_sense_id=sense.id,
        )

        if existing:
            if not existing.is_active:
                existing.is_active = True
                activated_count += 1
            else:
                skipped_count += 1
            continue

        question = create_question_for_sense(
            db=db,
            sense=sense,
            is_active=True,
        )

        if question:
            created_count += 1
        else:
            skipped_count += 1

    db.commit()

    return {
        "created_count": created_count,
        "activated_count": activated_count,
        "skipped_count": skipped_count,
        "total_senses": len(senses),
    }


def create_quiz_log(
    db: Session,
    word_id: int,
    word_sense_id: int,
    question_id: int,
    user_answer: str,
    correct_answer: str,
    is_correct: bool,
) -> QuizLog:
    log = QuizLog(
        word_id=word_id,
        word_sense_id=word_sense_id,
        question_id=question_id,
        user_answer=user_answer,
        correct_answer=correct_answer,
        is_correct=is_correct,
    )

    db.add(log)
    db.flush()

    return log


def submit_answer(
    db: Session,
    question_id: int,
    user_answer: str,
):
    question = get_question_by_id(
        db=db,
        question_id=question_id,
    )

    if (
        not question
        or not question.word_sense_id
    ):
        return None

    word = (
        db.query(Word)
        .filter(
            Word.id == question.word_id
        )
        .first()
    )

    sense = (
        db.query(WordSense)
        .filter(
            WordSense.id
            == question.word_sense_id
        )
        .first()
    )

    if not word or not sense:
        return None

    clean_user_answer = (
        user_answer
        .strip()
        .lower()
    )

    clean_correct_answer = (
        question.answer
        .strip()
        .lower()
    )

    is_correct = (
        clean_user_answer
        == clean_correct_answer
    )

    if is_correct:
        word.memorize_count = (
            word.memorize_count or 0
        ) + 1

        word.total_correct = (
            word.total_correct or 0
        ) + 1

        question.correct_count = (
            question.correct_count or 0
        ) + 1

    else:
        word.total_wrong = (
            word.total_wrong or 0
        ) + 1

        question.wrong_count = (
            question.wrong_count or 0
        ) + 1

    create_quiz_log(
        db=db,
        word_id=word.id,
        word_sense_id=sense.id,
        question_id=question.id,
        user_answer=user_answer,
        correct_answer=question.answer,
        is_correct=is_correct,
    )

    db.commit()
    db.refresh(word)
    db.refresh(question)
    db.refresh(sense)

    return {
        "is_correct": is_correct,
        "user_answer": user_answer,
        "correct_answer": question.answer,
        "word": word,
        "sense": sense,
        "question": question,
    }

def generate_quiz_question(
    db: Session,
) -> QuizQuestion | None:
    sense = get_sense_for_quiz(db)

    if not sense:
        return None

    existing = get_existing_question_by_sense(
        db=db,
        word_sense_id=sense.id,
    )

    if existing:
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing

    return create_question_for_sense(
        db=db,
        sense=sense,
        is_active=True,
    )