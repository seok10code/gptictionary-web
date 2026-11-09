"""Question-owned routing, bounded topic review, and durable pending results.

The server creates one question record per source. Dependent questions share their referenced
question's topic, regardless of the word/note label. AI never chooses source IDs or creates/splits persistence topics.
A pending followup holds its whole topic, so a possible correction cannot be skipped.
"""
import hashlib
import json
from openai import OpenAIError
from pydantic import ValidationError
from backend.app.services.note_auto_ai import ConversationPlan,TopicDraft,payload_hash,validate_plan
from backend.app.services.note_auto_review import review_plan,REVIEW_VERSION,NOTE_EDITORIAL_VERSION
from backend.app.services.note_question_intent import classify_question,RequestIntent,invalid_request
from backend.app.services.note_learning import NoteProblem

PIPELINE_VERSION = 2


def expected_review_error(error):
    return isinstance(error,(OpenAIError,ValidationError,NoteProblem))


def build_plan(turns, previous=None, heartbeat=lambda:None):
    fingerprint=payload_hash(turns)
    reusable=bool(previous and previous.get('pipeline_version')==PIPELINE_VERSION
                  and previous.get('review_version')==REVIEW_VERSION
                  and previous.get('fingerprint')==fingerprint)
    old=previous if reusable else {}
    request_cache={}
    reports={}
    requests={}
    seen=set()
    for index,turn in enumerate(turns):
        sid=turn['source_id'];key=str(sid)
        if sid in seen:raise NoteProblem('질문 원본 번호가 중복되어 저장을 중단했습니다.')
        seen.add(sid)
        heartbeat()
        raw=old.get('requests',{}).get(key)
        request=RequestIntent.model_validate(raw) if raw else None
        if request is None or request.review_required:
            request=classify_question(turn,turns[max(0,index-2):index],turns[index+1:index+3])
        if request.source_id!=sid:raise NoteProblem('질문 검토 원본 번호를 확인할 수 없습니다.')
        if not request.review_required:
            problem=invalid_request(request,turn)
            if problem:raise NoteProblem('저장된 질문 검토 결과를 확인할 수 없습니다.')
        requests[sid]=request;request_cache[key]=request.model_dump()
        reports[key]={'state':'pending' if request.review_required else 'ready','stage':'intent',
                      'reason':request.review_reason,'intent':request.intent,
                      'targets':[w.vocabulary for w in request.words]}
        heartbeat()
    from backend.app.services.note_question_relation import resolve_relation
    relations={}
    parents={t['source_id']:t['source_id'] for t in turns}
    def root(sid):
        while parents[sid]!=sid:
            parents[sid]=parents[parents[sid]];sid=parents[sid]
        return sid
    def join(sid,prior):parents[root(sid)]=root(prior)
    for index,turn in enumerate(turns):
        heartbeat()
        sid=turn['source_id'];key=str(sid);request=requests[sid]
        if request.intent in {'word','translation','mixed'} and not request.review_required:
            relation={'relation':'new','parent_source_id':None,'reason':'직접 물은 독립 어휘','question_quote':''}
        else:
            relation=old.get('relations',{}).get(key)
            if not relation or relation.get('relation')=='uncertain':
                try:relation=resolve_relation(turn,turns[:index])
                except Exception as error:
                    if not expected_review_error(error):raise
                    relation={'relation':'uncertain','parent_source_id':None,
                              'reason':str(error) if isinstance(error,NoteProblem) else
                                  '질문 연결 응답 오류 ('+type(error).__name__+
                                  (', HTTP '+str(error.status_code) if getattr(error,'status_code',None) else '')+').',
                              'error_type':type(error).__name__,'question_quote':''}
        prior_ids={t['source_id'] for t in turns[:index]}
        if relation['relation']=='linked':
            if relation.get('parent_source_id') not in prior_ids:
                raise NoteProblem('질문 연결이 이전 원본을 가리키지 않습니다.')
            join(sid,relation['parent_source_id'])
        elif relation['relation']=='uncertain':
            # An unresolved reference may correct a prior answer. Hold potentially
            # affected topics rather than save that earlier answer as confirmed.
            for prior in prior_ids:join(sid,prior)
            requests[sid]=request.model_copy(update={'review_required':True,
                'review_reason':relation.get('reason') or '관련 질문 연결을 확인하지 못해 저장을 보류했습니다.'})
            request_cache[key]=requests[sid].model_dump()
            reports[key].update(state='pending',stage='relation',reason=requests[sid].review_reason)
        relations[key]=relation
        reports[key]['relation']=relation
        heartbeat()
    components={}
    for turn in turns:components.setdefault(root(turn['source_id']),[]).append(turn)
    groups=[];ignored=[]
    for group in components.values():
        if all(requests[t['source_id']].intent=='other' and not requests[t['source_id']].review_required for t in group):
            ignored.extend(t['source_id'] for t in group)
        else:groups.append(group)
    topics=[];topic_cache={}
    for group in groups:
        heartbeat()
        ids=[t['source_id'] for t in group]
        if any(requests[sid].review_required for sid in ids):
            for sid in ids:
                reports[str(sid)].update(state='pending',stage='relation' if any(reports[str(s)]['stage']=='relation' for s in ids) else 'intent',
                    reason=reports[str(sid)]['reason'] or '관련 질문·정정의 확인이 필요해 이 주제의 저장을 보류했습니다.')
            ignored.extend(ids);continue
        token_payload={'turns':group,'requests':[request_cache[str(sid)] for sid in ids],
                       'version':REVIEW_VERSION}
        # Keep the existing vocabulary cache keys unchanged. The note editorial
        # revision is consulted only when an existing/new conversation is processed.
        if any(requests[sid].intent not in {'word','translation'} for sid in ids):
            token_payload['note_editorial_version']=NOTE_EDITORIAL_VERSION
        token=hashlib.sha256(json.dumps(token_payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        try:
            prior=old.get('topics',{}).get(token)
            if prior:
                reviewed=validate_plan(ConversationPlan.model_validate(prior),group)
                # Cached acceptance cannot bypass current request scope.
                from backend.app.services.note_question_intent import requested_word
                by_id={t['source_id']:t for t in group}
                if any(not requested_word(w,requests[w.source_id],by_id[w.source_id]) for t in reviewed.topics for w in t.words):
                    raise NoteProblem('이전 어휘 검토의 질문 범위가 현재 기준과 다릅니다.')
            else:
                draft=ConversationPlan(topics=[TopicDraft(source_ids=ids,route='note',note=None,words=[])],ignored_source_ids=[])
                reviewed=review_plan(draft,group,heartbeat,requests={sid:requests[sid] for sid in ids})
            topics.extend(reviewed.topics);ignored.extend(reviewed.ignored_source_ids)
            topic_cache[token]=reviewed.model_dump()
            for sid in ids:reports[str(sid)].update(state='ready',stage='review',reason='')
        except Exception as error:
            if not expected_review_error(error):raise
            reason=str(error) if isinstance(error,NoteProblem) else 'AI 검토 응답을 확인하지 못했습니다 ('+type(error).__name__+').'
            for sid in ids:reports[str(sid)].update(state='pending',stage='review',reason=reason)
            ignored.extend(ids)
        heartbeat()
    plan=validate_plan(ConversationPlan(topics=topics,ignored_source_ids=ignored),turns)
    return plan,{'pipeline_version':PIPELINE_VERSION,'review_version':REVIEW_VERSION,
                 'fingerprint':fingerprint,'plan':plan.model_dump(),'requests':request_cache,
                 'topics':topic_cache,'reports':reports,'relations':relations}
