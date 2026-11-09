"""Literal source checks for NEW textbook drafts, not semantic fact verification.

Never modifies a draft or restores missing material by guessing. Legacy cached
documents are deliberately outside this gate. Uncertain prose still needs human
review; these checks cover explicit examples and dialogue source bindings only.
"""
import re
import unicodedata
from backend.app.services.note_reading import literal_pairs, compact, EN_LINE


def key(value):
    value=unicodedata.normalize('NFKC',str(value)).replace('’',"'").replace('‘',"'")
    value=re.sub(r'[*`]', '', value)
    return re.sub(r'\s+',' ',value).strip(' \"“”').casefold()


def source_inventory(turns):
    """Adjacent arrow pairs, also across empty lines; never guess table bindings.

    Keep each complete utterance and every translation variant. Parenthesized
    usage notes stay in the inventory but can live in a separate table column.
    """
    result=[];seen=set()
    for turn in turns:
        lines=[re.sub(r'[*`]', '',line).strip() for line in compact(turn['answer']).splitlines() if line.strip()]
        for pair in literal_pairs('\n'.join(lines))[1]:
            # An explicit "A: ... → ..." is a labelled utterance, not part of
            # the English sentence itself. The dialogue gate checks its label.
            pair=dict(pair)
            labelled=re.fullmatch(r'([A-Za-z][A-Za-z0-9 ]{0,30}):\s+(.+)',pair['english'])
            if labelled:pair['english']=labelled.group(2)
            identity=(key(pair['english']),key(pair['korean']))
            if identity in seen:continue
            seen.add(identity)
            result.append({'source_id':turn['source_id'],'english':pair['english'],'korean':pair['korean']})
    return result


def english_column(block):
    if block['kind']=='dialogue':return 1
    if block['kind'] in {'table','examples'}:
        # Explicit English headers take priority over a status/label column.
        for i,header in enumerate(block['headers']):
            if re.search(r'영어|영문|english',header,re.I):return i
        for i,header in enumerate(block['headers']):
            if re.search(r'표현',header):return i
    if block['kind']=='examples':return 0
    return None


def source_utterances(turns):
    """Standalone English lines, without guessing their translation or speaker.

    Also protects unpaired expressions such as 'get back home'. Mixed Korean
    explanations, formulas with operators, and headings are not parsed as pairs.
    """
    result=[];seen=set()
    for turn in turns:
        exercise=False
        for line in compact(turn['answer']).splitlines():
            line=re.sub(r'[*`]', '',line).strip()
            if re.match(r'^(?:#{1,6}\s*)?(?:\d+[.)]\s*)?연습문제\s*$',line):exercise=True;continue
            if exercise and re.match(r'^(?:핵심 정리|기억하기|요약)\s*[:：]',line):exercise=False
            if exercise:continue
            match=EN_LINE.fullmatch(line)
            if not match:continue
            en=match.group(1).strip().strip('"“”')
            labelled=re.fullmatch(r'([A-Za-z][A-Za-z0-9 ]{0,30}):\s+(.+)',en)
            if labelled:en=labelled.group(2)
            if len(re.findall(r'[A-Za-z]+',en))<2:continue
            if key(en) in {'english expression','usage example'}:continue
            if key(en) not in seen:
                seen.add(key(en));result.append(en)
    return result


def validate_new_sources(turns,doc,require_all_examples=True):
    """Require explicit example preservation and literal source-backed dialogue.

    Translation variants must stay with their English, never somewhere else in
    the chapter. This intentionally does not accept AI coverage flags as proof.
    """
    inventory=source_inventory(turns);errors=[];rows=[]
    content=[]
    source='\n'.join(key(t['answer']) for t in turns)
    source_by_id={t['source_id']:key(t['answer']) for t in turns}
    for section in doc['sections']:
        for block in section['blocks']:
            content.extend([block['text']] if 'text' in block else [])
            content.extend(block.get('items',[]))
            content.extend(cell for row in block.get('rows',[]) for cell in row)
            # Comparison tables can contain more than one English column.
            # Never rely on the first "표현" column to vet all example cells.
            for row in block.get('rows',[]):
                for cell in row:
                    literal=key(cell)
                    if re.search('[a-z]',literal) and not re.search('[가-힣]',literal) and literal not in source:
                        errors.append('원문에 없는 표의 영어 셀: '+cell)
            col=english_column(block)
            if col is None:continue
            bound_ids={int(m.group(1)) for ref in block['evidence_ids']
                       if (m:=re.fullmatch(r's(\d+)-(?:q|p\d+)',ref))}
            grounded='\n'.join(source_by_id[sid] for sid in bound_ids if sid in source_by_id)
            for row in block['rows']:
                if len(row)<=col:continue
                en=key(row[col]);rows.append((en,row,col))
                if block['kind']=='dialogue':
                    # A speaker label, English and translation must occur together
                    # in an explicit raw dialogue (one or two adjacent lines).
                    speaker,english,korean=row
                    found=False
                    for turn in turns:
                        if turn['source_id'] not in bound_ids:continue
                        lines=[key(line) for line in turn['answer'].splitlines() if line.strip()]
                        for i,line in enumerate(lines):
                            if not re.match(r'^'+re.escape(key(speaker))+r'\s*:',line):continue
                            adjacent=' '.join(lines[i:i+2])
                            if key(english) in line and key(korean) in adjacent:found=True
                    if not found:errors.append('원문에 없는 화자·발화·번역 연결: '+english)
                elif re.search(r'[a-z]',en) and not re.search(r'[가-힣]',en):
                    if en not in source:errors.append('원문에 없는 영어 예문/표현: '+row[col])
                    elif en not in grounded:errors.append('예문이 연결된 원문에 없습니다: '+row[col])
    body='\n'.join(key(value) for value in content+[doc.get('summary','')])
    for english in source_utterances(turns) if require_all_examples else []:
        if key(english) not in body:errors.append('원문에 있는 독립 영문/표현 누락: '+english)
    for pair in inventory:
        en=key(pair['english'])
        matching=[(row,col) for english,row,col in rows if english==en]
        if not matching:
            if not require_all_examples:continue
            errors.append('완전한 원문 예문/표현 누락: '+pair['english']);continue
        # Strip only terminal usage annotation; preserve it elsewhere via the
        # existing paragraph coverage requirement. Do not strip negation/modality.
        korean=re.sub(r'\s*\([^()]*\)\s*$', '',pair['korean']).strip()
        # Explicit error labels are not Korean translations.
        if re.match(r'^(부적절한|틀린|잘못된)\s*예',korean):continue
        alternatives=[korean] if require_all_examples else [
            re.sub(r'\s*\([^()]*\)\s*$', '',p['korean']).strip() for p in inventory if key(p['english'])==en]
        if not any(key(option) in key(' '.join(cell for i,cell in enumerate(row) if i!=col))
                   for row,col in matching for option in alternatives):
            errors.append('원문 예문의 번역이 같은 행에 보존되지 않았습니다: '+pair['english'])
    return list(dict.fromkeys(errors))
