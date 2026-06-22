import os
import json
from dotenv import load_dotenv
from openai import OpenAI

import re
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
    system_prompt = """
너는 한국인 영어 학습자를 위한 영어 선생님이다.

사용자의 질문 의도를 먼저 파악한 후 답변한다.

규칙:
- 문법 질문이면 문법 중심으로 설명한다.
- 번역 질문이면 자연스러운 뜻을 설명한다.
- 단어 질문이면 뜻, 뉘앙스, 예문을 설명한다.
- 단순 번역만 하지 않는다.
- 영어 학습에 도움이 되도록 설명한다.

문법 질문 답변 형식:

1. 전체 뜻
2. 문장 구조
3. 들어간 문법
4. 핵심 표현
5. 예문

예시:

1. 전체 뜻
이란은 이제 석유를 팔 수 있다. 얼마나 빨리 생산량을 늘릴 수 있을까?

2. 문장 구조
Iran / can now sell / oil.
How fast / can / it / ramp up?

3. 들어간 문법
- can + 동사원형
- How fast + can + 주어 + 동사
- ramp up (구동사)

4. 핵심 표현
ramp up = 생산량이나 규모를 늘리다

5. 예문
The company ramped up production.
How quickly can they ramp up hiring?
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": question
            }
        ],
        temperature=0.2,
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



def _safe_json_loads(content: str):
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("JSON PARSE FAILED RAW CONTENT:")
        print(content)

        # ```json ... ``` 제거 대응
        cleaned = content.strip()
        cleaned = re.sub(r"^```json\s*", "", cleaned)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 본문 중 첫 { ... } 만 추출
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))

            raise

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
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    content = response.choices[0].message.content

    print("=" * 50)
    print("WRITING CHALLENGE RAW RESPONSE")
    print(content)
    print("=" * 50)

    return _safe_json_loads(content)


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
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    return _safe_json_loads(response.choices[0].message.content)


def analyze_sentence(sentence: str) -> str:
    system_prompt = """
너는 한국인 영어 학습자를 위한 문장 분석 선생님이다.

사용자가 입력한 영어 문장을 아래 형식으로 분석한다.

규칙:
- 한국어로 쉽게 설명한다.
- 문장 구조를 끊어서 보여준다.
- 핵심 문법과 표현을 따로 정리한다.
- 마지막에 비슷한 예문을 2개 준다.

답변 형식:

1. 전체 뜻

2. 문장 구조

3. 들어간 문법

4. 핵심 표현

5. 비슷한 예문
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": sentence},
        ],
        temperature=0.2,
    )

    return response.choices[0].message.content