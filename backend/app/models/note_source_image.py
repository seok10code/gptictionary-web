from sqlalchemy import Column, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.mysql import MEDIUMBLOB

from backend.app.db.database import Base
from backend.app.models.english_note import NoteSource


class NoteSourceImage(Base):
    __tablename__ = "english_note_source_images"

    source_id = Column(ForeignKey(NoteSource.id, ondelete="CASCADE"), primary_key=True)
    digest = Column(String(64), primary_key=True)
    media_type = Column(String(32), nullable=False)
    content = Column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql", "mariadb"), nullable=False)
