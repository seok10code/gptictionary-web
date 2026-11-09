import hashlib
import hmac
import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.services.note_source_store import save_source

router = APIRouter()


class CollectorSnapshot(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=255)
    source_conversation_id: str = Field(min_length=1, max_length=255)
    identity_checked: bool = Field(..., strict=True)
    title: str = Field(default="ChatGPT 대화", max_length=255)
    question_id: str = Field(min_length=1, max_length=255)
    answer_id: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=500000)
    answer: str = Field(min_length=1, max_length=1000000)
    protocol: int = Field(default=1, ge=1, le=2)
    previous_question_id: str | None = Field(default=None, max_length=255)
    order_known: bool = Field(default=False, strict=True)
    snapshot_stable: bool = Field(default=False, strict=True)
    captured_at: datetime | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CollectorBatch(BaseModel):
    snapshots: list[CollectorSnapshot] = Field(
        min_length=1, max_length=10
    )


@router.post("/api/collector/snapshots")
def receive_snapshots(
    payload: CollectorBatch,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    expected = os.getenv("COLLECTOR_API_TOKEN", "")

    if not expected:
        raise HTTPException(503, "수집기 연결키가 설정되지 않았습니다.")

    supplied = (
        authorization[7:]
        if authorization and authorization.startswith("Bearer ")
        else ""
    )

    if not supplied or not hmac.compare_digest(
        supplied.encode(), expected.encode()
    ):
        raise HTTPException(401, "수집기 연결키를 확인해주세요.")

    # 수집한 본문이 SQL 상세 로그에 출력되지 않도록 합니다.
    db.get_bind().echo = False
    db.get_bind().hide_parameters = True

    database = db.execute(text("SELECT DATABASE()")).scalar()
    if database != "dbo_dev":
        raise HTTPException(400, "현재 단계에서는 dbo_dev에만 저장합니다.")

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
                } if item.protocol == 2 else None,
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
        "stage": "auto_queued" if all(item.protocol == 2 for item in payload.snapshots) else "stored",
        "source_ids": source_ids,
        "source_statuses": statuses,
        "acknowledged": [
            item.content_hash for item in payload.snapshots
        ],
    }
