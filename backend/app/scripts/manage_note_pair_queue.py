"""Inspect or explicitly retry pair jobs. Never calls an AI API itself."""
import argparse,json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

def status(engine):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from backend.app.models.note_pair_queue import NotePairJob,NotePairDocument
    from backend.app.models.english_note import NoteSource,EnglishNote
    def select_only(conn,cursor,statement,params,context,many):
        if not statement.lstrip().upper().startswith('SELECT '):raise ValueError('진단 쓰기 차단')
    with engine.connect() as conn:
        if engine.dialect.name in {'mysql','mariadb'}:conn.exec_driver_sql('START TRANSACTION READ ONLY')
        event.listen(conn,'before_cursor_execute',select_only)
        try:
            with Session(bind=conn,autoflush=False) as db:
                rows=db.query(NotePairJob).filter(NotePairJob.status!='legacy').order_by(NotePairJob.id.desc()).limit(20).all()
                result=[]
                for job in rows:
                    source=db.get(NoteSource,job.source_id);note=db.get(EnglishNote,job.note_id) if job.note_id else None
                    result.append({'job_id':job.id,'question':source.question[:180],'status':job.status,
                        'attempts':job.attempts,'stable':bool(job.stable),'order_known':bool(job.order_known),'note_title':note.title if note else None,'note_id':job.note_id,
                        'route':(job.result or {}).get('route'),'error':job.error,'updated_at_utc':str(job.updated_at)})
                print(json.dumps({'jobs':result,'api_calls':0,'db_writes':False},ensure_ascii=False,indent=2))
        finally:event.remove(conn,'before_cursor_execute',select_only);conn.rollback()

def schedule_conversation(engine,cid):
    from sqlalchemy.orm import Session
    from backend.app.services.note_learning import write_guard
    from backend.app.models.note_auto import AutoTurn,AutoConversation
    from backend.app.models.note_pair_queue import NotePairJob
    with Session(engine) as db:
        write_guard(db)
        keys=[c.key for c in db.query(AutoConversation).filter_by(conversation_id=cid)]
        turns=db.query(AutoTurn).filter(AutoTurn.conversation_key.in_(keys),AutoTurn.active.is_(True)).all() if keys else []
        selected={t.source_id:t for t in turns}
        jobs=db.query(NotePairJob).filter_by(conversation_id=cid).order_by(NotePairJob.id).all()
        count=0
        for job in jobs:
            if job.source_id not in selected:continue
            if job.status not in {'legacy','failed'}:continue
            turn=selected[job.source_id];job.previous_question_id=turn.previous_question_id;job.stable=int(turn.stable);job.order_known=int(turn.order_known)
            job.status='waiting';job.available_at=datetime.utcnow();job.error=None;job.attempts=0;count+=1
        db.commit()
    print('명시한 기존 대화의 질문 작업 등록:',count)
    print('이 명령의 AI 호출 없음. 실행 중인 서버 작업자가 순서대로 처리하며 정상 AI 호출이 발생합니다.')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--status',action='store_true');group.add_argument('--retry',type=int)
    group.add_argument('--enqueue-conversation')
    args=p.parse_args(argv)
    load_dotenv(Path(__file__).resolve().parents[3]/'.env')
    from backend.app.db.database import engine
    engine.echo=False;engine.hide_parameters=True
    if args.status:status(engine)
    elif args.enqueue_conversation:schedule_conversation(engine,args.enqueue_conversation)
    else:
        from sqlalchemy.orm import Session
        from backend.app.models.note_pair_queue import NotePairJob
        from backend.app.models.english_note import NoteSource
        from backend.app.services.note_pair_queue import retry_source
        with Session(engine) as db:
            job=db.get(NotePairJob,args.retry)
            if not job:raise ValueError('작업을 찾을 수 없습니다.')
            if job.status!='failed':raise ValueError('실패한 작업만 재시도할 수 있습니다.')
            retry_source(db,db.get(NoteSource,job.source_id))
        print('질문 작업 재시도 예약:',args.retry)

if __name__=='__main__':main()
