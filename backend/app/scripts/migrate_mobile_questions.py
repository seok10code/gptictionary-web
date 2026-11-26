from backend.app.api.routes.collector import require_allowed_database
from backend.app.db.database import SessionLocal
from backend.app.models.mobile_question import MobileQuestion


def main():
    with SessionLocal() as db:
        require_allowed_database(db)
        MobileQuestion.__table__.create(bind=db.get_bind(), checkfirst=True)
    print("아이폰 질문함 테이블 준비 완료")


if __name__ == "__main__":
    main()
