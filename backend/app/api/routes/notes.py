import hmac
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend.app.db.database import get_db
from backend.app.models.english_note import EnglishNote, NoteSection, NoteSourceLink, NoteSource
from backend.app.services.note_learning import KINDS, NoteProblem, study_note
from backend.app.services.note_list_tags import note_tags
from backend.app.models.note_auto import AutoConversation, AutoTopic
from backend.app.models.note_pair_queue import NotePairDocument,NotePairJob
from backend.app.services.note_auto_ingest import request_retry, conversation_key
from backend.app.services.note_study import display_text, study_view
from backend.app.services.note_reading import reading_view, reading_preview, rich_text
from backend.app.services.note_document import topic_turns,article_view,document_text,document_preview,DOCUMENT_VERSION

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
templates.env.filters["note_text"] = display_text
templates.env.filters["note_rich_text"] = rich_text
templates.env.filters["note_document_text"] = document_text


def token(request):
    return request.session.setdefault("english_notes_csrf", secrets.token_urlsafe(32))


def local_day_utc_range(value):
    from datetime import date, time, timezone
    from zoneinfo import ZoneInfo
    try:
        selected_day = date.fromisoformat(value)
        if selected_day.isoformat() != value:
            return None
        local_tz = ZoneInfo("Asia/Seoul")
        local_start = datetime.combine(selected_day, time.min, tzinfo=local_tz)
        local_end = datetime.combine(date.fromordinal(selected_day.toordinal() + 1), time.min, tzinfo=local_tz)
        return (local_start.astimezone(timezone.utc).replace(tzinfo=None),
                local_end.astimezone(timezone.utc).replace(tzinfo=None))
    except (ValueError, OverflowError):
        return None


def check_csrf(request, csrf):
    expected = request.session.get("english_notes_csrf", "")
    origin = request.headers.get("origin")
    if (not expected or not hmac.compare_digest(expected, csrf)
            or (origin and urlsplit(origin).netloc != request.url.netloc)):
        raise HTTPException(403, "화면을 새로고침한 뒤 다시 실행해 주세요.")


def note_scope(db):
    managed = db.query(AutoTopic.key).filter(AutoTopic.note_id == EnglishNote.id).exists()
    current = db.query(AutoTopic.key).join(AutoConversation, AutoConversation.key == AutoTopic.conversation_key).filter(
        AutoTopic.note_id == EnglishNote.id, AutoTopic.active.is_(True)).exists()
    # Hide old manual notes while their conversations await their first unified analysis.
    pending_legacy = db.query(NoteSourceLink.id).join(NoteSource, NoteSource.id == NoteSourceLink.source_id).join(
        AutoConversation, AutoConversation.conversation_id == NoteSource.conversation_id).filter(
        NoteSourceLink.note_id == EnglishNote.id, AutoConversation.processed_revision < AutoConversation.revision).exists()
    paired = db.query(NotePairDocument.note_id).filter(NotePairDocument.note_id == EnglishNote.id).exists()
    return or_(paired, current, ~managed)


@router.get("/notes")
def notes_page(request: Request, state: str = "all", kind: str = "",
               q: str = Query("", max_length=200), page: int = Query(1, ge=1, le=100000),
               day: str = Query("", max_length=10), sort: str = "newest",
               db: Session = Depends(get_db)):
    token(request)
    if sort not in {"newest", "oldest"}:
        sort = "newest"
    day_range = local_day_utc_range(day) if day else None
    if day and day_range is None:
        day = ""
    day_start, day_end = day_range if day_range else (None, None)
    if state not in {"study", "all", "new", "updated", "due"}:
        state = "all"
    new = EnglishNote.studied_version == 0
    updated = (EnglishNote.studied_version > 0) & (EnglishNote.version > EnglishNote.studied_version)
    due = (EnglishNote.studied_version > 0) & (EnglishNote.next_review_at <= datetime.utcnow())
    counts = {key: db.query(EnglishNote.id).filter(note_scope(db), condition).count()
              for key, condition in (("new", new), ("updated", updated), ("due", due))}
    unfinished = db.query(NotePairJob).filter(NotePairJob.status.in_(['waiting','running','retry','failed']))
    processing = {"total": unfinished.count(),
                  "failed": unfinished.filter(NotePairJob.status.in_(['failed','retry'])).count()}
    query = db.query(EnglishNote).filter(note_scope(db))
    if state == "study":
        query = query.filter(or_(new, updated, due))
    elif state in {"new", "updated", "due"}:
        query = query.filter({"new": new, "updated": updated, "due": due}[state])
    if day_start is not None:
        query = query.filter(EnglishNote.updated_at >= day_start, EnglishNote.updated_at < day_end)
    if kind in KINDS:
        query = query.filter(EnglishNote.kind == kind)
    if q.strip():
        matches = db.query(NoteSection.id).filter(NoteSection.note_id == EnglishNote.id,
            NoteSection.body.contains(q.strip(), autoescape=True)).exists()
        query = query.filter(or_(EnglishNote.title.contains(q.strip(), autoescape=True),
            EnglishNote.subject.contains(q.strip(), autoescape=True),
            EnglishNote.keywords.contains(q.strip(), autoescape=True), matches))
    ordering = (EnglishNote.updated_at.asc(), EnglishNote.id.asc()) if sort == "oldest" else (EnglishNote.updated_at.desc(), EnglishNote.id.desc())
    rows = query.order_by(*ordering).offset((page-1)*20).limit(21).all()
    # Only read bounded previews, rather than every historical section body.
    from sqlalchemy import func
    cards = []
    for note in rows[:20]:
        section = db.query(NoteSection).filter(NoteSection.note_id == note.id).order_by(NoteSection.version.desc()).first()
        binding = db.query(AutoTopic).filter_by(note_id=note.id, active=True).first()
        view = study_view(binding, section)
        doc=(binding.data or {}).get('document') if binding else None
        summary=(doc or {}).get('summary','') if (doc and doc.get('version') in {2,DOCUMENT_VERSION} and doc.get('format')=='textbook' and section and doc.get('section_hash')==section.content_hash
                and doc.get('source_ids')==((binding.data or {}).get('plan') or {}).get('source_ids')) else ''
        pair_doc=db.get(NotePairDocument,note.id)
        preview=summary or document_preview(db,binding,section)
        if pair_doc:
            from backend.app.services.note_pair_editor import plain_body
            preview=plain_body(pair_doc.document)[:240]
            view=None
        cards.append({"note": note, "title": doc.get("title") if summary else note.title, "preview": preview,
                      "tags": note_tags(note.title, note.subject, note.keywords,
                          document=pair_doc.document if pair_doc else doc,
                          stored_keywords=(((binding.data or {}).get("plan") or {}).get("note") or {}).get("keywords") if binding else None),
                      "key_expression": view["content"].key_expression if view else "",
                      "needs_source_check": bool(view and view["unverified"]),
                      "needs_check": bool(view and view["uncertain"])})
    def url(**changes):
        return "/notes?" + urlencode({"state": state, "kind": kind, "q": q, "page": page, "day": day, "sort": sort, **changes})
    return templates.TemplateResponse(request=request, name="notes_live.html", context={
        "cards": cards, "counts": counts, "processing": processing, "state": state, "kind": kind, "q": q,
        "kinds": KINDS, "page": page, "has_more": len(rows)>20, "url": url, "day": day, "sort": sort,
    })


@router.post("/notes/sources/{source_id}/analyze")
def analyze_source(source_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    source = db.get(NoteSource, source_id)
    if source is None:
        raise HTTPException(404, "원본을 찾을 수 없습니다.")
    try:
        from backend.app.services.note_pair_queue import retry_source
        retry_source(db, source)
    except NoteProblem as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse("/notes/import", 303)


@router.get("/notes/{note_id:int}")
def note_detail(note_id: int, request: Request, page: int = Query(1, ge=1, le=100000), db: Session = Depends(get_db)):
    token(request)
    note = db.get(EnglishNote, note_id)
    if note is None:
        raise HTTPException(404, "노트를 찾을 수 없습니다.")
    binding = db.query(AutoTopic).filter_by(note_id=note_id, active=True).first()
    managed = db.query(AutoTopic.key).filter_by(note_id=note_id).first() is not None
    conversation = db.get(AutoConversation, binding.conversation_key) if binding else None
    ready = db.query(EnglishNote.id).filter(EnglishNote.id == note_id, note_scope(db)).first() is not None
    current_section = db.get(NoteSection, binding.section_id) if binding and binding.section_id else None
    sections = db.query(NoteSection).filter_by(note_id=note_id).order_by(
        NoteSection.version.desc()).offset((page-1)*20).limit(21).all()
    source_query = db.query(NoteSource.id, NoteSource.collection, NoteSource.question)
    if binding:
        # Current topic membership is authoritative. Historical links can include
        # sources moved to another topic by a later correction/routing decision.
        ids = ((binding.data or {}).get("plan") or {}).get("source_ids") or []
        ids = list(dict.fromkeys(sid for sid in ids if isinstance(sid,int) and not isinstance(sid,bool)))
        visible_ids = ids[-20:]
        rows = source_query.filter(NoteSource.id.in_(visible_ids)).all()
        positions = {sid:i for i,sid in enumerate(visible_ids)}
        sources = sorted(rows,key=lambda row:positions[row.id],reverse=True)
    else:
        sources = source_query.join(NoteSourceLink, NoteSourceLink.source_id == NoteSource.id).filter(
            NoteSourceLink.note_id == note_id).order_by(NoteSource.id.desc()).limit(20).all()
    study = study_view(binding, current_section)
    turns = topic_turns(db,binding) if binding else []
    if not binding:
        legacy_sources=db.query(NoteSource).join(NoteSourceLink,NoteSourceLink.source_id==NoteSource.id).filter(
            NoteSourceLink.note_id==note_id).order_by(NoteSource.created_at,NoteSource.id).all()
        turns=[{'source_id':source.id,'question':source.question,'answer':source.answer} for source in legacy_sources]
    document=article_view(turns,(binding.data or {}).get('document') if binding else None) if turns else None
    pair_doc=db.get(NotePairDocument,note_id)
    if pair_doc:
        from backend.app.services.note_editorial_view import editorial_view
        document=editorial_view(pair_doc.document,[])
        current_section=sections[0] if sections else None
        sources=source_query.join(NoteSourceLink,NoteSourceLink.source_id==NoteSource.id).filter(
            NoteSourceLink.note_id==note_id).order_by(NoteSource.id.desc()).limit(20).all()
    return templates.TemplateResponse(request=request, name="note_live_detail.html", context={
        "note": note, "sections": [current_section] if current_section else sections[:1], "sources": sources,
        "history": [section for section in sections[:20] if not current_section or section.id != current_section.id],
        "ready": ready, "managed": managed, "conversation": conversation,
        "study": study, "reading": reading_view(study), "document":document,
        "kinds": KINDS, "page": page, "has_more": len(sections)>20,
    })


@router.post("/notes/{note_id:int}/studied")
def studied(note_id: int, request: Request, version: int = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    binding = db.query(AutoTopic).filter_by(note_id=note_id, active=True).first()
    managed = db.query(AutoTopic.key).filter_by(note_id=note_id).first()
    if db.query(EnglishNote.id).filter(EnglishNote.id == note_id, note_scope(db)).first() is None:
        raise HTTPException(409, "새 대화를 반영 중입니다. 자동 정리가 끝난 뒤 학습 완료를 눌러 주세요.")
    try:
        study_note(db, note_id, version)
    except NoteProblem as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse(f"/notes/{note_id}?studied=1", 303)


# NOTE_WORD_LINKS_ROUTE_V1
@router.post("/notes/sources/{source_id}/words")
async def connect_source_words(source_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    return analyze_source(source_id, request, csrf, db)


@router.post("/notes/auto/{key}/retry")
def retry_conversation(key: str, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    try:
        request_retry(db, key)
    except NoteProblem as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse("/notes/import", 303)
