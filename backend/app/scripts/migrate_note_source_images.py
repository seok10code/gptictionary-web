from backend.app.api.routes.collector import require_allowed_database
from backend.app.db.database import engine, get_db
from backend.app.models.note_source_image import NoteSourceImage


def main():
    sessions = get_db()
    try:
        db = next(sessions)
        require_allowed_database(db)
        NoteSourceImage.__table__.create(bind=engine, checkfirst=True)
    finally:
        sessions.close()


if __name__ == "__main__":
    main()
