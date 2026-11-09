from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=ROOT / ".env")

from backend.app.db.database import Base, engine
from backend.app.models.english_note import (
    EnglishNote, NoteSource, NoteSection,
    NoteSourceLink,
)


def main():
    engine.echo = False

    with engine.connect() as connection:
        actual_database = connection.execute(
            text("SELECT DATABASE()")
        ).scalar()

    if actual_database != "dbo_dev":
        raise SystemExit(
            f"중단: 개발 DB dbo_dev가 아닙니다. 현재 DB: {actual_database}"
        )

    models = [
        NoteSource, EnglishNote, NoteSection,
        NoteSourceLink,
    ]
    tables = [model.__table__ for model in models]
    existing = set(inspect(engine).get_table_names())

    # 지정한 네 테이블만 생성합니다.
    # 이미 존재하는 테이블의 구조를 변경하지 않습니다.
    Base.metadata.create_all(
        bind=engine,
        tables=tables,
        checkfirst=True,
    )

    confirmed = set(inspect(engine).get_table_names())

    for table in tables:
        if table.name not in confirmed:
            raise RuntimeError(f"테이블 생성 확인 실패: {table.name}")
        status = "기존 유지" if table.name in existing else "신규 생성"
        print(f"{status}: {table.name}")

    print("완료: dbo_dev의 영어 노트 테이블 준비 완료")


if __name__ == "__main__":
    main()
