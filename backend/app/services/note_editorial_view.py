"""Read-only editorial presentation. No semantic similarity deletion or grammar guessing."""
from copy import deepcopy
import re
from backend.app.services.note_flow_layout import flow_layout

NEGATIVE=('부적절한 예','틀린 예','잘못된 예','잘못된 문장','틀린 문장')
POSITIVE=('수정','수정한 예','수정 문장','올바른 예','올바른 문장')
EN_HEADERS={'영어','영문','영어표현','영어문장','문장','표현','예문'}


def exact(value):
    return re.sub(r'\s+',' ',str(value)).strip()


def english_key(value):
    return exact(re.sub(r'[*`]', '',str(value))).strip('"“”')


def source_labels(turns):
    labels={}
    for turn in turns:
        for line in str(turn.get('answer','')).splitlines():
            text=re.sub(r'[*`]', '',line).strip()
            match=re.match(r'^('+ '|'.join(NEGATIVE+POSITIVE)+r')\s*[:：]\s*(.+)$',text)
            if not match:continue
            english=re.split(r'\s*(?:→|=>)\s*',match[2],maxsplit=1)[0].strip()
            if not re.search('[A-Za-z]',english) or re.search('[가-힣]',english):continue
            if match[1] in NEGATIVE:labels[english_key(english)]={'kind':'negative','label':'부적절한 예'}
            else:labels[english_key(english)]={'kind':'positive','label':'수정 예'}
    return labels


def editorial_view(document,turns):
    result=flow_layout(document,turns);labels=source_labels(turns)
    paragraph_keys={exact(b['text']) for s in result.get('sections',[]) for b in s['blocks'] if b['kind']=='paragraph'}
    if result.get('summary') and exact(result['summary']) in paragraph_keys:result['summary']=''
    seen=set()
    for section in result.get('sections',[]):
        blocks=[]
        for block in section['blocks']:
            if block['kind']=='paragraph':
                key=exact(block['text'])
                if key in seen:continue
                seen.add(key)
            if block['kind'] in {'table','examples','source_examples'} and block.get('headers'):
                first=english_key(block['headers'][0]).replace(' ','')
                if first in EN_HEADERS:
                    statuses=[labels.get(english_key(row[0])) if row else None for row in block['rows']]
                    if any(s and s['kind']=='negative' for s in statuses):block['view_row_labels']=statuses
            blocks.append(block)
        section['blocks']=blocks
    result['sections']=[s for s in result.get('sections',[]) if s['blocks']]
    return result


def table_html(block,rich_text):
    """Escape every cell; show only explicit source or in-cell error labels."""
    from markupsafe import Markup
    headers=list(block['headers']);rows=block['rows']
    statuses=list(block.get('view_row_labels') or [None]*len(rows))
    if len(statuses)!=len(rows):statuses=[None]*len(rows)
    for i,row in enumerate(rows):
        if statuses[i] or not row:continue
        for cell in row[1:]:
            match=re.match(r'^('+ '|'.join(NEGATIVE)+r')\s*[:：]',re.sub(r'[*`]', '',cell).strip())
            if match:statuses[i]={'kind':'negative','label':'부적절한 예'};break
    classified=any(statuses)
    if classified:
        headers=['구분']+headers
        if len(headers)>2 and headers[2] in {'뜻','해석','번역'}:headers[2]='뜻·설명'
    parts=['<div class="nd-table-wrap nd-cols-'+str(len(headers))+'" tabindex="0" role="region" aria-label="'+('오류와 수정 비교' if classified else '표현과 뜻')+' 표"><table><thead><tr>']
    parts += ['<th scope="col">'+str(rich_text(h))+'</th>' for h in headers]
    parts.append('</tr></thead><tbody>')
    for row,status in zip(rows,statuses):
        cells=list(row)
        kind=status['kind'] if status else ''
        parts.append('<tr'+(' class="nd-row-'+kind+'"' if kind in {'negative','positive'} else '')+'>')
        if classified:
            icon='❌' if kind=='negative' else '✅' if kind=='positive' else ''
            label=status['label'] if status else '예문'
            parts.append('<td class="nd-example-status">'+str(rich_text(icon+' '+label))+'</td>')
        if kind=='negative' and len(cells)>1:
            text=re.sub(r'[*`]', '',cells[1]).strip()
            match=re.match(r'^('+ '|'.join(NEGATIVE)+r')\s*[:：]\s*(.*)$',text)
            if match and english_key(match[2])==english_key(cells[0]):cells[1]='—'
        parts += ['<td>'+str(rich_text(cell))+'</td>' for cell in cells]
        parts.append('</tr>')
    parts.append('</tbody></table></div>')
    return Markup(''.join(parts))
