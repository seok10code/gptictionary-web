"""Enrich one already-reviewed note at a time without changing its sources/versions.

Uses the existing conversation lease. New collection always takes precedence;
an unchanged failed input is not retried automatically by this document editor.
"""
import asyncio
import secrets
import logging
from datetime import datetime
from backend.app.models.note_auto import AutoTopic,AutoConversation
from backend.app.models.english_note import NoteSection
from backend.app.services.note_document import topic_turns,fingerprint,generate_document,compile_document
from backend.app.services.note_textbook import recover_duplicate_table_failure


async def document_once(factory):
    selected=None
    with factory() as db:
        from backend.app.services.note_learning import write_guard
        write_guard(db)
        rows=db.query(AutoTopic,AutoConversation).join(AutoConversation,
            AutoConversation.key==AutoTopic.conversation_key).filter(AutoTopic.active.is_(True),
            AutoTopic.note_id.isnot(None),AutoTopic.revision==AutoConversation.revision,
            AutoConversation.processed_revision==AutoConversation.revision,
            AutoConversation.status.in_(['idle','review_needed']),AutoConversation.lease.is_(None)
        ).order_by(AutoTopic.updated_at.desc(),AutoTopic.key).all()
        for topic,conv in rows:
            turns=topic_turns(db,topic)
            if not turns:continue
            stamp=fingerprint(turns);data=topic.data or {}
            current=data.get('document') or {};attempt=data.get('document_attempt') or {}
            if current.get('fingerprint')==stamp and current.get('format')=='textbook':continue
            recovered=recover_duplicate_table_failure(turns,attempt)
            if recovered is None:
                if current.get('fingerprint')==stamp:continue
                if attempt.get('fingerprint')==stamp:continue
            lease='doc-'+secrets.token_hex(16)
            claimed=db.query(AutoConversation).filter_by(key=conv.key,revision=conv.revision,
                processed_revision=conv.revision,status=conv.status,lease=None).update(
                {'lease':lease,'leased_at':datetime.utcnow()},synchronize_session=False)
            if not claimed:continue
            section=db.get(NoteSection,topic.section_id) if topic.section_id else None
            selected=(topic.key,conv.key,conv.revision,lease,turns,stamp,
                      section.content_hash if section else '',recovered,attempt if recovered else None)
            db.commit();break
    if selected is None:return False
    topic_key,key,revision,lease,turns,stamp,section_hash,recovered,original_attempt=selected
    error=None;failure_details=None
    try:
        try:document=recovered if recovered is not None else await asyncio.to_thread(generate_document,turns)
        except Exception as exc:
            # Keep all original content visible if API output is unavailable.
            error=type(exc).__name__;document=compile_document(turns)
            failure_details={'errors':str(exc).splitlines() if error=='DocumentProblem' else [],
                'attempts':getattr(exc,'attempts',[])}
            logging.getLogger(__name__).warning('English note textbook generation failed: topic=%s error=%s details=%s',
                topic_key,error,' / '.join(failure_details['errors'])[:2000])
        with factory() as db:
            conv=db.query(AutoConversation).filter_by(key=key).with_for_update().first()
            topic=db.get(AutoTopic,topic_key)
            if (not conv or conv.lease!=lease or conv.revision!=revision or not topic or not topic.active
                    or topic.revision!=revision or fingerprint(topic_turns(db,topic))!=stamp):return True
            previous=(topic.data or {}).get('document') or {}
            # A failed re-edit must not replace an existing textbook for unchanged sources.
            if (error and previous.get('format')=='textbook' and previous.get('version') in {2,3}
                    and previous.get('fingerprint')==fingerprint(turns,version=previous['version'])):
                document=previous
            else:document['section_hash']=section_hash
            topic.data={**(topic.data or {}),'document':document,
                        'document_attempt':{'fingerprint':stamp,'error_type':error,
                            'failure_details':failure_details,
                            **({'recovery':{'kind':'duplicate_table_items','original_attempt':original_attempt}} if recovered is not None else {})}}
            db.commit()
    finally:
        with factory() as db:
            conv=db.query(AutoConversation).filter_by(key=key).with_for_update().first()
            if conv and conv.lease==lease:
                conv.lease=None;conv.leased_at=None;db.commit()
    return True
