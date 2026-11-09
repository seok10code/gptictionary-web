"""Queue changes in the same transaction that saves the raw source."""
import hashlib
from datetime import datetime, timedelta, timezone
from backend.app.models.note_auto import AutoConversation, AutoTurn

STATUSES = {"waiting": "자동 분석 대기", "running": "대화 분석·저장 중", "idle": "자동 정리 완료",
            "retry": "자동 재시도 대기", "error": "처리 실패", "needs_order": "대화 순서 확인 대기",
            "needs_stable": "안정된 답변 수집 대기", "review_needed": "일부 완료 · 검토 대기"}


def conversation_key(cid):
    return hashlib.sha256(cid.encode()).hexdigest()


def observed_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value is None:
        return datetime.utcnow()
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value > datetime.utcnow() + timedelta(minutes=5):
        raise ValueError("수집 시간과 서버 시간 차이가 너무 큽니다.")
    return value


def dirty(conv):
    conv.revision += 1
    conv.available_at = datetime.utcnow() + timedelta(seconds=45)
    conv.updated_at = datetime.utcnow()
    conv.attempts, conv.error = 0, None
    if not conv.lease:
        conv.status = "waiting"


def register_source(db, source, channel, meta=None):
    # Manually excluded connection-test records are never promoted to learning data.
    if source.status == "ignored" and not source.extraction:
        return
    meta = meta or {}
    key = conversation_key(source.conversation_id)
    conv = db.query(AutoConversation).filter_by(key=key).with_for_update().first()
    if conv is None:
        conv = AutoConversation(key=key, conversation_id=source.conversation_id,
                                title=source.collection, revision=0)
        db.add(conv); db.flush()
    now = observed_time(meta.get("captured_at"))
    turn = db.query(AutoTurn).filter_by(conversation_key=key, question_id=source.message_id).first()
    known = bool(meta.get("order_known"))
    stable = channel == "file" or bool(meta.get("snapshot_stable"))
    previous = meta.get("previous_question_id")
    if previous == source.message_id or (previous is not None and (not isinstance(previous, str) or len(previous) > 255)):
        raise ValueError("앞 질문 ID가 올바르지 않습니다.")
    if turn is None:
        turn = AutoTurn(conversation_key=key, question_id=source.message_id, source_id=source.id,
                        previous_question_id=previous, order_known=known, stable=stable,
                        channel=channel, observed_at=now, active=True)
        db.add(turn); dirty(conv)
    else:
        # An export is authoritative for its selected branch. Browser observations
        # add new questions but never replace an exported answer with a partial one.
        can_replace = channel == "file" or (turn.channel != "file" and now >= turn.observed_at)
        changed = False
        if can_replace:
            if turn.source_id != source.id or not turn.active:
                turn.source_id, turn.active = source.id, True
                changed = True
            if channel == "file" or known:
                # A window starting in the middle cannot erase a previously seen predecessor.
                if previous is not None or not turn.order_known or channel == "file":
                    if turn.previous_question_id != previous:
                        turn.previous_question_id = previous; changed = True
                if not turn.order_known:
                    turn.order_known = known; changed = True
            if turn.stable != stable or turn.channel != channel:
                turn.stable, turn.channel = stable, channel; changed = True
            turn.observed_at = now
        if changed:
            dirty(conv)
    conv.title = source.collection
    db.flush()


def finish_file_branch(db, cid, question_ids):
    key = conversation_key(cid)
    conv = db.query(AutoConversation).filter_by(key=key).with_for_update().first()
    if not conv:
        return
    current = set(question_ids)
    for turn in db.query(AutoTurn).filter_by(conversation_key=key, active=True):
        if turn.channel == "file" and turn.question_id not in current:
            turn.active = False
            dirty(conv)
    db.flush()


def source_view(db, source):
    from backend.app.models.note_pair_queue import NotePairJob
    job=db.query(NotePairJob).filter_by(source_id=source.id).first()
    if job and job.status!='legacy':
        names={'waiting':'질문 처리 대기','running':'질문 정리 중','retry':'질문 재시도 대기',
               'done':'질문 정리 완료','failed':'질문 정리 실패','ignored':'영어 학습 대상 아님',
               'superseded':'새 답변으로 대체됨'}
        return {'conversation':None,'status':names.get(job.status,job.status)+((' · '+job.error) if job.error else '')}
    conv = db.get(AutoConversation, conversation_key(source.conversation_id))
    status=STATUSES.get(conv.status,conv.status) if conv else '자동 처리 대상 확인 중'
    report=(source.extraction or {}).get('question_review')
    if report and conv and report.get('revision')==conv.revision:
        status=('이 질문 검토 대기: '+report.get('reason','')) if report['state']=='pending' else '이 질문 자동 정리 완료'
    return {'conversation':conv,'status':status}


def request_retry(db, key):
    from backend.app.services.note_learning import NoteProblem, write_guard
    write_guard(db)
    conv = db.query(AutoConversation).filter_by(key=key).with_for_update().first()
    if conv is None:
        raise NoteProblem("자동 처리에 등록되지 않은 원본입니다. 확장프로그램 재수집 또는 파일 재업로드를 해주세요.")
    if not conv.lease:
        conv.status, conv.available_at, conv.attempts, conv.error = "waiting", datetime.utcnow(), 0, None
    db.commit()
