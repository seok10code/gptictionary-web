"""Textbook document rendering; originals and history remain separate."""
import re
from markupsafe import Markup
from backend.app.services.note_source_layout import source_blocks
from backend.app.services.note_editorial_view import editorial_view,table_html
from backend.app.models.english_note import NoteSource
from backend.app.services.note_reading import compact,rich_text,literal_pairs
from backend.app.services.note_textbook import (DOCUMENT_VERSION, fingerprint, schema_for,
    textbook_document, generate_textbook)

def topic_turns(db,topic):
    plan=((topic.data or {}).get('plan') or {})
    ids=plan.get('source_ids') or []
    ids=list(dict.fromkeys(i for i in ids if isinstance(i,int) and not isinstance(i,bool)))
    if not ids:return []
    rows={s.id:s for s in db.query(NoteSource).filter(NoteSource.id.in_(ids)).all()}
    if set(rows)!=set(ids):return []
    return [{'source_id':i,'question':rows[i].question,'answer':rows[i].answer} for i in ids]


def document_preview(db,topic,section):
    ids=(((topic.data or {}).get('plan') or {}).get('source_ids') or []) if topic else []
    latest=db.get(NoteSource,ids[-1]) if ids and isinstance(ids[-1],int) else None
    return compact(latest.answer if latest else section.body if section else '')[:240]


def units_for(turns):
    units=[];seen={}
    for turn in turns:
        if turn['question'].strip():
            units.append({'id':f"s{turn['source_id']}-q",'source_id':turn['source_id'],
                'position':-1,'kind':'question','text':compact(turn['question']),
                'source_ids':[turn['source_id']]})
        # Blank-line paragraphs retain internal lists, tables and example/translation pairs.
        for index,text in enumerate(re.split(r'\n[ \t]*\n',compact(turn['answer']))):
            text=text.strip()
            if not text:continue
            key=re.sub(r'\s+',' ',text)
            if key in seen:
                seen[key]['source_ids'].append(turn['source_id'])
                continue
            unit={'id':f"s{turn['source_id']}-p{index}",'source_id':turn['source_id'],
                  'position':index,'kind':'answer','text':text,'source_ids':[turn['source_id']]}
            units.append(unit);seen[key]=unit
    return units


def table_in(text):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    # Native Markdown tables and TSV survive as real, horizontally scrollable tables.
    if len(lines)>=3 and '|' in lines[0] and re.fullmatch(r'[\s|:\-]+',lines[1]):
        rows=[[c.strip() for c in line.strip('|').split('|')] for line in [lines[0]]+lines[2:]]
    elif len(lines)>=2 and all('\t' in line for line in lines):
        rows=[[c.strip() for c in line.split('\t')] for line in lines]
    else:return None
    if len(rows[0])<2 or any(len(row)!=len(rows[0]) for row in rows):return None
    return rows


def compile_document(turns,draft=None):
    if draft is not None:
        return textbook_document(turns,units_for(turns),draft)
    # A failed generation must not hide learning content or pretend to be a synthesis.
    blocks=[]
    for turn in turns:
        blocks.extend(source_blocks(turn['answer'],compact,table_in,literal_pairs))
    return {'version':DOCUMENT_VERSION,'format':'source_fallback','fingerprint':fingerprint(turns),
            'source_ids':[t['source_id'] for t in turns], 'title':'','summary':'',
            'sections':[{'heading':'','blocks':blocks}] if blocks else []}


def generate_document(turns):
    units=units_for(turns)
    return generate_textbook(turns,units) if units else compile_document(turns)


def article_view(turns,stored=None):
    if (isinstance(stored,dict) and stored.get('version') in {2,DOCUMENT_VERSION}
            and stored.get('fingerprint')==fingerprint(turns,version=stored['version'])
            and stored.get('format')=='textbook'):
        try:
            result=textbook_document(turns,units_for(turns),stored)
            return editorial_view(result,turns)
        except (ValueError,TypeError,KeyError):pass
    return editorial_view(compile_document(turns),turns)


def _list_html(items):
    """Render indentation as nested semantic lists, never raw HTML from input."""
    if not items:return ''
    base=min(indent for indent,_ in items)
    def render(index,level):
        out=['<ul>']
        while index<len(items):
            indent,text=items[index]
            if indent<level:break
            out.append('<li>'+str(rich_text(text)));index+=1
            if index<len(items) and items[index][0]>indent:
                child,index=render(index,items[index][0]);out.append(child)
            out.append('</li>')
        out.append('</ul>')
        return ''.join(out),index
    return render(0,base)[0]


def document_text(value):
    """Escaped prose, lists, and explicit English/translation pairs."""
    if isinstance(value,dict) and value.get('kind') in {'table','examples','source_examples'}:
        return table_html(value,rich_text)
    output=[];paragraph=[];items=[]
    def flush():
        if paragraph:
            output.append('<p>'+str(rich_text('\n'.join(paragraph)))+'</p>');paragraph.clear()
        if items:
            output.append(_list_html(items));items.clear()
    lines,pairs=literal_pairs(value)
    pair_at={p['start']:p for p in pairs}
    index=0
    while index<len(lines):
        if index in pair_at:
            flush();pair=pair_at[index]
            output.append('<div class="nd-inline-example"><p class="nd-example-en" lang="en">'+str(rich_text(pair['english']))+
                '</p><p class="nd-example-ko"><span class="nd-arrow" aria-hidden="true">→</span><span>'+
                str(rich_text(pair['korean']))+'</span></p></div>')
            index=pair['end'];continue
        line=lines[index].expandtabs(4);index+=1
        heading=re.fullmatch(r'\s*(#{1,6})\s+(.+)',line)
        numbered_heading=re.fullmatch(r'\s*\d+[.)]\s+([가-힣].{1,60})',line)
        subheading=re.fullmatch(r'\s*([①-⑳]\s*[^\n]{1,90})',line)
        formula=re.fullmatch(r'\s*(주어\s*\+[^\n]{1,150})',line)
        bullet=re.fullmatch(r'(\s*)[-•]\s+(.+)',line)
        if heading or numbered_heading or subheading:
            flush()
            if heading:
                level=min(4,max(2,len(heading.group(1))))
                title=heading.group(2)
            elif numbered_heading:level=2;title=numbered_heading.group(1)
            else:level=3;title=subheading.group(1)
            tag='h'+str(level)
            output.append('<'+tag+' class="nd-prose-heading">'+str(rich_text(title))+'</'+tag+'>')
        elif formula:
            flush();output.append('<div class="nd-formula">'+str(rich_text(formula.group(1)))+'</div>')
        elif bullet:
            if paragraph:flush()
            items.append((len(bullet.group(1)),bullet.group(2)))
        elif not line.strip():flush()
        else:
            if items:flush()
            paragraph.append(line)
    flush()
    return Markup(''.join(output))
