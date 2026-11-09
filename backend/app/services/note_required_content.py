"""Required literal locations are checked against visible content, not AI flags.

These are structural safeguards. They do not verify all Korean explanations or
infer a translation by selecting an unrelated source paragraph.
"""
import re
from backend.app.services.note_source_guard import source_utterances,key


def utterance_catalog(turns,tables):
    native={key(cell) for table in tables.values() for row in table['rows'] for cell in row}
    result={}
    for english in source_utterances(turns):
        if key(english) in native:continue
        answer_ids=[f"s{t['source_id']}-answer" for t in turns if key(english) in key(t['answer'])]
        result[f'example{len(result)}']={'english':english,'answer_ids':answer_ids}
    return result


def validate_locations(wire,required):
    locations=wire.get('required_example_locations',{});errors=[]
    for uid,source in required.items():
        location=locations.get(uid)
        if not isinstance(location,dict):
            errors.append('예문별 본문 위치가 누락되었습니다: '+source['english']);continue
        try:
            si=location['section_index'];bi=location['block_index']
            if si<1 or bi<1:raise IndexError
            block=wire['sections'][si-1]['blocks'][bi-1]
        except (KeyError,IndexError,TypeError):
            errors.append('예문 위치가 본문 범위를 벗어났습니다: '+source['english']);continue
        values=[block.get('text','')]+block.get('items',[])
        for row in block.get('rows',[]):
            values.extend(row.get('cells',[]) if 'cells' in row else list(row.values()))
        if key(source['english']) not in '\n'.join(key(v) for v in values):
            errors.append('지정한 본문 위치에 완전한 예문이 없습니다: '+source['english'])
        if not set(block.get('evidence_ids',[])) & set(source['answer_ids']):
            errors.append('예문 위치가 해당 원문 답변과 연결되지 않았습니다: '+source['english'])
    for uid in set(locations)-set(required):errors.append('존재하지 않는 필수 예문 번호: '+uid)
    return errors
