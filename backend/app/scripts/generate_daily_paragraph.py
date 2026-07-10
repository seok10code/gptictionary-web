from backend.app.db.database import SessionLocal
from backend.app.services.daily_paragraph_service import (
    get_or_create_today_paragraph,
)


def main():
    db = SessionLocal()

    try:
        paragraph = get_or_create_today_paragraph(db)

        if paragraph:
            print(
                "DAILY PARAGRAPH READY:",
                paragraph.date,
                paragraph.title,
            )
        else:
            print("DAILY PARAGRAPH CREATION FAILED")

    except Exception as e:
        db.rollback()
        print("DAILY PARAGRAPH SCRIPT ERROR:", repr(e))
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()