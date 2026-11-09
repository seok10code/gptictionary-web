"""Lifecycle bridge for the question/answer DB queue. Legacy conversation loops are retired."""
import asyncio
import os

async def save_word(db, word):
    from backend.app.services.word_service import search_word
    return await search_word(db=db, vocabulary=word.vocabulary,
        requested_meaning=word.requested_meaning or None,
        requested_part_of_speech=word.requested_part_of_speech or None,
        requested_usage=word.requested_usage or None)

async def start_worker(app):
    if os.getenv("NOTE_AUTO_ENABLED", "1").lower() in {"0", "false", "off"}:
        print("영어 질문 큐: 설정으로 꺼져 있습니다.")
        return
    from backend.app.services.note_pair_worker import start_worker as start_pairs
    await start_pairs(app)


async def stop_worker(app):
    task = getattr(app.state, "note_auto_task", None)
    if task:
        app.state.note_auto_stop.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
