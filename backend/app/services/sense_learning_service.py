import json
import os

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from backend.app.crud.sense_learning import (
    get_coach_note_by_sense_id,
    get_confusions_by_sense_id,
    replace_sense_learning_data,
)


client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
)


def _serialize_learning_data(
    coach_note,
    confusions,
) -> dict:
    return {
        "coach": (
            {
                "coach_tip": coach_note.coach_tip,
                "memory_tip": coach_note.memory_tip,
                "pattern_tip": coach_note.pattern_tip,
            }
            if coach_note
            else None
        ),
        "confusions": [
            {
                "word": item.comparison_word,
                "explanation": (
                    item.korean_explanation
                ),
                "example": (
                    item.example_sentence
                ),
            }
            for item in confusions
        ],
    }


async def get_or_create_sense_learning_data(
    db: Session,
    vocabulary: str,
    sense,
) -> dict:
    coach_note = get_coach_note_by_sense_id(
        db=db,
        word_sense_id=sense.id,
    )

    confusions = get_confusions_by_sense_id(
        db=db,
        word_sense_id=sense.id,
    )

    if coach_note and confusions:
        return _serialize_learning_data(
            coach_note,
            confusions,
        )

    prompt = f"""
너는 한국인 영어 학습자를 위한 AI 코치다.

표제어:
{vocabulary}

현재 학습 중인 뜻:
- 품사: {sense.part_of_speech}
- 한국어 뜻: {sense.korean_meaning}
- 영어 정의: {sense.english_definition or ""}
- 대표 예문: {sense.sentence or ""}
- 동의어: {sense.synonyms or ""}
- 반의어: {sense.antonyms or ""}

학습 기록:
- 정답: {sense.total_correct or 0}
- 오답: {sense.total_wrong or 0}
- 복습 횟수: {sense.review_count or 0}
- 복습 간격: {sense.review_interval or 0}일

이 정확한 뜻을 기준으로 학습 도움말을 만들어라.

JSON 구조:
{{
  "coach_tip": "현재 뜻의 핵심 뉘앙스를 설명하는 짧은 한국어 코칭",
  "memory_tip": "짧고 실제로 외우기 좋은 한국어 암기 팁",
  "pattern_tip": "자주 함께 쓰는 영어 패턴 또는 콜로케이션",
  "comparisons": [
    {{
      "word": "비교할 영어 단어",
      "explanation": "현재 뜻과의 차이를 한국어로 명확하게 설명",
      "example": "비교 단어가 자연스럽게 들어간 영어 예문"
    }}
  ]
}}

규칙:
- JSON만 반환한다.
- comparisons는 3~4개다.
- 현재 뜻과 실제로 헷갈릴 수 있는 표현만 고른다.
- 같은 표제어의 다른 뜻을 비교 대상으로 넣지 않는다.
- 설명은 짧지만 차이가 명확해야 한다.
- 영어 예문은 자연스러운 완전한 문장이다.
- 학습 기록이 없으면 초보 학습자용 안내를 한다.
- 오답이 정답보다 많으면 혼동 지점을 직접 짚어준다.
"""

    try:
        response = (
            await client.chat.completions.create(
                model=os.getenv(
                    "OPENAI_MODEL",
                    "gpt-4o-mini",
                ),
                response_format={
                    "type": "json_object",
                },
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Return valid JSON only. "
                            "Coach Korean English learners."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.2,
            )
        )

        result = json.loads(
            response
            .choices[0]
            .message
            .content
            .strip()
        )

    except Exception as exc:
        print(
            "SENSE LEARNING GENERATION ERROR:",
            repr(exc),
        )

        return {
            "coach": None,
            "confusions": [],
        }

    coach_tip = str(
        result.get("coach_tip") or ""
    ).strip()

    memory_tip = str(
        result.get("memory_tip") or ""
    ).strip()

    pattern_tip = str(
        result.get("pattern_tip") or ""
    ).strip()

    comparisons = result.get(
        "comparisons"
    )

    if not isinstance(comparisons, list):
        comparisons = []

    if not coach_tip:
        coach_tip = (
            f"{vocabulary}의 이 뜻은 "
            f"'{sense.korean_meaning}'로 기억하세요."
        )

    replace_sense_learning_data(
        db=db,
        word_sense_id=sense.id,
        coach_tip=coach_tip,
        memory_tip=memory_tip,
        pattern_tip=pattern_tip,
        comparisons=comparisons,
    )

    return _serialize_learning_data(
        get_coach_note_by_sense_id(
            db=db,
            word_sense_id=sense.id,
        ),
        get_confusions_by_sense_id(
            db=db,
            word_sense_id=sense.id,
        ),
    )
