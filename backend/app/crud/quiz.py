import re

from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.models.word import Word
from backend.app.models.quiz_question import QuizQuestion
from backend.app.models.quiz_log import QuizLog


def make_blank_question(sentence: str, answer: str):
    if not sentence or not answer:
        return None

    pattern = re.compile(re.escape(answer), re.IGNORECASE)

    if not pattern.search(sentence):
        return None

    return pattern.sub("_____", sentence, count=1)


def make_definition_question(word: Word):
    return f"뜻을 보고 알맞은 영어 단어/표현을 입력하세요.\n\n뜻: {word.definition}"


def make_hint(word: Word):
    vocabulary = word.vocabulary or ""
    word_count = len(vocabulary.split())
    first_letter = vocabulary[0] if vocabulary else ""

    return {
        "definition": word.definition,
        "word_count": word_count,
        "first_letter": first_letter,
        "sentence": word.sentence,
    }


def get_active_question(db: Session):
    return (
        db.query(QuizQuestion)
        .filter(QuizQuestion.is_active == True)
        .join(Word, Word.id == QuizQuestion.word_id)
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand()
        )
        .first()
    )


def get_question_by_id(db: Session, question_id: int):
    return (
        db.query(QuizQuestion)
        .filter(QuizQuestion.id == question_id)
        .first()
    )


def get_latest_logged_word_id(db: Session):
    latest_log = (
        db.query(QuizLog)
        .order_by(QuizLog.id.desc())
        .first()
    )

    if not latest_log:
        return None

    return latest_log.word_id


def get_word_for_quiz(db: Session):
    latest_word_id = get_latest_logged_word_id(db)

    query = (
        db.query(Word)
        .filter(Word.vocabulary.isnot(None))
        .filter(Word.vocabulary != "")
        .filter(Word.definition.isnot(None))
        .filter(Word.definition != "")
    )

    if latest_word_id:
        query = query.filter(Word.id != latest_word_id)

    word = (
        query
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand()
        )
        .first()
    )

    if word:
        return word

    return (
        db.query(Word)
        .filter(Word.vocabulary.isnot(None))
        .filter(Word.vocabulary != "")
        .filter(Word.definition.isnot(None))
        .filter(Word.definition != "")
        .order_by(
            Word.priority.desc(),
            Word.memorize_count.asc(),
            func.rand()
        )
        .first()
    )


def get_existing_active_question_by_word(db: Session, word_id: int):
    return (
        db.query(QuizQuestion)
        .filter(QuizQuestion.word_id == word_id)
        .filter(QuizQuestion.is_active == True)
        .first()
    )


def get_existing_question_by_word(db: Session, word_id: int):
    return (
        db.query(QuizQuestion)
        .filter(QuizQuestion.word_id == word_id)
        .order_by(QuizQuestion.id.desc())
        .first()
    )


def create_question_for_word(db: Session, word: Word, is_active: bool = True):
    if not word:
        return None

    if not word.vocabulary or not word.definition:
        return None

    question_text = make_blank_question(
        sentence=word.sentence,
        answer=word.vocabulary
    )

    if not question_text:
        question_text = make_definition_question(word)

    existing_question = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.word_id == word.id)
        .filter(QuizQuestion.question == question_text)
        .first()
    )

    if existing_question:
        existing_question.is_active = is_active
        db.commit()
        db.refresh(existing_question)
        return existing_question

    quiz_question = QuizQuestion(
        word_id=word.id,
        question=question_text,
        answer=word.vocabulary,
        is_active=is_active
    )

    db.add(quiz_question)
    db.commit()
    db.refresh(quiz_question)

    return quiz_question


def generate_quiz_question_for_word(db: Session, word: Word):
    existing_question = get_existing_question_by_word(
        db=db,
        word_id=word.id
    )

    if existing_question:
        existing_question.is_active = True
        db.commit()
        db.refresh(existing_question)
        return existing_question

    return create_question_for_word(
        db=db,
        word=word,
        is_active=True
    )


def generate_quiz_question(db: Session):
    word = get_word_for_quiz(db)

    if not word:
        return None

    existing_question = get_existing_active_question_by_word(
        db=db,
        word_id=word.id
    )

    if existing_question:
        return existing_question

    return create_question_for_word(
        db=db,
        word=word,
        is_active=True
    )


def generate_all_quiz_questions(db: Session):
    words = (
        db.query(Word)
        .filter(Word.vocabulary.isnot(None))
        .filter(Word.vocabulary != "")
        .filter(Word.definition.isnot(None))
        .filter(Word.definition != "")
        .all()
    )

    created_count = 0
    skipped_count = 0

    for word in words:
        existing_question = get_existing_question_by_word(
            db=db,
            word_id=word.id
        )

        if existing_question:
            skipped_count += 1
            continue

        question = create_question_for_word(
            db=db,
            word=word,
            is_active=False
        )

        if question:
            created_count += 1
        else:
            skipped_count += 1

    return {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "total_words": len(words)
    }


def create_quiz_log(
    db: Session,
    word_id: int,
    question_id: int,
    user_answer: str,
    correct_answer: str,
    is_correct: bool
):
    log = QuizLog(
        word_id=word_id,
        question_id=question_id,
        user_answer=user_answer,
        correct_answer=correct_answer,
        is_correct=is_correct
    )

    db.add(log)
    db.flush()

    return log


def submit_answer(
    db: Session,
    question_id: int,
    user_answer: str
):
    question = get_question_by_id(
        db=db,
        question_id=question_id
    )

    if not question:
        return None

    word = (
        db.query(Word)
        .filter(Word.id == question.word_id)
        .first()
    )

    if not word:
        return None

    clean_user_answer = user_answer.strip().lower()
    clean_correct_answer = question.answer.strip().lower()

    is_correct = clean_user_answer == clean_correct_answer

    if is_correct:
        word.memorize_count += 1
        word.total_correct += 1
        question.correct_count += 1
    else:
        word.total_wrong += 1
        question.wrong_count += 1

    create_quiz_log(
        db=db,
        word_id=word.id,
        question_id=question.id,
        user_answer=user_answer,
        correct_answer=question.answer,
        is_correct=is_correct
    )

    db.commit()
    db.refresh(word)
    db.refresh(question)

    return {
        "is_correct": is_correct,
        "correct_answer": question.answer,
        "word": word,
        "question": question,
    }