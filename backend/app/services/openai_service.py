import os
import re
import json

from dotenv import load_dotenv
from openai import OpenAI

from backend.app.services.wiktionary_mcp_service import lookup_wiktionary


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=20.0,
    max_retries=1,
)


async def generate_word_info(
    vocabulary: str,
    requested_meaning: str | None = None,
    requested_part_of_speech: str | None = None,
    requested_usage: str | None = None,
) -> dict:
    original_vocabulary = vocabulary.strip().lower()
    corrected_from = ""
    correction_korean_meaning = ""

    correction = correct_word_candidate(
        original_vocabulary
    )

    if correction.get("found"):
        corrected_word = str(
            correction.get("correct_word") or ""
        ).strip().lower()

        correction_korean_meaning = str(
            correction.get("korean_meaning") or ""
        ).strip()

        if corrected_word:
            vocabulary = corrected_word

            if corrected_word != original_vocabulary:
                corrected_from = original_vocabulary
        else:
            vocabulary = original_vocabulary
    else:
        vocabulary = original_vocabulary

    wiktionary_data = await lookup_wiktionary(
        vocabulary
    )

    wiktionary_context = json.dumps(
        wiktionary_data,
        ensure_ascii=False,
        indent=2,
    )

    requested_meaning = (
        requested_meaning or ""
    ).strip()

    requested_part_of_speech = (
        requested_part_of_speech or ""
    ).strip()

    requested_usage = (
        requested_usage or ""
    ).strip()

    selected_context = ""

    if (
        requested_meaning
        or requested_part_of_speech
        or requested_usage
    ):
        selected_context = f"""
The user selected a specific sense from a Korean search.

Selected Korean meaning:
{requested_meaning or "not provided"}

Selected part of speech:
{requested_part_of_speech or "not provided"}

Selected usage:
{requested_usage or "not provided"}

The selected sense MUST be entries[0].
Still include the other major useful senses.
"""

    prompt = f"""
You are an expert English dictionary writer
for Korean learners.

Input:
{original_vocabulary}

Canonical vocabulary:
{vocabulary}

{selected_context}

Return ONLY valid JSON.
Do not use markdown.

Return this exact structure:

{{
  "valid": true,
  "vocabulary": "{vocabulary}",
  "definition": "Korean meaning of entries[0]",
  "sentence": "Representative sentence of entries[0]",
  "pronunciation": "IPA or empty string",
  "synonyms": [
    "top-level synonym from entries[0]"
  ],
  "antonyms": [
    "top-level antonym from entries[0]"
  ],
  "examples": [
    "top-level example 1 from entries[0]",
    "top-level example 2 from entries[0]"
  ],
  "usage_note": "Short Korean usage note from entries[0]",
  "etymology_summary": "짧은 한국어 어원 또는 빈 문자열",
  "entries": [
    {{
      "sense_key": "stable_short_key",
      "part_of_speech": "Noun",
      "korean_meaning": "권리, 권한",
      "definitions": [
        "A legal or moral entitlement."
      ],
      "sentence": "Everyone has the right to speak freely.",
      "synonyms": [
        "entitlement",
        "privilege"
      ],
      "antonyms": [
        "restriction"
      ],
      "examples": [
        "Everyone has the right to a fair trial.",
        "Workers demanded the right to organize."
      ],
      "usage_note": "이 표현은 권리나 권한을 의미할 때 사용됩니다.",
      "conversation": [
        {{
          "speaker": "A",
          "text": "Do all citizens have the right to vote?"
        }},
        {{
          "speaker": "B",
          "text": "Yes, voting is a fundamental right."
        }}
      ],
      "writing_examples": [
        "Every citizen has the right to receive an education.",
        "Freedom of speech is widely regarded as a fundamental right."
      ],
      "search_keywords": [
        "권리",
        "권한",
        "자격"
      ]
    }}
  ]
}}

Rules:

- Include every major learner-useful sense.
- Separate senses by part of speech and actual meaning.
- Never merge unrelated meanings.
- Do not duplicate equivalent senses.
The entries array MUST contain ALL major learner-useful senses.

- Never return only one entry when the word has multiple common meanings.
- For a common polysemous word, return at least 3 entries.
- Normally return between 3 and 8 entries.
- Return one entry only when the word genuinely has only one common meaning.

For the word "right", entries MUST include at least these distinct senses:
1. Noun: 권리, 권한
2. Adjective: 옳은, 올바른, 정확한
3. Adjective: 오른쪽의
4. Noun: 오른쪽, 오른쪽 방향
5. Adverb: 오른쪽으로

Do not omit these senses for "right".

Every entry MUST contain all of these fields:

- sense_key
- part_of_speech
- korean_meaning
- definitions
- sentence
- synonyms
- antonyms
- examples
- usage_note
- conversation
- writing_examples
- search_keywords

Required content rules:

- sentence must be a complete English sentence.
- definitions must contain at least one English definition.
- examples must contain exactly two English sentences.
- conversation must contain exactly two objects.
- conversation[0].speaker must be "A".
- conversation[1].speaker must be "B".
- Both conversation text values must be complete English sentences.
- writing_examples must contain exactly two complete English sentences.
- usage_note must be a short Korean explanation only.
- Do not put dialogue or writing examples inside usage_note.
- synonyms should normally contain 2 to 6 items.
- antonyms should normally contain 1 to 4 items.
- If there is no exact antonym,
  use the closest meaningful contrast.
- Never return empty conversation or writing_examples arrays.
- Never return an empty sentence.
- Every example and dialogue must match only that sense.
- Korean meanings and usage notes must be natural Korean.
- English definitions, examples, dialogue,
  and writing examples must be English.
- sense_key must be stable, short,
  lowercase, and underscore-separated.
- When a selected sense is provided,
  it must be entries[0].
- All top-level learning fields must mirror entries[0].

Wiktionary data:

{wiktionary_context}
"""

    try:
        response = client.chat.completions.create(
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
                        "Every entry must contain non-empty "
                        "conversation and writing_examples."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.05,
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
            "OPENAI WORD GENERATION ERROR:",
            repr(exc),
        )

        return {
            "valid": False,
        }

    if not result.get("valid"):
        return {
            "valid": False,
        }

    entries = result.get("entries")

    if not isinstance(entries, list) or not entries:
        return {
            "valid": False,
        }

    minimum_entry_count = 1

    if vocabulary == "right":
        minimum_entry_count = 5
    elif len(wiktionary_data or {}) > 0:
        minimum_entry_count = 2

    if len(entries) < minimum_entry_count:
        print(
            "INSUFFICIENT WORD SENSES:",
            vocabulary,
            "count=",
            len(entries),
        )

        retry_prompt = f"""
    The previous result returned too few dictionary senses.

    Word:
    {vocabulary}

    Previous entries:
    {json.dumps(entries, ensure_ascii=False, indent=2)}

    Create a corrected COMPLETE entries array.

    Requirements:
    - Include all major learner-useful meanings.
    - Separate meanings by part of speech and actual meaning.
    - Return between 3 and 8 distinct entries for a common polysemous word.
    - Every entry must contain:
    sense_key,
    part_of_speech,
    korean_meaning,
    definitions,
    sentence,
    synonyms,
    antonyms,
    exactly 2 examples,
    usage_note,
    conversation with exactly A and B,
    exactly 2 writing_examples,
    search_keywords.

    For "right", include at least:
    1. Noun: 권리, 권한
    2. Adjective: 옳은, 올바른, 정확한
    3. Adjective: 오른쪽의
    4. Noun: 오른쪽, 오른쪽 방향
    5. Adverb: 오른쪽으로

    Return JSON only in this form:

    {{
    "entries": [
        {{
        "sense_key": "...",
        "part_of_speech": "...",
        "korean_meaning": "...",
        "definitions": ["..."],
        "sentence": "...",
        "synonyms": ["..."],
        "antonyms": ["..."],
        "examples": ["...", "..."],
        "usage_note": "...",
        "conversation": [
            {{
            "speaker": "A",
            "text": "..."
            }},
            {{
            "speaker": "B",
            "text": "..."
            }}
        ],
        "writing_examples": ["...", "..."],
        "search_keywords": ["..."]
        }}
    ]
    }}
    """

        try:
            retry_response = client.chat.completions.create(
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
                            "Generate all major dictionary senses."
                        ),
                    },
                    {
                        "role": "user",
                        "content": retry_prompt,
                    },
                ],
                temperature=0.05,
            )

            retry_result = json.loads(
                retry_response
                .choices[0]
                .message
                .content
                .strip()
            )

            retry_entries = retry_result.get(
                "entries"
            )

            if (
                isinstance(retry_entries, list)
                and len(retry_entries) > len(entries)
            ):
                entries = retry_entries
                result["entries"] = retry_entries

        except Exception as exc:
            print(
                "WORD SENSE RETRY ERROR:",
                repr(exc),
            )

    cleaned_entries = []

    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            continue

        entry = dict(raw_entry)

        sentence = str(
            entry.get("sentence") or ""
        ).strip()

        examples = entry.get("examples")

        if not isinstance(examples, list):
            examples = []

        examples = [
            str(value).strip()
            for value in examples
            if str(value).strip()
        ]

        if not sentence and examples:
            sentence = examples[0]

        if not sentence:
            sentence = (
                f"This example shows how to use "
                f"{vocabulary} naturally."
            )

        while len(examples) < 2:
            examples.append(sentence)

        entry["sentence"] = sentence
        entry["examples"] = examples[:2]

        conversation = entry.get("conversation")

        if not isinstance(conversation, list):
            conversation = []

        valid_conversation = []

        for turn in conversation:
            if not isinstance(turn, dict):
                continue

            speaker = str(
                turn.get("speaker") or ""
            ).strip().upper()

            turn_text = str(
                turn.get("text") or ""
            ).strip()

            if (
                speaker in {"A", "B"}
                and turn_text
            ):
                valid_conversation.append(
                    {
                        "speaker": speaker,
                        "text": turn_text,
                    }
                )

        if len(valid_conversation) < 2:
            valid_conversation = [
                {
                    "speaker": "A",
                    "text": (
                        f"Can you give me an example "
                        f"using {vocabulary}?"
                    ),
                },
                {
                    "speaker": "B",
                    "text": sentence,
                },
            ]

        entry["conversation"] = (
            valid_conversation[:2]
        )

        writing_examples = entry.get(
            "writing_examples"
        )

        if not isinstance(
            writing_examples,
            list,
        ):
            writing_examples = []

        writing_examples = [
            str(value).strip()
            for value in writing_examples
            if str(value).strip()
        ]

        fallback_values = (
            examples
            + [sentence]
        )

        for fallback in fallback_values:
            if len(writing_examples) >= 2:
                break

            if fallback not in writing_examples:
                writing_examples.append(
                    fallback
                )

        while len(writing_examples) < 2:
            writing_examples.append(sentence)

        entry["writing_examples"] = (
            writing_examples[:2]
        )

        entry["sense_key"] = str(
            entry.get("sense_key")
            or f"sense_{index + 1}"
        ).strip()

        entry["part_of_speech"] = str(
            entry.get("part_of_speech")
            or "Unknown"
        ).strip()

        entry["korean_meaning"] = str(
            entry.get("korean_meaning")
            or correction_korean_meaning
            or ""
        ).strip()

        entry["usage_note"] = str(
            entry.get("usage_note") or ""
        ).strip()

        cleaned_entries.append(entry)

    if not cleaned_entries:
        return {
            "valid": False,
        }

    result["entries"] = cleaned_entries

    first = cleaned_entries[0]

    result["definition"] = (
        str(result.get("definition") or "").strip()
        or first.get("korean_meaning")
        or correction_korean_meaning
        or ""
    )

    result["sentence"] = (
        str(result.get("sentence") or "").strip()
        or first.get("sentence")
        or ""
    )

    result["synonyms"] = (
        result.get("synonyms")
        or first.get("synonyms")
        or []
    )

    result["antonyms"] = (
        result.get("antonyms")
        or first.get("antonyms")
        or []
    )

    result["examples"] = (
        result.get("examples")
        or first.get("examples")
        or []
    )

    result["usage_note"] = (
        str(result.get("usage_note") or "").strip()
        or first.get("usage_note")
        or ""
    )

    result["raw_wiktionary"] = wiktionary_data
    result["corrected_from"] = corrected_from

    return result

def ask_openai(question: str) -> str:
    system_prompt = """
너는 한국인 영어 학습자를 위한 영어 선생님이다.

가장 중요한 규칙

1.
사용자가 영어 문장을 입력했다고 해서 자동으로 문장 분석하지 않는다.

2.
문장 분석은 사용자가
- 문장 분석
- 문법 분석
- 구조 분석
- 해석하면서 분석
등을 요청한 경우에만 한다.

3.
그 외에는 질문에 직접 답한다.

예시

Q.
Although I was tired, I finished my homework before going to bed.
이거 내가 전에 물어본 적 있나?

A.
나는 이전 대화를 기억하지 못한다.
문장 자체는 자연스러운 표현이다.

Q.
remote와 remote controller 차이가 뭐야?

A.
두 표현의 차이를 설명한다.

Q.
What's the difference between say and tell?

A.
차이를 설명한다.

Q.
How do you use "although"?

A.
접속사 although 사용법을 설명한다.

답변은 항상 한국어로 설명하되,
필요한 경우 영어 예문을 함께 제공한다.

절대로 사용자가 요청하지 않았는데

1. 전체 뜻
2. 문장 구조
3. 들어간 문법
4. 핵심 표현
5. 예문

형식으로 답하지 않는다.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        temperature=0.2,
    )

    return response.choices[0].message.content


def extract_word_candidate(
    question: str,
    answer: str,
) -> dict | None:
    prompt = f"""
You are an expert English teacher for Korean learners.

From the user's question and answer,
extract ONE useful English word or phrase worth saving.

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

Question:
{question}

Answer:
{answer}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={
                "type": "json_object",
            },
            messages=[
                {
                    "role": "system",
                    "content": "Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()
        result = json.loads(content)

    except Exception as e:
        print(
            "OPENAI EXTRACT WORD ERROR:",
            repr(e),
        )

        return None

    if not result.get("has_candidate"):
        return None

    return result


def correct_word_candidate(vocabulary: str) -> dict:
    prompt = f"""
You are an English vocabulary and phrase normalization assistant.

Return ONLY valid JSON.

Input:
{vocabulary}

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
            response_format={
                "type": "json_object",
            },
            messages=[
                {
                    "role": "system",
                    "content": "Return JSON only.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.1,
        )

        content = response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        print(
            "SPELL CORRECTION ERROR:",
            repr(e),
        )

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

        cleaned = content.strip()

        cleaned = re.sub(
            r"^```json\s*",
            "",
            cleaned,
        )

        cleaned = re.sub(
            r"^```\s*",
            "",
            cleaned,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        )

        try:
            return json.loads(cleaned)

        except json.JSONDecodeError:
            match = re.search(
                r"\{.*\}",
                cleaned,
                re.DOTALL,
            )

            if match:
                return json.loads(
                    match.group(0)
                )

            raise


def generate_writing_challenge(
    required_words: list[str],
) -> dict:
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
                "content": "Return valid JSON only.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={
            "type": "json_object",
        },
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
  "used_words": [
    "required word used by user"
  ],
  "missing_words": [
    "required word not used by user"
  ],
  "grammar_tags": [
    "capitalization",
    "article",
    "past_tense"
  ],
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
                "content": "Return valid JSON only.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={
            "type": "json_object",
        },
        temperature=0.2,
    )

    content = response.choices[0].message.content

    return _safe_json_loads(content)


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
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": sentence,
            },
        ],
        temperature=0.2,
    )

    return response.choices[0].message.content


def generate_daily_paragraph(
    level: str = "intermediate",
) -> dict:
    prompt = f"""
You are an English reading writer for Korean learners.

Create one engaging daily English reading in a style similar to
BBC Learning English: clear, practical, interesting, and easy to follow.

Return ONLY valid JSON.
Do not use markdown.

Learner level:
{level}

Return this exact JSON structure:

{{
  "title": "An engaging English title",
  "english_content": "A natural English reading split into 2 or 3 short paragraphs using \\\\n\\\\n.",
  "korean_translation": "A natural Korean translation split into matching paragraphs using \\\\n\\\\n.",
  "focus_words": [
    "useful word or phrase 1",
    "useful word or phrase 2",
    "useful word or phrase 3"
  ],
  "level": "{level}"
}}

Content rules:
- Write between 100 and 150 English words in total.
- Split the English reading into 2 or 3 short paragraphs.
- Insert exactly one blank line between paragraphs using \\n\\n.
- Split the Korean translation into the same paragraph structure.
- The title should be specific, interesting, and inviting.
- Avoid generic textbook titles such as:
  "The Importance of Time Management",
  "The Benefits of Exercise",
  or "The Importance of Communication."
- Prefer titles such as:
  "Why Some People Always Finish Early",
  "The Five-Minute Habit That Changed My Morning",
  or "What Happens When You Put Your Phone Away?"
- Begin with a relatable situation, question, observation, or small story.
- Use natural modern English.
- Do not make the reading childish.
- Do not make it sound like a formal essay or school textbook.
- Keep sentences clear enough for a Korean intermediate learner.
- Use a mixture of short and medium-length sentences.
- End with a useful insight, takeaway, or reflection.

Topic rules:
- Choose one practical or interesting topic.
- Possible topics include:
  daily habits, work, technology, travel, relationships,
  psychology, culture, productivity, learning, health, or communication.
- Vary the topic from day to day.
- Do not always write about productivity or self-improvement.

Focus-word rules:
- Select exactly 3 useful English words, collocations, or short expressions.
- Every focus word must appear exactly as written in english_content.
- Prefer expressions that are useful in real conversation or writing.
- Do not choose overly basic words.
- Do not choose a long sentence as a focus word.
- focus_words must contain English only.

Translation rules:
- korean_translation must be natural Korean.
- Translate the meaning naturally rather than word-for-word.
- Preserve the meaning and paragraph order of the English reading.

JSON rules:
- Return JSON only.
- Do not add explanations outside the JSON.
- Do not use markdown code fences.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={
                "type": "json_object",
            },
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You create engaging English readings "
                        "for Korean learners. "
                        "Return valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
        )

        content = response.choices[0].message.content.strip()
        result = json.loads(content)

    except Exception as e:
        print(
            "DAILY PARAGRAPH GENERATION ERROR:",
            repr(e),
        )

        return {}

    title = str(
        result.get("title", "")
    ).strip()

    english_content = str(
        result.get("english_content", "")
    ).strip()

    korean_translation = str(
        result.get("korean_translation", "")
    ).strip()

    focus_words = result.get(
        "focus_words",
        [],
    )

    if not isinstance(focus_words, list):
        focus_words = []

    cleaned_focus_words = [
        str(word).strip()
        for word in focus_words
        if str(word).strip()
    ][:3]

    if (
        not title
        or not english_content
        or not korean_translation
        or len(cleaned_focus_words) != 3
    ):
        print(
            "DAILY PARAGRAPH INVALID RESULT:",
            {
                "title": title,
                "english_content": english_content,
                "focus_words": cleaned_focus_words,
            },
        )

        return {}

    return {
        "title": title,
        "english_content": english_content,
        "korean_translation": korean_translation,
        "focus_words": cleaned_focus_words,
        "level": (
            str(
                result.get(
                    "level",
                    level,
                )
            ).strip()
            or level
        ),
    }


def ask_daily_paragraph(
    english_content: str,
    question: str,
) -> str:
    prompt = f"""
너는 한국인 영어 학습자를 위한 영어 읽기 선생님이다.

아래 영어 문단만을 기준으로 사용자의 질문에 답해라.

영어 문단:
{english_content}

사용자 질문:
{question}

규칙:
- 답변은 한국어로 쉽게 설명한다.
- 필요한 경우 영어 표현이나 문장을 인용해서 설명한다.
- 문단에 없는 내용을 사실처럼 지어내지 않는다.
- 질문이 단어 뜻이면 문단 속 의미와 뉘앙스를 설명한다.
- 질문이 문법이면 해당 문장을 중심으로 설명한다.
- 질문이 내용 이해 질문이면 문단의 근거를 들어 답한다.
- 답변은 너무 길지 않게 작성한다.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an English reading tutor "
                        "for Korean learners. "
                        "Answer based only on the provided paragraph."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
        )

        return (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

    except Exception as e:
        print(
            "DAILY PARAGRAPH QUESTION ERROR:",
            repr(e),
        )

        return "질문에 답변을 생성하는 중 오류가 발생했습니다."
