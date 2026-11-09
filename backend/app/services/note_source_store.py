import hashlib
import json
from datetime import datetime

from backend.app.models.english_note import NoteSource
from backend.app.models.note_source_evidence import NoteSourceEvidence


def fingerprint(values):
    raw = json.dumps(values, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_source(
    db, *,
    channel,
    conversation_id,
    message_id,
    question,
    answer,
    collection,
    context="",
    answer_ids=None,
    source_conversation_id=None,
    identity_checked=False,
    auto_meta=None,
):
    # commit은 이 함수를 호출하는 가져오기/API 쪽에서 수행합니다.
    if channel not in {"file", "browser"}:
        raise ValueError("지원하지 않는 수집 출처입니다.")

    for name, value in [
        ("conversation_id", conversation_id),
        ("message_id", message_id),
    ]:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 255
        ):
            raise ValueError(f"{name}를 확인해주세요.")

    if not isinstance(question, str) or not question.strip():
        raise ValueError("질문이 비어 있습니다.")

    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("답변이 비어 있습니다.")

    answer_ids = [] if answer_ids is None else answer_ids

    if not isinstance(answer_ids, list):
        raise ValueError("답변 메시지 ID는 목록이어야 합니다.")

    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 255
        for value in answer_ids
    ):
        raise ValueError("답변 메시지 ID를 확인해주세요.")

    answer_ids = list(dict.fromkeys(answer_ids))

    if channel == "browser" and (
        identity_checked is not True
        or source_conversation_id != conversation_id
        or not answer_ids
    ):
        raise ValueError("브라우저 대화 ID 검증을 통과하지 못했습니다.")

    # 원본 버전 식별: 기존 가져오기와 같은 기준입니다.
    key = fingerprint([
        conversation_id, message_id, question, answer,
    ])

    # 본문이 달라도 같은 질문으로 묶기 위한 키입니다.
    question_key = fingerprint([conversation_id, message_id])

    source = db.query(NoteSource).filter_by(source_key=key).first()
    created = source is None
    promoted = False

    if created:
        source = NoteSource(
            source_key=key,
            conversation_id=conversation_id,
            message_id=message_id,
            question=question,
            answer=answer,
            collection=str(collection or "ChatGPT 대화")[:255],
            context=context or "",
            status="pending" if channel == "file" else "draft",
        )
        db.add(source)
        db.flush()

    elif channel == "file":
        # 파일에서 정확히 일치하는 원본을 확인한 경우에만 보완합니다.
        source.collection = str(collection or "ChatGPT 대화")[:255]
        source.context = context or source.context or ""

        if source.status == "draft":
            source.status = "pending"
            promoted = True

    evidence = db.query(NoteSourceEvidence).filter_by(
        source_id=source.id,
        channel=channel,
    ).first()

    if evidence is None:
        evidence = NoteSourceEvidence(
            source_id=source.id,
            channel=channel,
            question_key=question_key,
        )
        db.add(evidence)

    evidence.identity_state = (
        "from_file" if channel == "file" else "matched"
    )
    evidence.completion_state = (
        "exported" if channel == "file" else "snapshot"
    )
    evidence.answer_ids = sorted(set(
        (evidence.answer_ids or []) + answer_ids
    ))
    evidence.last_seen_at = datetime.utcnow()

    db.flush()

    if auto_meta is not None:
        from backend.app.services.note_pair_queue import enqueue
        enqueue(db, source, channel, auto_meta)

    return {
        "source": source,
        "evidence": evidence,
        "created": created,
        "promoted": promoted,
    }
