"""Conservative read-only layout from literal rows and source relationships.

No synonym/semantic deletion. Ambiguous placement and additional conditions are
left intact. Stored documents, source text and coverage metadata are unchanged.
"""
from copy import deepcopy
import re


def exact(value):return re.sub(r'\s+',' ',str(value)).strip()


def table_columns(block):
    headers=[re.sub(r'[\s*`]', '',v) for v in block.get('headers',[])]
    en=next((i for i,h in enumerate(headers) if h in {'영어','영문','영어표현','영어문장'}),None)
    status=next((i for i,h in enumerate(headers) if h=='구분'),None)
    return en,status


def source_ids(block):
    return {int(m[1]) for ref in block.get('evidence_ids',[]) if (m:=re.fullmatch(r's(\d+)-p\d+',ref))}


def formula_view(block,turns):
    if block['kind']!='paragraph':return
    text=exact(block['text'])
    for turn in turns:
        if turn['source_id'] not in source_ids(block):continue
        for paragraph in re.split(r'\n\s*\n',turn['answer']):
            formulas=[]
            for line in paragraph.splitlines():
                match=re.fullmatch(r'\s*([^:：\n]{1,40}?)\s*구조\s*[:：]\s*(.+\+.+)\s*',line)
                if not match:break
                formulas.append((match[1].strip(),match[2].strip()))
            else:
                if not formulas:continue
                # Only the exact prose wrapper around these source formulas.
                # Any extra caveat/condition prevents conversion.
                prose='이며, '.join(f'{label}의 구조는 {rhs}' for label,rhs in formulas)+'입니다.'
                if exact(prose)==text:
                    block['kind']='formula'
                    block['text']='\n'.join(f'{label}: {rhs}' for label,rhs in formulas)
                    return


def flow_layout(document,turns):
    result=deepcopy(document);sections=result.get('sections',[])
    tables=[b for s in sections for b in s['blocks'] if b['kind'] in {'examples','table','source_examples'}]
    generic_tables={id(b) for s in sections if exact(s.get('heading','')) in {'예문','예문 모음'}
                    for b in s['blocks'] if b['kind']=='examples'}
    # A complete identical payload already in an explicit correction comparison
    # need not also appear as a normal example. Extra cells/wording stay intact.
    correction_payloads=set()
    for block in tables:
        en,status=table_columns(block)
        if en is None or status is None:continue
        for row in block.get('rows',[]):
            if len(row)!=len(block['headers']):continue
            label=re.sub(r'[✅❌\s*`]', '',row[status])
            if label in {'수정예','수정','올바른예','부적절한예','틀린예'}:
                correction_payloads.add(tuple(exact(c) for i,c in enumerate(row) if i!=status))
    for block in tables:
        if id(block) not in generic_tables:continue
        en,status=table_columns(block)
        if en is None or status is not None:continue
        block['rows']=[r for r in block.get('rows',[]) if tuple(exact(c) for c in r) not in correction_payloads]
    for section in sections:
        for block in section['blocks']:formula_view(block,turns)
    # Rehome only rows from a generic mixed-source example collection. A unique
    # prose owner from that same raw answer is mandatory. Headings are not used
    # to infer meaning, and existing deliberate comparison tables stay in place.
    owners={}
    for index,section in enumerate(sections):
        prose=[b for b in section['blocks'] if b['kind'] in {'paragraph','list'}]
        refs=set().union(*(source_ids(b) for b in prose)) if prose else set()
        if len(refs)==1:owners.setdefault(next(iter(refs)),[]).append(index)
    moves={}
    for index,section in enumerate(sections):
        if exact(section.get('heading','')) not in {'예문','예문 모음'}:continue
        for block in section['blocks']:
            if block['kind']!='examples' or len(source_ids(block))<2:continue
            en,status=table_columns(block)
            if en is None or status is not None:continue
            kept=[];groups={}
            for row in block.get('rows',[]):
                if len(row)!=len(block['headers']):kept.append(row);continue
                matches={t['source_id'] for t in turns if exact(row[en]) in exact(t['answer'])}
                candidates=owners.get(next(iter(matches)),[]) if len(matches)==1 else []
                if len(candidates)!=1 or candidates[0]==index:kept.append(row);continue
                groups.setdefault(candidates[0],[]).append(row)
            block['rows']=kept
            for target,rows in groups.items():
                moved=deepcopy(block);moved['rows']=rows
                moves.setdefault(target,[]).append(moved)
    for index,section in enumerate(sections):
        section['blocks']=[b for b in section['blocks'] if b['kind'] not in {'examples','table','source_examples'} or b.get('rows')]
        section['blocks'].extend(moves.get(index,[]))
    result['sections']=[s for s in sections if s['blocks']]
    return result
