from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.services.openai_service import (
    ask_openai,
    extract_word_candidate,
    analyze_sentence,
)
from backend.app.services.embedding_service import create_embedding
from backend.app.services.qdrant_service import (
    save_question_to_qdrant,
    search_similar_questions,
)
from backend.app.services.db_query_service import (
    get_word_count,
    get_most_wrong_words,
    get_most_memorized_words,
)

router = APIRouter()


def is_sentence_analysis_answer(answer: str | None) -> bool:
    if not answer:
        return False

    markers = [
        "1. 전체 뜻",
        "2. 문장 구조",
        "3. 들어간 문법",
        "4. 핵심 표현",
        "5. 예문",
        "5. 비슷한 예문",
    ]

    count = sum(1 for m in markers if m in answer)
    return count >= 2


def normalize_memory_query(question: str) -> str:
    remove_phrases = [
        "이거 내가 전에 물어본 적 있냐?",
        "이거 내가 전에 물어본 적 있나?",
        "내가 전에 물어본 적 있냐?",
        "내가 전에 물어본 적 있나?",
        "전에 물어본 적 있냐?",
        "전에 물어본 적 있나?",
        "이거 물어본 적 있어?",
        "이거 전에 물어봤어?",
    ]

    clean = question.strip()

    for phrase in remove_phrases:
        clean = clean.replace(phrase, "")

    return clean.strip()


def is_memory_question(question: str) -> bool:
    keywords = [
        "전에 물어본",
        "물어본 적",
        "전에 질문",
        "이거 물어봤",
        "기억나",
    ]
    return any(k in question for k in keywords)


def answer_db_question(question: str, db: Session) -> str | None:
    if "몇 개" in question or "몇개" in question or "총" in question:
        count = get_word_count(db)
        return f"현재 단어장에는 총 {count}개의 단어가 저장되어 있어."

    if "많이 틀린" in question or "제일 많이 틀린" in question:
        words = get_most_wrong_words(db, limit=10)
        answer = "가장 많이 틀린 단어 TOP 10:\n\n"
        for i, word in enumerate(words, 1):
            answer += f"{i}. {word.vocabulary} - 오답 {word.priority}회\n"
        return answer

    if "많이 외운" in question or "암기" in question:
        words = get_most_memorized_words(db, limit=10)
        answer = "가장 많이 외운 단어 TOP 10:\n\n"
        for i, word in enumerate(words, 1):
            answer += f"{i}. {word.vocabulary} - 정답 {word.memorize_count}회\n"
        return answer

    return None


@router.get("/questions", response_class=HTMLResponse)
def questions_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="questions.html",
        context={
            "question": None,
            "answer": None,
            "candidate": None,
            "similar_questions": [],
            "mode": "question",
        },
    )


@router.post("/questions", response_class=HTMLResponse)
def ask_question(
    request: Request,
    question: str = Form(...),
    mode: str = Form("question"),
    db: Session = Depends(get_db),
):
    question = question.strip()
    mode = mode.strip()

    answer = None
    candidate = None
    similar_questions = []

    print("=" * 80)
    print("USER INPUT:", question)
    print("MODE:", mode)
    print("=" * 80)

    try:
        if mode == "sentence":
            print("ANSWER SOURCE: SENTENCE ANALYSIS")
            answer = analyze_sentence(question)
            candidate = None

        else:
            db_answer = answer_db_question(question, db)

            if db_answer:
                print("ANSWER SOURCE: LOCAL DB QUERY")
                answer = db_answer
                candidate = None

            else:
                memory_mode = is_memory_question(question)
                search_query = normalize_memory_query(question) if memory_mode else question

                print("VECTOR SEARCH QUERY:", search_query)

                vector = create_embedding(search_query)
                results = search_similar_questions(vector, limit=5)

                threshold = 0.80 if memory_mode else 0.97

                print("QDRANT THRESHOLD:", threshold)
                print("QDRANT RESULTS:")

                for r in results:
                    payload_question = r.payload.get("question")
                    payload_answer = r.payload.get("answer")
                    payload_mode = r.payload.get("mode", "question")

                    print("score:", round(r.score, 4))
                    print("mode:", payload_mode)
                    print("question:", payload_question)
                    print("answer:", payload_answer)
                    print("-" * 40)

                    if payload_mode != "question":
                        continue

                    if is_sentence_analysis_answer(payload_answer):
                        print("SKIP: sentence analysis cached answer")
                        continue

                    if r.score >= threshold:
                        similar_questions.append(
                            {
                                "score": round(r.score, 4),
                                "question": payload_question,
                                "answer": payload_answer,
                            }
                        )

                print("FILTERED SIMILAR QUESTIONS:", similar_questions)

                if memory_mode:
                    if similar_questions:
                        answer = (
                            "응, 비슷한 질문을 전에 한 적이 있어.\n\n"
                            f"가장 비슷한 질문:\n{similar_questions[0]['question']}\n\n"
                            f"유사도: {similar_questions[0]['score']}"
                        )
                    else:
                        answer = "내 저장된 질문 기록에서는 거의 같은 질문을 찾지 못했어."

                    candidate = None

                elif similar_questions:
                    print("ANSWER SOURCE: QDRANT CACHE")
                    answer = similar_questions[0]["answer"]

                    candidate = extract_word_candidate(
                        question=question,
                        answer=answer,
                    )

                else:
                    print("ANSWER SOURCE: OPENAI")
                    answer = ask_openai(question)

                    print("GPT ANSWER:")
                    print(answer)

                    save_question_to_qdrant(
                        question=question,
                        answer=answer,
                        vector=vector,
                    )

                    candidate = extract_word_candidate(
                        question=question,
                        answer=answer,
                    )

    except Exception as e:
        print("QUESTION ERROR:", repr(e))
        answer = f"에러 발생: {str(e)}"

    return templates.TemplateResponse(
        request=request,
        name="questions.html",
        context={
            "question": question,
            "answer": answer,
            "candidate": candidate,
            "similar_questions": similar_questions,
            "mode": mode,
        },
    )