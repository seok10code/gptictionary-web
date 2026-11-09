"""Whole-turn generation input with compatibility mapping for stored documents.

The model cites the full answer it read. Expanding that citation for the old
paragraph-based cache is structural mapping, not semantic coverage verification.
Original messages and stored source-unit numbering are never rewritten.
"""
from copy import deepcopy


def generation_units(turns,legacy_units):
    groups=[];mapping={};assigned=set()
    for turn in turns:
        sid=turn['source_id']
        question=[u['id'] for u in legacy_units if u['kind']=='question' and u['source_id']==sid]
        if question:
            uid=f's{sid}-q'
            groups.append({'id':uid,'source_id':sid,'source_ids':[sid],
                'kind':'question','text':turn['question']})
            mapping[uid]=question;assigned.update(question)
        # Deduplicated legacy paragraphs retain their original source_id. An
        # answer still arrives verbatim even if all its paragraphs are duplicates.
        members=[u['id'] for u in legacy_units if u['kind']=='answer' and u['source_id']==sid]
        if turn['answer'].strip():
            uid=f's{sid}-answer'
            groups.append({'id':uid,'source_id':sid,'source_ids':[sid],
                'kind':'answer','text':turn['answer']})
            mapping[uid]=members;assigned.update(members)
    if assigned!={u['id'] for u in legacy_units}:
        raise ValueError('입력 단위 대응에 누락이 있습니다.')
    return groups,mapping


def expand_source_references(draft,mapping,legacy_units):
    """Expand answer-scope citations without pretending they are precise quotes."""
    result=deepcopy(draft)
    def expand(ids):
        return list(dict.fromkeys(member for uid in ids for member in mapping[uid]))
    # An answer may repeat some or all canonical paragraphs from earlier turns.
    # Its citation includes those paragraphs through their source relationship.
    relations={u['id']:list(u.get('source_ids',[u['source_id']])) for u in legacy_units if u['kind']=='answer'}
    resolved={uid:([key for key,sids in relations.items() if int(uid.split('-')[0][1:]) in sids]
                   if uid.endswith('-answer') else members) for uid,members in mapping.items()}
    mapping=resolved
    result['summary_evidence_ids']=expand(result['summary_evidence_ids'])
    for section in result['sections']:
        for block in section['blocks']:block['evidence_ids']=expand(block['evidence_ids'])
    treatments={}
    for entry in result['coverage']:
        for uid in mapping[entry['unit_id']]:
            # Keep the canonical owner's treatment when a later answer is an
            # exact duplicate; another turn cannot relabel its paragraphs.
            treatments.setdefault(uid,entry['treatment'])
    result['coverage']=[{'unit_id':u['id'],'treatment':treatments[u['id']]} for u in legacy_units]
    return result
