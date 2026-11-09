"""Keep explicit native table boundaries before whitespace normalization.

No language detection or translation matching. Ambiguous text remains text.
The captured tab/blank-row format is treated as data, never instructions.
"""
from copy import deepcopy
import re

CELL = re.compile(r'\n\n[ \t]*\t[ \t]*\n\n')
ROW = re.compile(r'\n{3,}')
PARAGRAPH = re.compile(r'\n\n')


def read_row(text, start):
    cells = []
    cursor = start
    for _ in range(7):
        boundary = PARAGRAPH.search(text, cursor)
        end = boundary.start() if boundary else len(text)
        cells.append(text[cursor:end].strip())
        if not boundary:
            return cells, end, end, 'end'
        cell = CELL.match(text, end)
        if cell:
            cursor = cell.end()
            continue
        row = ROW.match(text, end)
        if row:
            return cells, end, row.end(), 'row'
        return cells, end, end, 'paragraph'
    return None


def candidate_table(text, start):
    header = read_row(text, start)
    if not header:
        return None
    headers, end, next_start, kind = header
    if (not 2 <= len(headers) <= 6 or kind != 'row'
            or any(not h or '\n' in h or len(h) > 160 for h in headers)):
        return None
    rows = []
    cursor = next_start
    table_end = end
    for _ in range(80):
        row = read_row(text, cursor)
        if not row:
            break
        values, end, next_start, kind = row
        if len(values) != len(headers) or not any(values):
            break
        rows.append(values)
        table_end = end
        if kind != 'row':
            break
        cursor = next_start
    if not rows:
        return None
    return {'kind': 'table', 'headers': headers, 'rows': rows,
            'start': start, 'end': table_end, 'raw_text': text[start:table_end]}


def native_blocks(text):
    """Partition the original string losslessly; only cells are trimmed."""
    blocks = []
    cursor = 0
    for separator in CELL.finditer(text):
        if separator.start() < cursor:
            continue
        previous = text.rfind('\n\n', cursor, separator.start())
        start = previous + 2 if previous >= cursor else cursor
        while start < separator.start() and text[start] == '\n':
            start += 1
        table = candidate_table(text, start)
        if not table:
            continue
        if start > cursor:
            blocks.append({'kind': 'text', 'start': cursor, 'end': start,
                           'raw_text': text[cursor:start]})
        blocks.append(table)
        cursor = table['end']
    if cursor < len(text):
        blocks.append({'kind': 'text', 'start': cursor, 'end': len(text),
                       'raw_text': text[cursor:]})
    if ''.join(b['raw_text'] for b in blocks) != text:
        raise ValueError('원문 표 분리 중 내용이 변경되었습니다.')
    return blocks


def table_catalog(turns):
    catalog = {}
    for turn in turns:
        index = 0
        for block in native_blocks(turn['answer']):
            if block['kind'] != 'table':
                continue
            key = f"s{turn['source_id']}-table{index}"
            if key in catalog:
                raise ValueError('중복 원문 식별자입니다.')
            catalog[key] = {'headers': block['headers'], 'rows': block['rows'],
                            'answer_id': f"s{turn['source_id']}-answer"}
            index += 1
    return catalog


def resolve_source_tables(wire, catalog, collect_errors=False):
    """Preserve exact native tables; diagnose all defects before rejecting.

    New drafts choose mandatory section/gap locations. Legacy inline references
    and exact copies can be inspected without treating a correct copy as rebinding.
    No missing content is appended unless its placement was explicitly supplied.
    """
    result = deepcopy(wire)
    errors = []
    used = set()
    def cell_key(value):
        return re.sub(r'\s+', ' ', re.sub(r'[*`]', '', value)).strip(' \"“”').casefold()
    protected = {cell_key(cell) for table in catalog.values() for row in table['rows'] for cell in row
                 if re.search('[A-Za-z]', cell) and not re.search('[가-힣]', cell)}
    def materialize(key):
        table = catalog[key]
        return {'kind':'table','headers':deepcopy(table['headers']),
                'rows':[{'cells':deepcopy(row)} for row in table['rows']],
                'evidence_ids':[table['answer_id']]}
    locations = result.pop('source_table_locations', None)
    gaps = {}
    if locations is not None:
        for key, location in locations.items():
            if key not in catalog:
                errors.append('존재하지 않는 원문 표 배치: '+key);continue
            section = location['section_index']; gap = location['before_block']
            if not 1 <= section <= len(result['sections']) or not 1 <= gap <= len(result['sections'][section-1]['blocks'])+1:
                errors.append('원문 표 배치 위치가 본문 범위를 벗어났습니다: '+key);continue
            gaps.setdefault((section,gap),[]).append(key)
        errors.extend('원문 표 배치가 누락되었습니다: '+key for key in catalog if key not in locations)
    for si, section in enumerate(result['sections'],1):
        output=[]
        for bi in range(1,len(section['blocks'])+2):
            for key in gaps.get((si,bi),[]):
                output.append(materialize(key));used.add(key)
            if bi>len(section['blocks']):break
            block=section['blocks'][bi-1]
            key=block.get('table_id') if block['kind']=='source_table' else None
            if block['kind'] in {'table','examples'}:
                rows=[r['cells'] for r in block['rows']]
                matches=[tid for tid,t in catalog.items() if t['headers']==block['headers'] and t['rows']==rows
                         and t['answer_id'] in block['evidence_ids']]
                if matches:key=matches[0]
            if key is not None:
                if key not in catalog:
                    errors.append('존재하지 않는 원문 표 참조: '+key);continue
                if key in {tid for keys in gaps.values() for tid in keys}:
                    # Only a whole, exactly identical source table may be
                    # suppressed here. Partial/changed copies are never dropped.
                    continue
                if key in used:
                    errors.append('원문 표 참조가 중복되었습니다: '+key);continue
                output.append(materialize(key));used.add(key);continue
            if block['kind'] in {'table','examples','dialogue'}:
                for row in block.get('rows',[]):
                    cells=list(row.values()) if block['kind']=='dialogue' else row['cells']
                    if any(cell_key(cell) in protected for cell in cells):
                        errors.append('원문 표와 다른 셀 연결입니다: '+' / '.join(cells))
            output.append(block)
        section['blocks']=output
    errors.extend('원문 표 배치가 누락되었습니다: '+key for key in catalog if key not in used)
    errors=list(dict.fromkeys(errors))
    if collect_errors:return result,errors
    if errors:raise ValueError('\n'.join(errors))
    return result
