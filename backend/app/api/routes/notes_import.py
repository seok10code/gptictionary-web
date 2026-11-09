from fastapi import Query
from sqlalchemy import func, or_
from backend.app.models.note_source_evidence import NoteSourceEvidence
import hashlib
import json

from fastapi import (
    APIRouter, Depends, File, Form,
    HTTPException, Request, UploadFile,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.models.english_note import NoteSource
from sqlalchemy.exc import IntegrityError
from backend.app.services.note_source_store import save_source

from backend.app.models.note_auto import AutoConversation
from backend.app.services.note_auto_ingest import STATUSES, finish_file_branch, source_view

router = APIRouter()


def parse_pairs(data, title_filter=""):
    if not isinstance(data, list):
        raise ValueError("JSON 최상위는 대화 목록이어야 합니다.")

    for conv in data:
        if not isinstance(conv, dict):
            raise ValueError("대화 항목 형식이 올바르지 않습니다.")

        title = str(conv.get("title") or "제목 없는 대화")
        if title_filter.casefold() not in title.casefold():
            continue

        cid = str(conv.get("id") or conv.get("conversation_id") or "")
        if not cid or len(cid) > 255:
            raise ValueError("대화 ID가 없거나 너무 깁니다.")

        mapping = conv.get("mapping")
        if not isinstance(mapping, dict):
            raise ValueError("ChatGPT conversations.json 형식인지 확인해주세요.")

        current = conv.get("current_node")
        if not current or current not in mapping:
            raise ValueError("선택된 대화 경로를 찾을 수 없습니다.")

        chain, seen = [], set()

        while current:
            if current in seen or current not in mapping:
                raise ValueError("대화 경로가 손상되었습니다.")

            seen.add(current)
            node = mapping[current]
            message = node.get("message")

            if message:
                role = (message.get("author") or {}).get("role")
                parts = (message.get("content") or {}).get("parts") or []
                body = "\n".join(
                    part for part in parts if isinstance(part, str)
                ).strip()

                if body and role in {"user", "assistant"}:
                    chain.append((
                        str(message.get("id") or current),
                        role,
                        body,
                    ))

            current = node.get("parent")

        question, answers, history, answer_ids = None, [], [], []
        previous_id = None

        def build():
            mid, body = question
            if len(mid) > 255:
                raise ValueError("메시지 ID가 너무 깁니다.")

            answer = "\n\n".join(answers)
            raw = json.dumps(
                [cid, mid, body, answer],
                ensure_ascii=False,
            )

            return {
                "source_key": hashlib.sha256(raw.encode()).hexdigest(),
                "conversation_id": cid,
                "message_id": mid,
                "collection": title[:255],
                "question": body,
                "answer": answer,
                "answer_ids": list(dict.fromkeys(answer_ids)),
                "context": "\n".join(history[-6:]),
                "auto_meta": {"order_known": True, "previous_question_id": previous_id,
                              "snapshot_stable": True},
            }

        # 현재 선택된 분기의 대화만 시간순으로 읽습니다.
        for mid, role, body in reversed(chain):
            if role == "user":
                if question and answers:
                    pair = build()
                    yield pair
                    history.extend([pair["question"], pair["answer"]])
                    previous_id = question[0]

                question, answers, answer_ids = (mid, body), [], []

            elif question:
                answers.append(body)
                answer_ids.append(mid)

        if question and answers:
            yield build()



ARCHIVE_STATUS_LABELS = {
    "draft": "임시 수집",
    "pending": "분석 대기",
    "processing": "분석 중",
    "done": "정리 완료",
    "error": "재처리 필요",
    "ignored": "학습 대상 아님",
}

def archive_evidence_condition(channel=None):
    condition = or_(
        (NoteSourceEvidence.channel == "file")
        & (NoteSourceEvidence.identity_state == "from_file"),
        (NoteSourceEvidence.channel == "browser")
        & (NoteSourceEvidence.identity_state == "matched"),
    )
    if channel in {"file", "browser"}:
        condition = condition & (NoteSourceEvidence.channel == channel)
    return condition

def archive_source_query(db, channel, q):
    known = db.query(NoteSourceEvidence.id).filter(
        NoteSourceEvidence.source_id == NoteSource.id,
        archive_evidence_condition(),
    ).exists()
    query = db.query(NoteSource)
    if channel == "unverified":
        query = query.filter(~known, NoteSource.status != "ignored")
    elif channel == "excluded":
        query = query.filter(NoteSource.status == "ignored")
    else:
        query = query.filter(known, NoteSource.status != "ignored")
        if channel in {"file", "browser"}:
            query = query.filter(db.query(NoteSourceEvidence.id).filter(
                NoteSourceEvidence.source_id == NoteSource.id,
                archive_evidence_condition(channel),
            ).exists())
    if q.strip():
        query = query.filter(or_(
            NoteSource.collection.contains(q.strip(), autoescape=True),
            NoteSource.question.contains(q.strip(), autoescape=True),
            NoteSource.answer.contains(q.strip(), autoescape=True),
        ))
    return query

def archive_badges(db, source_ids):
    result = {source_id: [] for source_id in source_ids}
    if source_ids:
        rows = db.query(NoteSourceEvidence).filter(
            NoteSourceEvidence.source_id.in_(source_ids),
            archive_evidence_condition(),
        ).all()
        for row in rows:
            result[row.source_id].append(
                "파일" if row.channel == "file" else "브라우저 · ID 확인"
            )
    return result

@router.get("/notes/import")
def import_page(
    request: Request, added: int = 0, skipped: int = 0, promoted: int = 0,
    channel: str = "all", q: str = Query("", max_length=200),
    page: int = Query(1, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    import secrets
    request.session.setdefault("english_notes_csrf", secrets.token_urlsafe(32))
    if channel not in {"all", "file", "browser", "unverified", "excluded"}:
        channel = "all"
    query = archive_source_query(db, channel, q)
    grouped = query.with_entities(
        NoteSource.conversation_id, NoteSource.message_id,
        func.max(NoteSource.id).label("latest_id"),
        func.count(NoteSource.id).label("versions"),
    ).group_by(NoteSource.conversation_id, NoteSource.message_id)
    question_count = grouped.count()
    version_count = query.count()
    groups = grouped.order_by(
        func.max(NoteSource.id).desc()
    ).offset((page - 1) * 20).limit(21).all()
    ids = [group.latest_id for group in groups[:20]]
    rows = db.query(
        NoteSource.id, NoteSource.collection, NoteSource.status,
        func.substr(NoteSource.question, 1, 180).label("question_preview"),
        func.substr(NoteSource.answer, 1, 240).label("answer_preview"),
    ).filter(NoteSource.id.in_(ids)).all() if ids else []
    by_id = {row.id: row for row in rows}
    badges = archive_badges(db, ids)
    cards = [
        dict(by_id[group.latest_id]._mapping,
             versions=group.versions, badges=badges[group.latest_id])
        for group in groups[:20]
    ]
    return templates.TemplateResponse(
        request=request, name="notes_import.html", context={
            "auto_conversations": db.query(AutoConversation).order_by(AutoConversation.updated_at.desc()).limit(30).all(),
            "auto_statuses": STATUSES,
            "cards": cards, "channel": channel, "q": q, "page": page,
            "question_count": question_count, "version_count": version_count,
            "unverified_count": archive_source_query(db, "unverified", "").count(),
            "has_more": len(groups) > 20,
            "added": added, "skipped": skipped, "promoted": promoted,
            "status_labels": ARCHIVE_STATUS_LABELS,
        },
    )

@router.get("/notes/sources/{source_id}")
def note_source_detail(
    source_id: int, request: Request,
    version_page: int = Query(1, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    import secrets
    request.session.setdefault('english_notes_csrf', secrets.token_urlsafe(32))
    source = db.get(NoteSource, source_id)
    if source is None:
        raise HTTPException(404, "원본을 찾을 수 없습니다.")
    history = db.query(NoteSource).filter(
        NoteSource.conversation_id == source.conversation_id,
        NoteSource.message_id == source.message_id,
    )
    total = history.count()
    current_version = history.filter(NoteSource.id <= source.id).count()
    offset = (version_page - 1) * 10
    rows = history.with_entities(
        NoteSource.id, NoteSource.status,
        func.substr(NoteSource.answer, 1, 120).label("preview"),
    ).order_by(NoteSource.id.desc()).offset(offset).limit(11).all()
    badges = archive_badges(db, [row.id for row in rows[:10]] + [source.id])
    versions = [
        dict(row._mapping, number=total-offset-i, badges=badges[row.id])
        for i, row in enumerate(rows[:10])
    ]
    return templates.TemplateResponse(
        request=request, name="note_source_detail.html", context={
            "auto_view": source_view(db, source),
            "source": source, "badges": badges[source.id],
            "versions": versions, "version_count": total,
            "current_version": current_version,
            "version_page": version_page, "has_more": len(rows) > 10,
            "status_labels": ARCHIVE_STATUS_LABELS,
        },
    )

@router.post("/notes/import")
def upload_conversations(
    file: UploadFile = File(...),
    title_filter: str = Form(""),
    db: Session = Depends(get_db),
):
    db.get_bind().echo = False
    db.get_bind().hide_parameters = True

    if db.execute(text("SELECT DATABASE()")).scalar() != "dbo_dev":
        raise HTTPException(400, "현재 단계에서는 dbo_dev에만 저장합니다.")

    raw = file.file.read(100 * 1024 * 1024 + 1)
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(413, "100MB 이하 conversations.json을 선택해 주세요.")

    added = skipped = promoted = 0
    manifests = {}

    try:
        data = json.loads(raw)

        for pair in parse_pairs(data, title_filter.strip()):
            values = {
                key: value
                for key, value in pair.items()
                if key != "source_key"
            }

            result = save_source(db, channel="file", **values)
            manifests.setdefault(pair["conversation_id"], []).append(pair["message_id"])

            added += int(result["created"])
            promoted += int(result["promoted"])
            skipped += int(
                not result["created"] and not result["promoted"]
            )

        for cid, ids in manifests.items():
            finish_file_branch(db, cid, ids)
        db.commit()

    except (ValueError, TypeError, KeyError, AttributeError) as error:
        db.rollback()
        raise HTTPException(
            400, "JSON 형식을 확인해주세요: " + str(error)
        ) from error

    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            409, "동시 저장이 감지됐습니다. 파일을 다시 가져와주세요."
        ) from error

    except Exception as error:
        db.rollback()
        raise HTTPException(500, "원본 저장에 실패했습니다.") from error

    return RedirectResponse(
        f"/notes/import?added={added}&skipped={skipped}&promoted={promoted}",
        status_code=303,
    )

ARCHIVE_STATUS_LABELS["notes_ready"] = "노트 정리 완료"

ARCHIVE_STATUS_LABELS.update({"word_ready": "단어장 처리 대상", "auto_waiting": "자동 정리 대기"})
