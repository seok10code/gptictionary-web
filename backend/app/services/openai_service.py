import os
import json
from dotenv import load_dotenv
from openai import OpenAI

from backend.app.services.wiktionary_mcp_service import lookup_wiktionary


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=20.0,
    max_retries=1
)


async def generate_word_info(vocabulary: str) -> dict:
    wiktionary_data = await lookup_wiktionary(vocabulary)

    if not wiktionary_data.get("found"):
        return {
            "valid": False
        }

    entries = wiktionary_data.get("entries", [])
    pronunciations = wiktionary_data.get("pronunciations", [])
    synonyms = wiktionary_data.get("synonyms", [])
    antonyms = wiktionary_data.get("antonyms", [])
    examples = wiktionary_data.get("examples", [])
    etymology = wiktionary_data.get("etymology", "")

    cleaned_entries = []

    for entry in entries[:4]:
        definitions = [
            definition
            for definition in entry.get("definitions", [])
            if definition
        ][:3]

        if not definitions:
            continue

        cleaned_entries.append(
            {
                "part_of_speech": entry.get("part_of_speech", ""),
                "korean_meaning": "",
                "definitions": definitions
            }
        )

    if not cleaned_entries:
        return {
            "valid": False
        }

    first_definition = cleaned_entries[0]["definitions"][0]
    first_example = examples[0] if examples else ""

    prompt = f"""
You are an English teacher for Korean learners.

Return ONLY valid JSON.
Do not use markdown.
Do not add explanations outside JSON.

Word: {vocabulary}

Main English definition:
{first_definition}

Example:
{first_example}

Entries:
{json.dumps(cleaned_entries, ensure_ascii=False)}

Raw etymology:
{etymology[:500]}

Return this JSON structure:

{{
    "definition": "대표 한국어 뜻",
    "entries_korean": [
        {{
            "part_of_speech": "same part_of_speech",
            "korean_meaning": "한국어 뜻"
        }}
    ],
    "sentence": "Natural English example sentence using the word",
    "usage_note": "한국어 뉘앙스 설명 + 실제 대화 예시 2개",
    "etymology_summary": "어원이 유용하면 한국어로 짧게, 아니면 빈 문자열"
}}

Rules:
- definition must be short Korean.
- entries_korean must match the part_of_speech values in Entries.
- sentence should be natural and use the word.
- usage_note must be mostly Korean.
- usage_note must include two short realistic English conversation examples.
- Keep everything concise.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2
        )

        content = response.choices[0].message.content.strip()
        ai_result = json.loads(content)

    except Exception:
        ai_result = {}

    korean_map = {
        item.get("part_of_speech"): item.get("korean_meaning", "")
        for item in ai_result.get("entries_korean", [])
        if isinstance(item, dict)
    }

    final_entries = []

    for entry in cleaned_entries:
        part_of_speech = entry.get("part_of_speech", "")

        final_entries.append(
            {
                "part_of_speech": part_of_speech,
                "korean_meaning": korean_map.get(part_of_speech, ""),
                "definitions": entry.get("definitions", [])
            }
        )

    return {
        "valid": True,
        "vocabulary": vocabulary,
        "entries": final_entries,
        "definition": ai_result.get("definition", ""),
        "sentence": ai_result.get("sentence", first_example),
        "pronunciation": pronunciations[0] if pronunciations else "",
        "synonyms": synonyms[:4],
        "antonyms": antonyms[:4],
        "examples": examples[:4],
        "etymology_summary": ai_result.get("etymology_summary", ""),
        "usage_note": ai_result.get("usage_note", ""),
        "raw_wiktionary": wiktionary_data
    }


def ask_openai(question: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "너는 영어 표현을 한국어로 쉽고 자연스럽게 설명해주는 영어 선생님이야."
            },
            {
                "role": "user",
                "content": question
            }
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content


def extract_word_candidate(question: str, answer: str) -> dict | None:
    prompt = f"""
        You are an expert English teacher for Korean learners.

        From the user's question and the answer, extract ONE useful English word or phrase worth saving to a vocabulary notebook.

        Return ONLY valid JSON.
        Do not use markdown.
        Do not add explanations outside JSON.

        If there is no useful English word or phrase to save, return:
        {{
        "has_candidate": false
        }}

        If there is a useful word or phrase, return:
        {{
        "has_candidate": true,
        "vocabulary": "English word or phrase",
        "definition": "Natural Korean meaning",
        "sentence": "Natural English example sentence using the word or phrase",
        "synonyms": "synonym1, synonym2, synonym3",
        "usage_note": "Korean nuance explanation + real-life usage + two short English conversation examples"
        }}

        Requirements:
        - Pick only ONE best expression.
        - Prefer the expression the user asked about.
        - Do not extract random common words.
        - vocabulary must be English only.
        - definition must be Korean.
        - sentence must be natural everyday English.
        - synonyms should be comma-separated.
        - usage_note must be written mostly in Korean.
        - usage_note must explain how native speakers use it in real conversation.
        - usage_note must include two short realistic English conversation examples.
        - Each conversation example must have A and B lines.
        - Do not make usage_note too long.

        usage_note format:
        "이 표현은 ... 뉘앙스로 쓰입니다. 실제 대화에서는 ... 상황에서 자주 씁니다.

        실제 대화 1:
        A: ...
        B: ...

        실제 대화 2:
        A: ...
        B: ..."

        Question: {question}

        Answer: {answer}
        """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an English teacher. "
                    "Return valid JSON only."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.2
    )

    content = response.choices[0].message.content.strip()

    try:
        result = json.loads(content)

    except Exception:
        return None

    if not result.get("has_candidate"):
        return None

    return result