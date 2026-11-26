import hmac
import hashlib
import logging
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from sqlalchemy import bindparam, inspect, or_, text

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from backend.app.db.database import get_db
from backend.app.models.note_source_image import NoteSourceImage
from backend.app.models.mobile_question import MobileQuestion
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


def local_datetime_label(value):
    from zoneinfo import ZoneInfo
    if value is None:
        return ""
    # Database note timestamps are stored as naive UTC datetimes.
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M")


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


def editable_document_text(document):
    """Plain-text editing view; headings stay editable and tables remain readable."""
    lines=[]
    for section in document.get("sections",[]):
        heading=str(section.get("heading","")).strip()
        if heading:
            lines.extend(["## "+heading,""])
        for block in section.get("blocks",[]):
            kind=block.get("kind")
            if kind=="list":
                lines.extend("- "+str(item) for item in block.get("items",[]))
            elif kind in {"table","examples","source_examples"}:
                headers=block.get("headers",[])
                if headers: lines.append(" | ".join(str(cell) for cell in headers))
                lines.extend(" | ".join(str(cell) for cell in row) for row in block.get("rows",[]))
            elif kind=="dialogue":
                lines.extend(" | ".join(str(cell) for cell in row) for row in block.get("rows",[]))
            elif "text" in block:
                lines.append(str(block["text"]))
            lines.append("")
    return "\n".join(lines).strip()


def editable_document(title, body, source_ids):
    sections=[]
    heading="노트 내용"
    paragraphs=[]
    def flush():
        nonlocal paragraphs
        text="\n".join(paragraphs).strip()
        if text:
            sections.append({"key":f"manual-{len(sections)+1}","heading":heading,
                "source_ids":source_ids,"blocks":[{"kind":"paragraph","text":text,"evidence_ids":[]}]})
        paragraphs=[]
    for line in body.splitlines():
        if line.startswith("## "):
            flush(); heading=line[3:].strip()[:255] or "노트 내용"
        else:
            paragraphs.append(line)
    flush()
    if not sections:
        raise HTTPException(400,"노트 내용은 비워둘 수 없습니다.")
    return {"format":"pair_textbook","version":1,"title":title,"summary":"","sections":sections,
            "semantic_verification":"manually_edited"}


def visible_note_or_404(db,note_id):
    note=db.get(EnglishNote,note_id)
    if note is None or db.query(EnglishNote.id).filter(EnglishNote.id==note_id,note_scope(db)).first() is None:
        raise HTTPException(404,"노트를 찾을 수 없습니다.")
    return note


@router.get("/notes")
def notes_page(request: Request, state: str = "all", kind: str = "",
               q: str = Query("", max_length=200), page: int = Query(1, ge=1, le=100000),
               day: str = Query("", max_length=10), sort: str = "newest",
               db: Session = Depends(get_db)):
    csrf=token(request)
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
                      "updated_label": local_datetime_label(note.updated_at),
                      "tags": note_tags(note.title, note.subject, note.keywords,
                          document=pair_doc.document if pair_doc else doc,
                          stored_keywords=(((binding.data or {}).get("plan") or {}).get("note") or {}).get("keywords") if binding else None),
                      "key_expression": view["content"].key_expression if view else "",
                      "needs_source_check": bool(view and view["unverified"]),
                      "needs_check": bool(view and view["uncertain"])})
    def url(**changes):
        return "/notes?" + urlencode({"state": state, "kind": kind, "q": q, "page": page, "day": day, "sort": sort, **changes})
    return templates.TemplateResponse(request=request, name="notes_live.html", context={
        "cards": cards, "counts": counts, "processing": processing, "csrf": csrf, "state": state, "kind": kind, "q": q,
        "kinds": KINDS, "page": page, "has_more": len(rows)>20, "url": url, "day": day, "sort": sort,
    })


@router.get("/notes/calendar-days")
def notes_calendar_days(year: int = Query(..., ge=2000, le=2100),
                        month: int = Query(..., ge=1, le=12),
                        db: Session = Depends(get_db)):
    """Return note-update counts by Seoul calendar day for the date picker."""
    from zoneinfo import ZoneInfo
    first = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    start = local_day_utc_range(first.isoformat())[0]
    end = local_day_utc_range(next_month.isoformat())[0]
    timestamps = db.query(EnglishNote.updated_at).filter(
        note_scope(db), EnglishNote.updated_at >= start, EnglishNote.updated_at < end
    ).all()
    counts = {}
    seoul = ZoneInfo("Asia/Seoul")
    for (value,) in timestamps:
        local_date = value.replace(tzinfo=timezone.utc).astimezone(seoul).date().isoformat()
        counts[local_date] = counts.get(local_date, 0) + 1
    return JSONResponse({"year": year, "month": month, "days": counts})


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
    answer_images = []
    if sources:
        try:
            answer_images = db.query(NoteSourceImage.source_id, NoteSourceImage.digest).filter(
                NoteSourceImage.source_id.in_([source.id for source in sources]),
            ).order_by(NoteSourceImage.source_id, NoteSourceImage.digest).all()
        except ProgrammingError as error:
            if not error.orig.args or error.orig.args[0] != 1146:
                raise
            logging.getLogger(__name__).warning("Run migrate_note_source_images to enable note images")
    return templates.TemplateResponse(request=request, name="note_live_detail.html", context={
        "answer_images": answer_images,
        "note": note, "sections": [current_section] if current_section else sections[:1], "sources": sources,
        "updated_label": local_datetime_label(note.updated_at),
        "history": [section for section in sections[:20] if not current_section or section.id != current_section.id],
        "ready": ready, "managed": managed, "conversation": conversation,
        "study": study, "reading": reading_view(study), "document":document,
        "kinds": KINDS, "page": page, "has_more": len(sections)>20,
    })


@router.get("/notes/{note_id:int}/edit")
def edit_note_page(note_id:int,request:Request,db:Session=Depends(get_db)):
    csrf=token(request)
    note=visible_note_or_404(db,note_id)
    pair_doc=db.get(NotePairDocument,note_id)
    body=editable_document_text(pair_doc.document or {}) if pair_doc else ""
    return templates.TemplateResponse(request=request,name="note_edit.html",context={
        "note":note,"csrf":csrf,"body":body,"kinds":KINDS,"has_body":bool(pair_doc),
    })


@router.post("/notes/{note_id:int}/edit")
def edit_note(note_id:int,request:Request,csrf:str=Form(...),title:str=Form(...),kind:str=Form(...),
              subject:str=Form(""),keywords:str=Form(""),body:str=Form(""),db:Session=Depends(get_db)):
    check_csrf(request,csrf)
    note=visible_note_or_404(db,note_id)
    from backend.app.services.note_learning import write_guard
    try:
        write_guard(db)
        title=title.strip();subject=subject.strip();keywords=keywords.strip()
        if not title or len(title)>255 or len(subject)>100 or len(keywords)>2000:
            raise HTTPException(400,"제목·주제·검색어의 길이를 확인해 주세요.")
        if kind not in KINDS:
            raise HTTPException(400,"노트 종류를 확인해 주세요.")
        pair_doc=db.get(NotePairDocument,note_id)
        note.title=title;note.kind=kind;note.subject=subject;note.keywords=keywords
        note.version+=1;note.updated_at=datetime.utcnow()
        if pair_doc:
            if not body.strip() or len(body)>40000:
                raise HTTPException(400,"본문은 비워둘 수 없고 40,000자 이하여야 합니다.")
            source_ids=[]
            try:
                source_ids=list(dict.fromkeys(int(sid) for section in (pair_doc.document or {}).get("sections",[])
                    for sid in section.get("source_ids",[]) if isinstance(sid,int) and not isinstance(sid,bool)))
            except (TypeError,ValueError):
                source_ids=[]
            pair_doc.document=editable_document(title,body,source_ids)
            pair_doc.revision+=1;pair_doc.updated_at=datetime.utcnow()
            latest=db.query(NoteSection).filter_by(note_id=note_id).order_by(NoteSection.version.desc()).first()
            if latest:
                version=max(note.version,latest.version+1)
                digest=hashlib.sha256((str(note.id)+":"+str(version)+":"+body.strip()).encode("utf-8")).hexdigest()
                db.add(NoteSection(note_id=note_id,source_id=latest.source_id,version=version,
                    content_hash=digest,heading=title,body=body.strip(),recall_question=latest.recall_question))
                note.version=version
        db.commit()
    except HTTPException:
        db.rollback();raise
    except NoteProblem as exc:
        db.rollback();raise HTTPException(409,str(exc)) from None
    except Exception:
        db.rollback();raise
    return RedirectResponse(f"/notes/{note_id}",303)


def delete_note_quiz_rows(db, note_ids):
    connection = db.connection()
    schema = inspect(connection)
    if not schema.has_table("english_note_quizzes"):
        return

    for table in ("english_note_quiz_tickets", "english_note_quiz_attempts"):
        if schema.has_table(table):
            connection.execute(text(f"""
                DELETE FROM {table}
                WHERE quiz_id IN (
                    SELECT id FROM english_note_quizzes
                    WHERE section_id IN (
                        SELECT id FROM english_note_sections WHERE note_id IN :note_ids
                    )
                )
            """).bindparams(bindparam("note_ids", expanding=True)), {"note_ids": note_ids})
    connection.execute(text("""
        DELETE FROM english_note_quizzes
        WHERE section_id IN (
            SELECT id FROM english_note_sections WHERE note_id IN :note_ids
        )
    """).bindparams(bindparam("note_ids", expanding=True)), {"note_ids": note_ids})


@router.post("/notes/delete-all")
def delete_all_notes(request:Request,csrf:str=Form(...),db:Session=Depends(get_db)):
    check_csrf(request,csrf)
    from backend.app.services.note_learning import write_guard
    try:
        write_guard(db)
        note_ids=[row[0] for row in db.query(EnglishNote.id).all()]
        if not note_ids:
            return RedirectResponse("/notes",303)
        active_job=db.query(NotePairJob.id).filter(NotePairJob.note_id.in_(note_ids),
            NotePairJob.status.in_(["waiting","running","retry"])).first()
        if active_job:
            raise HTTPException(409,"노트에 연결된 수집 작업이 진행 중입니다. 작업이 끝난 뒤 전체 삭제해 주세요.")
        # Keep original conversations and queue history; remove note-owned records.
        db.query(NotePairJob).filter(NotePairJob.note_id.in_(note_ids)).update(
            {NotePairJob.note_id:None},synchronize_session=False)
        db.query(AutoTopic).filter(AutoTopic.note_id.in_(note_ids)).update(
            {AutoTopic.note_id:None,AutoTopic.section_id:None,AutoTopic.active:False},
            synchronize_session=False)
        db.query(NotePairDocument).filter(NotePairDocument.note_id.in_(note_ids)).delete(
            synchronize_session=False)
        db.query(NoteSourceLink).filter(NoteSourceLink.note_id.in_(note_ids)).delete(
            synchronize_session=False)
        delete_note_quiz_rows(db, note_ids)
        db.query(NoteSection).filter(NoteSection.note_id.in_(note_ids)).delete(
            synchronize_session=False)
        db.query(EnglishNote).filter(EnglishNote.id.in_(note_ids)).delete(
            synchronize_session=False)
        db.commit()
    except HTTPException:
        db.rollback();raise
    except NoteProblem as exc:
        db.rollback();raise HTTPException(409,str(exc)) from None
    except Exception:
        db.rollback();raise
    return RedirectResponse("/notes",303)


@router.post("/notes/{note_id:int}/delete")
def delete_note(note_id:int,request:Request,csrf:str=Form(...),db:Session=Depends(get_db)):
    check_csrf(request,csrf)
    note=visible_note_or_404(db,note_id)
    from backend.app.services.note_learning import write_guard
    try:
        write_guard(db)
        active_job=db.query(NotePairJob.id).filter(NotePairJob.note_id==note_id,
            NotePairJob.status.in_(["waiting","running","retry"])).first()
        if active_job:
            raise HTTPException(409,"이 노트에 연결된 수집 작업이 진행 중입니다. 작업이 끝난 뒤 삭제해 주세요.")
        # Preserve source conversations and queue history; remove only note-owned rows.
        db.query(NotePairJob).filter(NotePairJob.note_id==note_id).update({NotePairJob.note_id:None},synchronize_session=False)
        db.query(AutoTopic).filter(AutoTopic.note_id==note_id).update(
            {AutoTopic.note_id:None,AutoTopic.section_id:None,AutoTopic.active:False},synchronize_session=False)
        db.query(NotePairDocument).filter_by(note_id=note_id).delete(synchronize_session=False)
        db.query(NoteSourceLink).filter_by(note_id=note_id).delete(synchronize_session=False)
        delete_note_quiz_rows(db, [note_id])
        db.query(NoteSection).filter_by(note_id=note_id).delete(synchronize_session=False)
        db.delete(note);db.commit()
    except HTTPException:
        db.rollback();raise
    except NoteProblem as exc:
        db.rollback();raise HTTPException(409,str(exc)) from None
    except Exception:
        db.rollback();raise
    return RedirectResponse("/notes",303)


@router.get("/notes/answer-images/{source_id:int}/{digest}")
def answer_image(source_id: int, digest: str, db: Session = Depends(get_db)):
    image = db.get(NoteSourceImage, (source_id, digest))
    if image is None:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return Response(
        image.content, media_type=image.media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        },
    )


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


@router.get("/notes/mobile-questions")
def mobile_questions(
    request: Request,
    before: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    query = db.query(MobileQuestion)
    if before is not None:
        query = query.filter(MobileQuestion.id < before)
    try:
        rows = query.order_by(MobileQuestion.id.desc()).limit(51).all()
    except ProgrammingError as error:
        if not error.orig.args or error.orig.args[0] != 1146:
            raise
        raise HTTPException(503, "아이폰 질문함 테이블을 먼저 준비해 주세요.") from None
    return templates.TemplateResponse(
        request=request, name="note_mobile_questions.html",
        context={"questions": rows[:50], "next_before": rows[49].id if len(rows) > 50 else None},
    )
