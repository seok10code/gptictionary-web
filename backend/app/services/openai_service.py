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
    original_vocabulary = vocabulary.strip().lower()
    corrected_from = ""
    correction_korean_meaning = ""

    correction = correct_word_candidate(original_vocabulary)

    if correction.get("found"):
        corrected_word = correction.get("correct_word", "").strip().lower()
        correction_korean_meaning = correction.get("korean_meaning", "")

        if corrected_word:
            vocabulary = corrected_word
            if corrected_word != original_vocabulary:
                corrected_from = original_vocabulary
        else:
            vocabulary = original_vocabulary
    else:
        vocabulary = original_vocabulary

    wiktionary_data = await lookup_wiktionary(vocabulary)

    wiktionary_context = json.dumps(
        wiktionary_data,
        ensure_ascii=False,
        indent=2
    )

    prompt = f"""
You are an expert English teacher for Korean learners.

The input may be:
- a single English word
- an idiom
- a phrase
- a phrasal verb
- a collocation
- a slightly incorrect expression that should be corrected to a natural standard form

Return ONLY valid JSON.
Do not use markdown.

Input: {original_vocabulary}
Canonical vocabulary to explain: {vocabulary}

Important:
- If the input is a common expression or phrase, it is valid.
- If Wiktionary data is missing or weak, use your own English knowledge.
- If the input is unnatural but clearly intended, explain the corrected canonical expression.
- Example: "pinch penny" should become "pinch pennies".
- Example: "awash with" is valid.
- Example: "come out" is valid.

Return this exact JSON structure:

{{
  "valid": true,
  "vocabulary": "{vocabulary}",
  "definition": "대표 한국어 뜻",
  "entries": [
    {{
      "part_of_speech": "Expression",
      "korean_meaning": "한국어 뜻",
      "definitions": [
        "Short English definition"
      ]
    }}
  ],
  "sentence": "Natural English example sentence",
  "pronunciation": "IPA pronunciation if useful, otherwise empty string",
  "synonyms": ["synonym1", "synonym2"],
  "antonyms": ["antonym1", "antonym2"],
  "examples": [
    "Useful English example 1",
    "Useful English example 2"
  ],
  "etymology_summary": "어원이 유용하면 한국어로 짧게, 아니면 빈 문자열",
  "usage_note": "이 표현은 ... 뉘앙스로 쓰입니다.\\n\\n💬 실제 대화\\n\\nA: English sentence\\nB: English sentence\\n\\n📝 글쓰기 예문\\n\\nFormal writing example sentence 1.\\n\\nFormal writing example sentence 2."
}}

Rules:
- valid must be true if the input can be understood as a useful English word, phrase, idiom, or expression.
- definition must be Korean.
- korean_meaning must be Korean.
- definitions must be English.
- usage_note explanation must be Korean.
- A and B conversation lines must be English only.
- Do not use Korean in A or B lines.
- usage_note must contain line breaks.
- Do not include wiki markup like {{}}, [[]], <ref>, or CSS.
- Keep everything concise.
- usage_note must include exactly ONE short real-life conversation.
- usage_note must include exactly TWO formal writing example sentences.
- Formal writing examples must be English only.
- Do not create a second conversation.

Wiktionary data:
{wiktionary_context}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt}
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
    result["corrected_from"] = corrected_from

    if correction_korean_meaning and not result.get("definition"):
        result["definition"] = correction_korean_meaning

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
  "usage_note": "이 표현은 ... 뉘앙스로 쓰입니다.\\n\\n💬 실제 대화\\n\\nA: English sentence\\nB: English sentence\\n\\n📝 글쓰기 예문\\n\\nFormal writing example sentence 1.\\n\\nFormal writing example sentence 2."
}}

Rules:
- vocabulary must be English.
- vocabulary can be a word, idiom, phrasal verb, collocation, or useful expression.
- definition must be Korean.
- sentence must be English.
- usage_note explanation must be Korean.
- A and B conversation lines must be English only.
- usage_note must include exactly ONE short real-life conversation.
- usage_note must include exactly TWO formal writing example sentences.
- Formal writing examples must be English only.
- Do not create a second conversation.

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


def correct_word_candidate(vocabulary: str) -> dict:
    prompt = f"""
You are an English vocabulary and phrase normalization assistant.

Return ONLY valid JSON.

Input: {vocabulary}

Your job:
- Accept single words, idioms, phrasal verbs, collocations, and useful expressions.
- If the input is slightly unnatural or grammatically wrong, convert it to the natural standard form.
- Do not reject useful English expressions just because they are more than one word.

Examples:
- pinch penny -> pinch pennies
- awash with -> awash with
- come out -> come out
- This is it -> this is it
- head check -> head check
- shoulder check -> shoulder check

If the input is a useful English word or expression:

{{
  "found": true,
  "correct_word": "standard word or expression",
  "korean_meaning": "짧은 한국어 뜻"
}}

If you cannot understand it as English at all:

{{
  "found": false,
  "correct_word": "",
  "korean_meaning": ""
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        print("SPELL CORRECTION ERROR:", repr(e))
        return {
            "found": False,
            "correct_word": "",
            "korean_meaning": "",
        }


def _safe_json_loads(content: str) -> dict:
    content = content.strip()

    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "").strip()
    elif content.startswith("```"):
        content = content.replace("```", "").strip()

    return json.loads(content)


def generate_writing_challenge(required_words: list[str]) -> dict:
    words_text = ", ".join(required_words)

    prompt = f"""
You are an English writing coach for a Korean learner.

Create ONE practical writing challenge.
The learner must use ALL required words naturally.

Required words:
{words_text}

Rules:
- Topic should be easy enough for daily writing.
- Topic should naturally encourage the required words.
- Korean instruction should be friendly and clear.
- Return JSON only.

JSON format:
{{
  "topic": "Describe a situation where you had to save money while dealing with many people.",
  "required_words": {required_words},
  "recommended_grammar": "past tense",
  "target_words": "80-120 words",
  "instruction_ko": "아래 필수 단어를 모두 사용해서 80~120단어 영어 글을 작성해보세요."
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return _safe_json_loads(response.choices[0].message.content)


def correct_writing_challenge(
    original_text: str,
    topic: str,
    required_words: list[str],
) -> dict:
    words_text = ", ".join(required_words)

    prompt = f"""
You are an English writing coach for a Korean learner.

Topic:
{topic}

Required words:
{words_text}

User writing:
{original_text}

Your job:
1. Correct grammar.
2. Rewrite it naturally.
3. Check ONLY the required words for used_words and missing_words.
4. Do NOT count normal words like I, am, my, name as used words unless they are required words.
5. Explain mistakes in Korean.
6. Extract grammar mistake tags.

Return JSON only.

JSON format:
{{
  "overall_score": 85,
  "grammar_score": 85,
  "vocab_score": 80,
  "word_usage_score": 70,
  "corrected_text": "...",
  "natural_text": "...",
  "used_words": ["required word used by user"],
  "missing_words": ["required word not used by user"],
  "grammar_tags": ["capitalization", "article", "past_tense"],
  "feedback": [
    {{
      "type": "grammar",
      "tag": "capitalization",
      "original": "i am sukwon kim",
      "corrected": "My name is Sukwon Kim.",
      "explanation_ko": "문장의 첫 글자와 이름은 대문자로 써야 합니다."
    }}
  ],
  "short_review_ko": "전체적으로 의미는 전달되지만, 문장 시작 대문자와 자기소개 표현을 다듬으면 더 자연스럽습니다."
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    return _safe_json_loads(response.choices[0].message.content)