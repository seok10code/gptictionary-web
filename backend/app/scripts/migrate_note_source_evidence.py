from uuid import uuid4

from sqlalchemy import text

from backend.app.db.database import Base, engine, SessionLocal
from backend.app.models.note_source_evidence import NoteSourceEvidence
from backend.app.services.note_source_store import save_source


def source_count():
    with engine.connect() as connection:
        return connection.execute(text(
            "SELECT COUNT(*) FROM english_note_sources"
        )).scalar()


def verify_store():
    # 시험 데이터는 마지막에 rollback하여 남기지 않습니다.
    with SessionLocal() as db:
        try:
            data = {
                "conversation_id": "store-test-" + str(uuid4()),
                "message_id": "question-test",
                "question": "밥 양 줄여달라고 어떻게 말해?",
                "answer": "Could I have less rice, please?",
                "collection": "공통 저장기 시험",
                "answer_ids": ["answer-test"],
            }

            try:
                save_source(
                    db,
                    channel="browser",
                    source_conversation_id="wrong-conversation",
                    identity_checked=True,
                    **data,
                )
            except ValueError:
                pass
            else:
                raise AssertionError("잘못된 대화 ID가 허용됐습니다.")

            browser = save_source(
                db,
                channel="browser",
                source_conversation_id=data["conversation_id"],
                identity_checked=True,
                **data,
            )
            assert browser["source"].status == "draft"

            exported = save_source(db, channel="file", **data)
            assert exported["source"].id == browser["source"].id
            assert exported["created"] is False
            assert exported["promoted"] is True
            assert exported["source"].status == "pending"

            repeated = save_source(
                db,
                channel="browser",
                source_conversation_id=data["conversation_id"],
                identity_checked=True,
                **data,
            )
            assert repeated["source"].status == "pending"

            revised = save_source(
                db,
                channel="file",
                **{
                    **data,
                    "answer": "Could you use less rice, please?",
                },
            )
            assert revised["source"].id != exported["source"].id
            assert (
                revised["evidence"].question_key
                == exported["evidence"].question_key
            )

            count = db.query(NoteSourceEvidence).filter_by(
                question_key=exported["evidence"].question_key
            ).count()
            assert count == 3

        finally:
            db.rollback()


def main():
    engine.echo = False

    with engine.connect() as connection:
        database = connection.execute(
            text("SELECT DATABASE()")
        ).scalar()

    if database != "dbo_dev":
        raise SystemExit(f"중단: dbo_dev가 아닙니다. 현재 DB: {database}")

    before = source_count()

    Base.metadata.create_all(
        bind=engine,
        tables=[NoteSourceEvidence.__table__],
        checkfirst=True,
    )
    print("출처 테이블 준비 완료")

    verify_store()
    print("검증 완료: 출처 병합·내용 버전·대화 ID 차단")

    after = source_count()
    if before != after:
        raise RuntimeError("원본 기록 수가 달라졌습니다.")

    print(f"기존 원본 수 유지: {before} → {after}")
    print("공통 저장기 준비 완료")


if __name__ == "__main__":
    main()
