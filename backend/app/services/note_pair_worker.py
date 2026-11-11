"""One durable question/answer job per claim. Old conversation worker is not run."""
import asyncio,copy,hashlib,json,logging,re
from datetime import datetime
from sqlalchemy import or_,inspect
from sqlalchemy.orm import sessionmaker
from backend.app.models.english_note import EnglishNote,NoteSection,NoteSource,NoteSourceLink
from backend.app.models.note_auto import AutoTopic
from backend.app.models.note_pair_queue import NotePairJob,NotePairDocument,NotePairLane
from backend.app.services.note_pair_queue import claim,owned,finish,fail,heartbeat,prior_job
from backend.app.services import note_pair_editor as editor

log=logging.getLogger(__name__)

class VersionConflict(Exception):pass

def existing_document(db,note):
    stored=db.get(NotePairDocument,note.id)
    if stored:return copy.deepcopy(stored.document)
    topic=db.query(AutoTopic).filter_by(note_id=note.id,active=True).first()
    old=(topic.data or {}).get('document') if topic else None
    if old and old.get('format')=='textbook' and old.get('sections'):
        doc=copy.deepcopy(old)
    else:
        section=db.query(NoteSection).filter_by(note_id=note.id).order_by(NoteSection.version.desc()).first()
        doc=editor.empty_document(note.title)
        if section:doc['sections']=[{'heading':'기존 정리','source_ids':[],
            'blocks':[{'kind':'paragraph','text':section.body,'evidence_ids':[]}]}]
    result=editor.empty_document(doc.get('title') or note.title)
    for index,s in enumerate(doc.get('sections',[])):
        section={'key':f'existing-{index}','heading':s.get('heading',''),
            'source_ids':s.get('source_ids',[]),'blocks':copy.deepcopy(s['blocks'])}
        result['sections'].append(section)
    return result

def candidates(db,turn,previous):
    # Indexed metadata search, then bounded recent fallback. Raw histories are not read.
    words=list(dict.fromkeys(re.findall(r'[A-Za-z][A-Za-z-]{2,}|[가-힣]{2,}',turn['question'])))[:12]
    checks=[]
    for word in words:
        if word in {'영어로','설명해','알려줘','어떻게','예문으로','차이를','구조와'}:continue
        for col in (EnglishNote.title,EnglishNote.subject,EnglishNote.keywords):checks.append(col.contains(word,autoescape=True))
    managed=db.query(AutoTopic.key).filter(AutoTopic.note_id==EnglishNote.id).exists()
    active=db.query(AutoTopic.key).filter(AutoTopic.note_id==EnglishNote.id,AutoTopic.active.is_(True)).exists()
    paired=db.query(NotePairDocument.note_id).filter(NotePairDocument.note_id==EnglishNote.id).exists()
    visible=db.query(EnglishNote).filter(or_(~managed,active,paired))
    matches=visible.filter(or_(*checks)).order_by(EnglishNote.updated_at.desc()).limit(40).all() if checks else []
    explicit_followup=bool(editor.FOLLOWUP_SHAPE.search(turn['question']))
    prior_ids=[p['note_id'] for p in previous if p.get('note_id')] if explicit_followup else []
    earlier=db.query(EnglishNote).filter(EnglishNote.id.in_(prior_ids)).all() if prior_ids else []
    combined={}
    for n in earlier+matches:combined.setdefault(n.id,n)
    return [{'note_id':n.id,'title':n.title,'kind':n.kind,'subject':n.subject,'keywords':n.keywords}
        for n in list(combined.values())[:55]]

def load_input(factory,job_id,token):
    with factory() as db:
        job,lane=owned(db,job_id,token)
        source=db.get(NoteSource,job.source_id)
        turn={'source_id':source.id,'question':source.question,'answer':source.answer}
        prior=[];cursor=job;seen={job.question_id}
        for _ in range(2):
            predecessor=prior_job(db,cursor)
            if not predecessor or predecessor.question_id in seen:break
            seen.add(predecessor.question_id);prior.append(predecessor);cursor=predecessor
        context=[]
        for p in reversed(prior):
            s=db.get(NoteSource,p.source_id)
            context.append({'source_id':s.id,'question':s.question,'answer':s.answer[:10000],
                'note_id':p.note_id,'context_truncated':len(s.answer)>10000})
        options=candidates(db,turn,context)
        info={'turn':turn,'context':context,'candidates':options,'old_result':copy.deepcopy(job.result or {})}
        db.commit();return info

def save_note(factory,job_id,token,route,document,expected_version,expected_note_id):
    with factory() as db:
        job,lane=owned(db,job_id,token);source=db.get(NoteSource,job.source_id)
        if expected_note_id is None:
            # Same concrete canonical title is an additional uniqueness guard;
            # semantic matching remains the routing decision, not a keyword-only merge.
            topic_key=hashlib.sha256(('pair-note:'+route.kind+':'+editor.text_key(route.title)).encode()).hexdigest()
            note=db.query(EnglishNote).filter_by(topic_key=topic_key).with_for_update().first()
            if note:raise VersionConflict('동시에 같은 노트가 생성되었습니다.')
            note=EnglishNote(topic_key=topic_key,title=document['title'],kind=route.kind,
                subject=route.subject,keywords=' '.join(route.keywords),version=0,studied_version=0)
            db.add(note);db.flush()
        else:
            note=db.query(EnglishNote).filter_by(id=expected_note_id).with_for_update().one()
            if note.version!=expected_version:raise VersionConflict('다른 작업이 노트를 수정했습니다.')
            if not editor.compatible_topic(source.question,note.title):
                raise ValueError('비교 대상이 다른 기존 노트에는 저장할 수 없습니다.')
            if document['title']!=note.title:
                raise ValueError('기존 노트의 제목/주제 변경을 차단했습니다.')
        body=editor.plain_body(document)
        latest=db.query(NoteSection).filter_by(note_id=note.id).order_by(NoteSection.version.desc()).first()
        if not latest or latest.body!=body or note.title!=document['title']:
            note.version+=1;note.updated_at=datetime.utcnow()
            content_hash=hashlib.sha256((str(note.id)+':'+str(note.version)+':'+body).encode()).hexdigest()
            db.add(NoteSection(note_id=note.id,source_id=source.id,version=note.version,
                content_hash=content_hash,heading=document['title'],body=body,recall_question=''))
        # Metadata is set once for a new note and remains canonical on follow-up edits.
        # A later answer cannot silently move an existing note to another subject.
        if expected_note_id is None:
            note.title=route.title;note.subject=route.subject;note.kind=route.kind
        note.keywords=' '.join(dict.fromkeys((note.keywords or '').split()+route.keywords))[:4000]
        doc=db.get(NotePairDocument,note.id)
        if doc is None:doc=NotePairDocument(note_id=note.id,revision=0);db.add(doc)
        doc.revision+=1;doc.document=document;doc.updated_at=datetime.utcnow()
        if not db.query(NoteSourceLink.id).filter_by(note_id=note.id,source_id=source.id).first():
            db.add(NoteSourceLink(note_id=note.id,source_id=source.id))
        job.note_id=note.id
        source.notes_applied=True;source.status='done'
        source.extraction={**(source.extraction or {}),'pair_queue':{'job_id':job.id,'route':'note','note_id':note.id}}
        finish(db,job,lane,'done',{'route':'note','note_id':note.id,'note_version':note.version,'reason':route.reason})
        db.commit()

def snapshot_note(factory,note_id,title):
    if note_id is None:return editor.empty_document(title),None
    with factory() as db:
        note=db.get(EnglishNote,note_id)
        if note is None:raise ValueError('대상 노트를 찾지 못했습니다.')
        return existing_document(db,note),note.version

async def process_word(factory,job_id,token,turn,old_result):
    # Reuse the existing direct-word admission/review and the dictionary service.
    # Synonyms, antonyms, examples, Wiktionary/MCP, and sense handling are unchanged.
    from backend.app.services.note_review_pipeline import build_plan
    from backend.app.services.note_auto_worker import save_word
    plan,cache=await asyncio.to_thread(build_plan,[turn],None,lambda:heartbeat(factory,job_id,token))
    report=cache['reports'][str(turn['source_id'])]
    if report['state']=='pending':raise ValueError(report['reason'] or '단어 검토 대기')
    words=[w for topic in plan.topics for w in topic.words]
    if not words:raise ValueError('검토를 통과한 직접 요청 어휘가 없습니다.')
    results=dict(old_result.get('words',{}))
    for word in words:
        heartbeat(factory,job_id,token)
        key=hashlib.sha256(json.dumps(word.model_dump(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if key in results:continue
        with factory() as word_db:
            saved=await asyncio.wait_for(save_word(word_db,word),timeout=120)
            if not saved.get('found') or not saved.get('word'):raise ValueError('단어 저장 검토를 완료하지 못했습니다.')
            entry=saved['word'];link={'target_key':key,'word_id':entry.id,'vocabulary':entry.vocabulary,
                'sense_id':getattr(saved.get('selected_sense'),'id',None),'requested_meaning':word.requested_meaning,
                'created':bool(saved.get('created')),'question_quote':word.question_quote,'auto':True}
        results[key]=link
        with factory() as db:
            job,lane=owned(db,job_id,token);source=db.get(NoteSource,job.source_id)
            links=list(source.word_links or [])
            if not any(v.get('target_key')==key for v in links if isinstance(v,dict)):source.word_links=links+[link]
            job.result={'route':'word','words':results};db.commit()
    with factory() as db:
        job,lane=owned(db,job_id,token);source=db.get(NoteSource,job.source_id);source.status='done'
        source.extraction={**(source.extraction or {}),'pair_queue':{'job_id':job.id,'route':'word'}}
        finish(db,job,lane,'done',{'route':'word','words':results});db.commit()

async def process(factory,job_id,token):
    data=load_input(factory,job_id,token);turn=data['turn']
    route=await asyncio.to_thread(editor.route_pair,turn,data['context'],data['candidates'])
    heartbeat(factory,job_id,token)
    if route.route=='other':
        with factory() as db:
            job,lane=owned(db,job_id,token)
            finish(db,job,lane,'ignored',{'route':'other','reason':route.reason});db.commit()
    elif route.route=='word':await process_word(factory,job_id,token,turn,data['old_result'])
    else:
        document,version=snapshot_note(factory,route.note_id,route.title)
        edited=await asyncio.to_thread(editor.edit_pair,turn,document,job_id)
        heartbeat(factory,job_id,token)
        save_note(factory,job_id,token,route,edited,version,route.note_id)

def job_error_detail(error):
    from openai import BadRequestError
    if isinstance(error,BadRequestError):
        body=error.body if isinstance(error.body,dict) else {}
        details=body.get('error',body)
        if not isinstance(details,dict):details={}
        parts=['BadRequestError','status=400']
        for key in ('code','param','message'):
            value=details.get(key)
            if not isinstance(value,(str,int)):continue
            value=str(value)
            value=re.sub(r'(?i)bearer\s+[^\s"\']+','Bearer [REDACTED]',value)
            value=re.sub(r'sk-[A-Za-z0-9_-]+','[REDACTED]',value)
            value=re.sub(r'https?://[^\s]+','[URL REDACTED]',value)
            parts.append(key+'='+value[:2200])
        if len(parts)==2:parts.append('message=API 오류 응답에 상세 필드가 없습니다.')
        return ' · '.join(parts)[:2800]
    return str(error)[:2000] if isinstance(error,(ValueError,VersionConflict)) else type(error).__name__

async def run_once(factory):
    selected=claim(factory)
    if selected is None:return False
    job_id,token=selected
    try:await process(factory,job_id,token)
    except asyncio.CancelledError:
        fail(factory,job_id,token,'서버 종료로 중단되었습니다. 대기 후 이어서 처리합니다.',retry=True);raise
    except Exception as error:
        # Preserve existing note/document on any generation/format failure.
        # Only transaction/version or transport failures receive bounded retry.
        from openai import APIConnectionError,APITimeoutError,RateLimitError
        from sqlalchemy.exc import OperationalError,IntegrityError
        retry=isinstance(error,(VersionConflict,OperationalError,IntegrityError,APIConnectionError,APITimeoutError,RateLimitError))
        detail=job_error_detail(error)
        fail(factory,job_id,token,detail,retry=retry)
        log.warning('English pair job %s failed: %s',job_id,detail)
    return True

def diagnostic(error,stage):
    original=getattr(error,'orig',None)
    args=getattr(original,'args',())
    code=args[0] if args and isinstance(args[0],int) else None
    result={'stage':stage,'exception':type(error).__name__,'mysql_code':code}
    name=getattr(error,'name',None)
    if isinstance(name,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name):result['name']=name
    return result


def check_ready(factory):
    from backend.app.services.note_learning import write_guard
    stage='database_guard'
    try:
        with factory() as db:
            write_guard(db)
            # Probe the columns the worker actually uses, rather than requiring
            # information_schema access through has_table(). No writes or AI.
            for model in (NotePairJob,NotePairLane,NotePairDocument):
                stage=model.__tablename__
                db.query(model).limit(1).all()
        return True,None
    except Exception as error:return False,diagnostic(error,stage)


async def loop(factory,stop):
    ready=False
    last_error=None
    last_log_at=0.0
    while not stop.is_set():
        delay=2
        try:
            if not ready:
                ready,problem=await asyncio.to_thread(check_ready,factory)
                if ready:
                    print('영어 질문 큐: DB 확인 완료 · 질문별 처리를 시작합니다.',flush=True)
                    last_error=None
                else:
                    import time
                    signature=json.dumps(problem,sort_keys=True)
                    now=time.monotonic()
                    if signature!=last_error or now-last_log_at>=30:
                        log.warning('영어 질문 큐: DB 준비 대기 · %s · 10초 후 자동 재확인',signature)
                        last_error=signature;last_log_at=now
                    delay=10
            if ready:await run_once(factory)
        except asyncio.CancelledError:raise
        except Exception as error:
            import time
            problem=diagnostic(error,'claim_or_worker')
            signature=json.dumps(problem,sort_keys=True)
            now=time.monotonic()
            if signature!=last_error or now-last_log_at>=30:
                log.warning('영어 질문 큐: 처리 확인 필요 · %s',signature)
                last_error=signature;last_log_at=now
            ready=False;delay=10
        try:await asyncio.wait_for(stop.wait(),timeout=delay)
        except asyncio.TimeoutError:pass


async def start_worker(app):
    from backend.app.db.database import engine
    engine.echo=False;engine.hide_parameters=True
    factory=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    app.state.note_auto_stop=asyncio.Event()
    app.state.note_auto_task=asyncio.create_task(loop(factory,app.state.note_auto_stop))
    print('영어 질문 큐: 작업자 시작 · DB 확인 후 자동으로 처리합니다.',flush=True)
