import os
import json
from dotenv import load_dotenv
from openai import OpenAI

from backend.app.services.wiktionary_mcp_service import lookup_wiktionary


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


async def generate_word_info(vocabulary: str) -> dict:
    wiktionary_data = await lookup_wiktionary(vocabulary)

    if not wiktionary_data.get("found"):
        return {
            "valid": False
        }

    wiktionary_context = json.dumps(
        wiktionary_data,
        ensure_ascii=False,
        indent=2
    )

    prompt = f"""
            You are an expert English teacher for Korean learners.

            You will receive raw Wiktionary data for an English word or phrase.

            Your task is NOT to invent new dictionary information.
            Your task is to select, clean, simplify, and organize the most useful information for Korean English learners.

            Return ONLY valid JSON.
            Do not use markdown.
            Do not add explanations outside JSON.

            Return this exact JSON structure:

            {{
            "valid": true,
            "vocabulary": "{vocabulary}",
            "entries": [
                {{
                "part_of_speech": "Adjective",
                "korean_meaning": "자연스러운 한국어 뜻",
                "definitions": [
                    "Short English definition 1",
                    "Short English definition 2"
                ]
                }}
            ],
            "definition": "대표 한국어 뜻",
            "sentence": "One natural English example sentence",
            "pronunciation": "Most common IPA pronunciation",
            "synonyms": [
                "common synonym 1",
                "common synonym 2",
                "common synonym 3",
                "common synonym 4"
            ],
            "antonyms": [
                "common antonym 1",
                "common antonym 2",
                "common antonym 3",
                "common antonym 4"
            ],
            "examples": [
                "Useful example sentence 1",
                "Useful example sentence 2",
                "Useful example sentence 3",
                "Useful example sentence 4"
            ],
            "etymology_summary": "어원을 한국어로 짧고 자연스럽게 요약",
            "usage_note": "한국어 뉘앙스 설명 + 실제 대화 예시 2개"
            }}

            Rules:
            - Keep all useful part_of_speech categories from Wiktionary, such as Adjective, Noun, Verb, etc.
            - For each part_of_speech, keep only the most common and useful meanings.
            - definitions must be in English.
            - korean_meaning must be in Korean.
            - definition must be a short representative Korean meaning for the word.
            - sentence must be one natural everyday English sentence.
            - pronunciation should be the most common IPA only. If unclear, use an empty string.
            - synonyms must be up to 4 common useful words only.
            - antonyms must be up to 4 common useful words only.
            - examples must be up to 4 useful natural examples only.
            - etymology_summary must be in Korean and short.
            - If the raw etymology is broken, unclear, or useless, return an empty string for etymology_summary.
            - usage_note must be mostly Korean.
            - usage_note must explain how native speakers use the word in real conversation.
            - usage_note must include two short realistic English conversation examples.
            - Do not include rare, archaic, religious, obsolete, or overly technical meanings unless they are very commonly used today.
            - Do not make the response too long.

            usage_note format:
            "이 표현은 ... 뉘앙스로 쓰입니다. 실제 대화에서는 ... 상황에서 자주 씁니다.

            실제 대화 1:
            A: ...
            B: ...

            실제 대화 2:
            A: ...
            B: ..."

            Raw Wiktionary data:
            {wiktionary_context}
        """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an English learning data editor. "
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
        return {
            "valid": False
        }

    if not result.get("valid"):
        return {
            "valid": False
        }

    result["raw_wiktionary"] = wiktionary_data

    return result


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