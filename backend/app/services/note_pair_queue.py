"""Database queue mechanics. No AI calls; enqueue shares the raw-source transaction."""
import hashlib,secrets
from datetime import datetime,timedelta
from sqlalchemy import or_,select
from sqlalchemy.orm import aliased
from backend.app.models.note_pair_queue import NotePairJob,NotePairLane
from backend.app.models.english_note import NoteSource

LEASE_SECONDS=300
TERMINAL={'done','ignored','superseded','legacy'}

def lane_key(cid):return hashlib.sha256(cid.encode()).hexdigest()

def enqueue(db,source,channel,meta):
    from backend.app.services.note_auto_ingest import observed_time
    if source.status=='ignored' and not source.extraction:return
    lane=db.get(NotePairLane,lane_key(source.conversation_id))
    if lane is None:
        lane=NotePairLane(key=lane_key(source.conversation_id));db.add(lane);db.flush()
    # Lock the lane for admission too, so concurrent edits cannot both become active.
    db.query(NotePairLane).filter_by(key=lane.key).with_for_update().one()
    now=datetime.utcnow();seen=observed_time(meta.get('captured_at'))
    job=db.query(NotePairJob).filter_by(source_id=source.id).first()
    stable=channel=='file' or meta.get('snapshot_stable') is True
    previous=meta.get('previous_question_id')
    if previous==source.message_id:raise ValueError('앞 질문 ID가 현재 질문과 같습니다.')
    if job:
        if seen>=job.observed_at and (channel=='file' or job.channel!='file'):
            job.observed_at=seen
            if channel=='file':job.channel='file'
            if job.status not in TERMINAL:
                job.previous_question_id=previous
                job.stable=int(stable)
                job.order_known=int(meta.get('order_known') is True)
        return job
    older=db.query(NotePairJob).filter_by(conversation_id=source.conversation_id,question_id=source.message_id).order_by(NotePairJob.observed_at.desc(),NotePairJob.id.desc()).all()
    # A complete file import remains authoritative over later browser snapshots.
    if older and (older[0].observed_at>seen or (older[0].channel=='file' and channel!='file')):
        status='superseded'
    else:
        status='waiting'
        for prior in older:
            if prior.status not in {'legacy','done','ignored','superseded'}:
                prior.status='superseded';prior.error=None
                if prior.lease and lane.lease==prior.lease:
                    lane.lease=None;lane.expires_at=None
                prior.lease=None
    job=NotePairJob(source_id=source.id,conversation_id=source.conversation_id,
        question_id=source.message_id,previous_question_id=previous,channel=channel,
        stable=int(stable),order_known=int(meta.get('order_known') is True),status=status,attempts=0,available_at=now,observed_at=seen,
        result={},created_at=now,updated_at=now)
    db.add(job);db.flush();return job

def prior_job(db,job):
    if not job.previous_question_id:return None
    return db.query(NotePairJob).filter_by(conversation_id=job.conversation_id,
        question_id=job.previous_question_id).filter(NotePairJob.status!='superseded').order_by(NotePairJob.observed_at.desc(),NotePairJob.id.desc()).first()

def claim(factory):
    now=datetime.utcnow()
    with factory() as db:
        # Only look at job metadata here. No full conversation/raw-answer scan.
        prior=aliased(NotePairJob)
        latest_status=select(prior.status).where(
            prior.conversation_id==NotePairJob.conversation_id,
            prior.question_id==NotePairJob.previous_question_id,
            prior.status!='superseded').order_by(prior.observed_at.desc(),prior.id.desc()).limit(1).scalar_subquery()
        candidates=db.query(NotePairJob).filter(
            or_(NotePairJob.status.in_(['waiting','retry']),NotePairJob.status=='running'),
            NotePairJob.available_at<=now,NotePairJob.stable==1,NotePairJob.order_known==1,
            or_(NotePairJob.previous_question_id.is_(None),latest_status.in_(TERMINAL))
        ).order_by(NotePairJob.id).limit(100).all()
        for candidate in candidates:
            lane=db.query(NotePairLane).filter_by(key=lane_key(candidate.conversation_id)).with_for_update().one()
            if lane.lease and lane.expires_at and lane.expires_at>now:continue
            job=db.query(NotePairJob).populate_existing().filter_by(id=candidate.id).with_for_update().one()
            if job.status not in {'waiting','retry','running'}:continue
            if not job.stable or not job.order_known:continue
            if job.attempts>=3:
                finish(db,job,lane,'failed',job.result or {},'처리 시도 한도에 도달했습니다. 수동 재시도가 필요합니다.')
                db.commit();continue
            predecessor=prior_job(db,job)
            if job.previous_question_id and (not predecessor or predecessor.status not in TERMINAL):continue
            token=secrets.token_hex(16)
            acquired=db.query(NotePairLane).filter(NotePairLane.key==lane.key,
                or_(NotePairLane.lease.is_(None),NotePairLane.expires_at<=now)).update(
                    {'lease':token,'expires_at':now+timedelta(seconds=LEASE_SECONDS)},synchronize_session=False)
            if not acquired:continue
            job.status='running';job.lease=token;job.attempts+=1;job.updated_at=now
            db.commit();return job.id,token
        db.rollback()
    return None

def owned(db,job_id,token):
    candidate=db.get(NotePairJob,job_id)
    if candidate is None:raise ValueError('StalePairLease')
    lane=db.query(NotePairLane).filter_by(key=lane_key(candidate.conversation_id)).with_for_update().populate_existing().one()
    job=db.query(NotePairJob).filter_by(id=job_id).with_for_update().populate_existing().one()
    if job.status!='running' or job.lease!=token or lane.lease!=token:
        raise ValueError('StalePairLease')
    return job,lane

def heartbeat(factory,job_id,token):
    with factory() as db:
        job,lane=owned(db,job_id,token)
        job.updated_at=datetime.utcnow();lane.expires_at=job.updated_at+timedelta(seconds=LEASE_SECONDS)
        db.commit()

def finish(db,job,lane,status,result,error=None):
    job.status=status;job.result=result;job.error=error;job.lease=None;job.updated_at=datetime.utcnow()
    lane.lease=None;lane.expires_at=None

def fail(factory,job_id,token,error,*,retry=False):
    with factory() as db:
        try:job,lane=owned(db,job_id,token)
        except ValueError:return
        state='retry' if retry and job.attempts<3 else 'failed'
        finish(db,job,lane,state,job.result or {},str(error)[:3000])
        job.available_at=datetime.utcnow()+timedelta(seconds=15*job.attempts)
        db.commit()

def retry_source(db,source):
    from backend.app.services.note_learning import write_guard,NoteProblem
    write_guard(db)
    job=db.query(NotePairJob).filter_by(source_id=source.id).with_for_update().first()
    if job is None:raise NoteProblem('질문 큐에 등록되지 않은 원본입니다.')
    if job.status=='running':raise NoteProblem('이 질문은 처리 중입니다.')
    if job.status=='superseded':raise NoteProblem('더 최신 답변이 있는 원본입니다.')
    job.status='waiting';job.available_at=datetime.utcnow();job.error=None;job.attempts=0
    db.commit()
