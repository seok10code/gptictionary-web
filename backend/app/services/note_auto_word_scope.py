"""Hide only unused, provenance-confirmed automatic additions rejected by current routing."""
from datetime import datetime
from backend.app.models.note_auto_word_scope import AutoWordScope
from backend.app.models.note_auto import AutoTopic,AutoConversation
from backend.app.models.english_note import NoteSource


def visible_words(query,db):
    from sqlalchemy import and_,or_,func
    from backend.app.models.word import Word
    from backend.app.models.word_sense import WordSense
    from backend.app.models.quiz_log import QuizLog
    fields=('priority','memorize_count','total_correct','total_wrong')
    unused=and_(*(func.coalesce(getattr(Word,field),0)==0 for field in fields))
    used_sense=db.query(WordSense.id).filter(WordSense.word_id==Word.id,
        or_(*(func.coalesce(getattr(WordSense,field),0)!=0 for field in fields))).correlate(Word).exists()
    used_quiz=db.query(QuizLog.id).filter(QuizLog.word_id==Word.id).correlate(Word).exists()
    excluded=db.query(AutoWordScope.word_id).filter(AutoWordScope.word_id==Word.id,
        AutoWordScope.excluded.is_(True)).correlate(Word).exists()
    return query.filter(~and_(excluded,unused,~used_sense,~used_quiz))


def reconcile_word_visibility(db, conversation_key):
    from backend.app.models.word import Word
    from backend.app.models.word_sense import WordSense
    from backend.app.models.quiz_log import QuizLog
    conv=db.get(AutoConversation,conversation_key)
    sources=db.query(NoteSource).filter_by(conversation_id=conv.conversation_id).all()
    # Only new words created by this collector are candidates for reversible exclusion.
    created={link['word_id'] for source in sources for link in (source.word_links or [])
        if isinstance(link,dict) and link.get('auto') is True and link.get('created') is True
        and isinstance(link.get('word_id'),int)}
    targets={}
    # Inspect all ready current topics, not historical caches or only this conversation.
    for topic,conversation in db.query(AutoTopic,AutoConversation).join(
            AutoConversation,AutoTopic.conversation_key==AutoConversation.key).filter(AutoTopic.active.is_(True)):
        if topic.revision!=conversation.revision or conversation.processed_revision!=conversation.revision:
            # A pending conversation could still justify a word. Preserve its existing links.
            for result in (topic.data or {}).get('word_results',{}).values():
                if isinstance(result,dict):targets[result.get('word_id')]=True
            continue
        plan=(topic.data or {}).get('plan') or {}
        for word in plan.get('words',[]):
            targets[('vocabulary',word.get('vocabulary','').casefold())]=True
    # Pending classification/review cannot invalidate previously justified entries.
    # Only a completed, current reroute may exclude them (e.g. sentence -> note).
    pending_convs={c.conversation_id:c for c in db.query(AutoConversation).filter_by(status='review_needed')}
    if conv.status=='review_needed':pending_convs[conv.conversation_id]=conv
    if pending_convs:
        for source in db.query(NoteSource).filter(NoteSource.conversation_id.in_(list(pending_convs))):
            report=(source.extraction or {}).get('question_review') or {}
            current=pending_convs[source.conversation_id]
            if report.get('state')=='pending' and report.get('revision')==current.revision:
                for link in source.word_links or []:
                    if isinstance(link,dict) and link.get('auto') is True:
                        targets[link.get('word_id')]=True
    for word_id in created:
        word=db.get(Word,word_id)
        if word is None:continue
        justified=word_id in targets or ('vocabulary',word.vocabulary.casefold()) in targets
        used=any((getattr(word,field,0) or 0)!=0 for field in ('priority','memorize_count','total_correct','total_wrong'))
        if not used:
            used=db.query(QuizLog.id).filter(QuizLog.word_id==word_id).first() is not None
        if not used:
            for sense in db.query(WordSense).filter_by(word_id=word_id):
                if any((getattr(sense,field,0) or 0)!=0 for field in ('priority','memorize_count','total_correct','total_wrong')):
                    used=True;break
        scope=db.get(AutoWordScope,word_id)
        if scope is None:
            scope=AutoWordScope(word_id=word_id);db.add(scope)
        scope.excluded=not justified and not used
        scope.reason='질문에서 직접 요청하지 않은 자동 등록 어휘' if scope.excluded else ''
        scope.updated_at=datetime.utcnow()
    # A later explicit word question restores a previously excluded word, even if it was created elsewhere.
    for scope in db.query(AutoWordScope).filter_by(excluded=True):
        word=db.get(Word,scope.word_id)
        if word and (('vocabulary',word.vocabulary.casefold()) in targets or word.id in targets):
            scope.excluded=False;scope.reason='';scope.updated_at=datetime.utcnow()
    db.flush()
