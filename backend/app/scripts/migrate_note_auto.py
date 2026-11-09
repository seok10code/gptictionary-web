"""Creates the automatic-note tables and registers existing verified raw sources."""
from pathlib import Path
from dotenv import load_dotenv


def main():
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    from sqlalchemy.orm import sessionmaker
    from backend.app.db.database import engine
    from backend.app.models.english_note import NoteSource
    from backend.app.models.note_source_evidence import NoteSourceEvidence
    from backend.app.models.note_auto import AutoConversation, AutoTurn, AutoTopic
    from backend.app.services.note_auto_ingest import register_source, conversation_key
    from backend.app.services.note_learning import write_guard
    engine.echo, engine.hide_parameters = False, True
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        write_guard(db)
    for model in [AutoConversation, AutoTurn, AutoTopic]:
        model.__table__.create(engine, checkfirst=True)
        print("준비 완료:", model.__tablename__)
    with factory() as db:
        rows = db.query(NoteSource, NoteSourceEvidence.channel).join(
            NoteSourceEvidence, NoteSourceEvidence.source_id == NoteSource.id).filter(
            ((NoteSourceEvidence.channel == "file") & (NoteSourceEvidence.identity_state == "from_file")) |
            ((NoteSourceEvidence.channel == "browser") & (NoteSourceEvidence.identity_state == "matched"))
        ).order_by(NoteSource.id).all()
        grouped = {}
        for source, channel in rows:
            key = (source.conversation_id, source.message_id)
            old = grouped.get(key)
            if old is None or channel == "file" or old[1] != "file":
                grouped[key] = (source, channel)
        count = 0
        for source, channel in grouped.values():
            if db.query(AutoTurn.id).filter_by(conversation_key=conversation_key(source.conversation_id), question_id=source.message_id).first():
                continue
            register_source(db, source, channel, {"order_known": False, "snapshot_stable": bool(source.notes_applied)})
            if db.query(AutoTurn.id).filter_by(conversation_key=conversation_key(source.conversation_id), question_id=source.message_id).first():
                count += 1
        db.commit()
    print("기존 원본 등록:", count)
    print("기존 본문 유지. 여러 질문의 순서는 확장프로그램 재수집 또는 파일 재업로드로 확인합니다.")


if __name__ == "__main__":
    main()
