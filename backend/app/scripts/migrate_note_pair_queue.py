"""Add the pair queue tables and baseline existing sources. Never enqueue history by default."""
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

def migrate(engine):
    from sqlalchemy.orm import Session
    from backend.app.models.english_note import NoteSource,NoteSourceLink
    from backend.app.models.note_auto import AutoTurn
    from backend.app.models.note_pair_queue import NotePairLane,NotePairJob,NotePairDocument
    from backend.app.services.note_pair_queue import lane_key
    from backend.app.services.note_learning import write_guard
    with Session(engine) as db:write_guard(db)
    for model in (NotePairLane,NotePairJob,NotePairDocument):model.__table__.create(engine,checkfirst=True)
    count=0
    with Session(engine,autoflush=False) as db:
        last_id=0
        while True:
            batch=db.query(NoteSource).filter(NoteSource.id>last_id).order_by(NoteSource.id).limit(200).all()
            if not batch:break
            for source in batch:
                if db.query(NotePairJob.id).filter_by(source_id=source.id).first():continue
                key=lane_key(source.conversation_id)
                if db.get(NotePairLane,key) is None:db.add(NotePairLane(key=key));db.flush()
                turn=db.query(AutoTurn).filter_by(source_id=source.id,active=True).first()
                links=db.query(NoteSourceLink.note_id).filter_by(source_id=source.id).all()
                note_id=links[0][0] if len(links)==1 else None
                now=datetime.utcnow()
                db.add(NotePairJob(source_id=source.id,conversation_id=source.conversation_id,
                    question_id=source.message_id,previous_question_id=turn.previous_question_id if turn else None,
                    channel=turn.channel if turn else 'browser',stable=int(turn.stable) if turn else 1,
                    order_known=int(turn.order_known) if turn else 0,
                    status='legacy',attempts=0,available_at=now,created_at=now,updated_at=now,
                    observed_at=turn.observed_at if turn else source.created_at,note_id=note_id,
                    result={'migration':'existing_source_not_reprocessed'}));db.flush();count+=1
            last_id=batch[-1].id
        db.commit()
    return count

def main():
    load_dotenv(Path(__file__).resolve().parents[3]/'.env')
    from backend.app.db.database import engine
    engine.echo=False;engine.hide_parameters=True
    print('기존 원문 기준선 등록:',migrate(engine))
    print('새 테이블 3개 준비. 기존 원문·노트·학습기록·단어장 변경·삭제·과거 AI 재처리 없음.')

if __name__=='__main__':main()
