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
        return {"valid": False}

    wiktionary_context = json.dumps(
        wiktionary_data,
        ensure_ascii=False,
        indent=2
    )

    prompt = f"""
You are an expert English teacher for Korean learners.

Use the Wiktionary data below as the source.
Return ONLY valid JSON.
Do not use markdown.

Word: {vocabulary}

Return this exact JSON structure:

{{
  "valid": true,
  "vocabulary": "{vocabulary}",
  "definition": "대표 한국어 뜻",
  "entries": [
    {{
      "part_of_speech": "Verb",
      "korean_meaning": "한국어 뜻",
      "definitions": [
        "Short English definition"
      ]
    }}
  ],
  "sentence": "Natural English example sentence",
  "pronunciation": "IPA pronunciation",
  "synonyms": ["synonym1", "synonym2"],
  "antonyms": ["antonym1", "antonym2"],
  "examples": [
    "Useful English example 1",
    "Useful English example 2"
  ],
  "etymology_summary": "어원이 유용하면 한국어로 짧게, 아니면 빈 문자열",
  "usage_note": "이 표현은 ... 뉘앙스로 쓰입니다.\\n\\n실제 대화 1:\\nA: English sentence\\nB: English sentence\\n\\n실제 대화 2:\\nA: English sentence\\nB: English sentence"
}}

Rules:
- definition must be Korean.
- korean_meaning must be Korean.
- definitions must be English.
- usage_note explanation must be Korean.
- A and B conversation lines must be English only.
- Do not use Korean in A or B lines.
- usage_note must contain line breaks.
- Do not include wiki markup like {{}}, [[]], <ref>, or CSS.
- Keep everything concise.

Wiktionary data:
{wiktionary_context}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
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
        result = json.loads(content)

    except Exception as e:
        print("OPENAI WORD GENERATION ERROR:", repr(e))
        return {"valid": False}

    if not result.get("valid"):
        return {"valid": False}

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

From the user's question and answer, extract ONE useful English word or phrase worth saving.

Return ONLY valid JSON.

If there is no useful word, return:
{{
  "has_candidate": false
}}

If there is a useful word, return:
{{
  "has_candidate": true,
  "vocabulary": "English word or phrase",
  "definition": "Natural Korean meaning",
  "sentence": "Natural English example sentence",
  "synonyms": "synonym1, synonym2, synonym3",
  "usage_note": "이 표현은 ... 뉘앙스로 쓰입니다.\\n\\n실제 대화 1:\\nA: English sentence\\nB: English sentence\\n\\n실제 대화 2:\\nA: English sentence\\nB: English sentence"
}}

Rules:
- vocabulary must be English.
- definition must be Korean.
- sentence must be English.
- usage_note explanation must be Korean.
- A and B conversation lines must be English only.

Question: {question}

Answer: {answer}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
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

        result = json.loads(response.choices[0].message.content.strip())

    except Exception as e:
        print("OPENAI EXTRACT WORD ERROR:", repr(e))
        return None

    if not result.get("has_candidate"):
        return None

    return result