import hashlib
import os
from pathlib import Path

from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent.parent

AUDIO_DIR = BASE_DIR / "static" / "audio" / "flashcards"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다."
        )

    return OpenAI(api_key=api_key)


def make_cache_key(
    text: str,
    voice: str,
    audio_type: str,
) -> str:
    raw_value = f"{voice}:{audio_type}:{text.strip()}"

    return hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()


def generate_tts_audio(
    text: str,
    audio_type: str = "word",
    voice: str = "marin",
) -> Path:
    clean_text = text.strip()

    if not clean_text:
        raise ValueError("TTS text cannot be empty.")

    cache_key = make_cache_key(
        text=clean_text,
        voice=voice,
        audio_type=audio_type,
    )

    audio_path = AUDIO_DIR / f"{cache_key}.mp3"

    if audio_path.exists():
        return audio_path

    if audio_type == "sentence":
        instructions = (
            "Speak naturally in clear American English. "
            "Use a calm, warm, educational tone. "
            "Read at a slightly slower pace for an English learner."
        )
    else:
        instructions = (
            "Pronounce this English word clearly and naturally. "
            "Use a calm American English voice. "
            "Speak slightly slowly, with no extra explanation."
        )

    client = get_openai_client()

    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=clean_text,
        instructions=instructions,
        response_format="mp3",
    ) as response:
        response.stream_to_file(audio_path)

    return audio_path
