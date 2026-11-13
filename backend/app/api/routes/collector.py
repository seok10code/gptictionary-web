import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.services.note_source_store import save_source

router = APIRouter()


class CollectorClassificationRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=255)
    source_conversation_id: str = Field(min_length=1, max_length=255)
    identity_checked: bool = Field(..., strict=True)
    question_id: str = Field(min_length=1, max_length=255)
    previous_question_id: str | None = Field(default=None, max_length=255)
    question: str = Field(min_length=1, max_length=20000)


class CollectorSnapshot(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=255)
    source_conversation_id: str = Field(min_length=1, max_length=255)
    identity_checked: bool = Field(..., strict=True)
    title: str = Field(default="ChatGPT 대화", max_length=255)
    question_id: str = Field(min_length=1, max_length=255)
    answer_id: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=500000)
    answer: str = Field(min_length=1, max_length=1000000)
    protocol: int = Field(..., ge=3, le=3)
    admission_token: str = Field(min_length=1, max_length=256)
    previous_question_id: str | None = Field(default=None, max_length=255)
    order_known: bool = Field(default=False, strict=True)
    snapshot_stable: bool = Field(default=False, strict=True)
    captured_at: datetime | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CollectorClassification(CollectorClassificationRequest):
    pass


class CollectorBatch(BaseModel):
    snapshots: list[CollectorSnapshot] = Field(
        min_length=1, max_length=10
    )


def require_collector_auth(authorization: str | None):
    expected = os.getenv("COLLECTOR_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "수집기 연결키가 설정되지 않았습니다.")
    supplied = (
        authorization[7:]
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "수집기 연결키를 확인해주세요.")
    return expected


def require_allowed_database(db: Session):
    db.get_bind().echo = False
    db.get_bind().hide_parameters = True
    database = db.execute(text("SELECT DATABASE()")).scalar()
    if database != "dbo_dev" and not (
        database == "dbo" and os.getenv("ALLOW_PRODUCTION_NOTE_WRITES") == "1"
    ):
        raise HTTPException(400, "허용된 영어 노트 DB가 아닙니다.")


def question_fingerprint(item: CollectorClassificationRequest) -> str:
    raw = json.dumps(
        [item.conversation_id, item.question_id, item.question],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def make_admission_token(secret: str, item: CollectorClassificationRequest) -> str:
    expires = int((datetime.utcnow() + timedelta(hours=24)).timestamp())
    message = "\n".join((item.conversation_id, item.question_id,
        question_fingerprint(item), str(expires)))
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def verify_admission_token(secret: str, item: CollectorSnapshot) -> bool:
    try:
        expires_text, supplied = item.admission_token.split(".", 1)
        expires = int(expires_text)
    except (ValueError, AttributeError):
        return False
    now = int(datetime.utcnow().timestamp())
    if expires < now or expires > now + 25 * 60 * 60:
        return False
    message = "\n".join((item.conversation_id, item.question_id,
        question_fingerprint(item), str(expires)))
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


@router.post("/api/collector/classify")
def classify_collector_question(
    payload: CollectorClassification,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    secret = require_collector_auth(authorization)
    require_allowed_database(db)
    if payload.identity_checked is not True or payload.source_conversation_id != payload.conversation_id:
        raise HTTPException(400, "대화 ID 검증을 통과하지 못했습니다.")

    parent = None
    if payload.previous_question_id:
        from backend.app.models.english_note import NoteSource
        parent = db.query(NoteSource).filter_by(
            conversation_id=payload.conversation_id,
            message_id=payload.previous_question_id,
        ).first()

    try:
        from backend.app.services.note_intent_classifier import classify_learning_intent
        decision = classify_learning_intent(
            payload.question,
            parent_question=parent.question if parent else None,
        )
    except Exception as error:
        # Do not accept on model/API failure; the extension retries later.
        raise HTTPException(503, "질문 분류를 완료하지 못했습니다. 자동 재시도합니다.") from error

    accepted = decision.decision in {"direct", "followup"}
    if accepted and (not decision.evidence_quote or decision.evidence_quote not in payload.question):
        accepted = False
        decision.reason = "질문 안에서 학습 요청 근거를 확인하지 못했습니다."
    if decision.decision == "followup" and parent is None:
        accepted = False
        decision.reason = "이전의 승인된 영어 학습 질문을 찾지 못했습니다."

    return {
        "question_id": payload.question_id,
        "accepted": accepted,
        "decision": decision.decision if accepted else ("other" if decision.decision == "other" else "uncertain"),
        "reason": decision.reason,
        "admission_token": make_admission_token(secret, payload) if accepted else None,
    }


@router.post("/api/collector/snapshots")
def receive_snapshots(
    payload: CollectorBatch,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    secret = require_collector_auth(authorization)
    require_allowed_database(db)

    # 배치 전체를 검증한 뒤 저장합니다.
    for item in payload.snapshots:
        raw = json.dumps(
            [
                item.conversation_id,
                item.question_id,
                item.answer_id,
                item.question,
                item.answer,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if hashlib.sha256(raw.encode()).hexdigest() != item.content_hash:
            raise HTTPException(
                400, "스냅샷 내용과 해시가 일치하지 않습니다."
            )
        if not verify_admission_token(secret, item):
            raise HTTPException(403, "서버 질문 분류 승인이 없거나 만료됐습니다. 확장을 새로고침해주세요.")

    added = duplicates = 0
    source_ids, statuses = [], []

    try:
        for item in payload.snapshots:
            result = save_source(
                db,
                channel="browser",
                conversation_id=item.conversation_id,
                message_id=item.question_id,
                question=item.question,
                answer=item.answer,
                collection=item.title,
                answer_ids=[item.answer_id],
                source_conversation_id=item.source_conversation_id,
                identity_checked=item.identity_checked,
                auto_meta={
                    "previous_question_id": item.previous_question_id,
                    "order_known": item.order_known,
                    "snapshot_stable": item.snapshot_stable,
                    "captured_at": item.captured_at,
                },
            )

            added += int(result["created"])
            duplicates += int(not result["created"])
            source_ids.append(result["source"].id)
            statuses.append(result["source"].status)

        db.commit()

    except ValueError as error:
        db.rollback()
        raise HTTPException(400, str(error)) from error

    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            409, "동시 저장이 감지됐습니다. 다시 전송해주세요."
        ) from error

    except Exception as error:
        db.rollback()
        raise HTTPException(
            500, "스냅샷 저장에 실패했습니다."
        ) from error

    return {
        "added": added,
        "duplicates": duplicates,
        "stage": "auto_queued",
        "source_ids": source_ids,
        "source_statuses": statuses,
        "acknowledged": [
            item.content_hash for item in payload.snapshots
        ],
    }
