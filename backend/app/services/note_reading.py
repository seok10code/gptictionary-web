"""Read-only layout of reviewed notes. No AI calls, writes, or new learning claims."""
import re
from markupsafe import Markup, escape
from backend.app.services.note_study import display_text


def compact(value):
    text=display_text(value)
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',text).strip()


def rich_text(value):
    # Escape first: stored/raw content never becomes executable HTML.
    value=str(escape(compact(value)))
    value=re.sub(r'\*\*([^*\n]+)\*\*',r'<strong>\1</strong>',value)
    value=re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)',r'<em>\1</em>',value)
    value=re.sub(r'`([^`\n]+)`',r'<code>\1</code>',value)
    return Markup(value)


def norm(text):
    # Only whitespace is normalized. Negation, modality, punctuation and register remain distinct.
    return re.sub(r'\s+',' ',compact(text)).strip()


ENGLISH=r'''[A-Za-z][A-Za-z0-9 '’.,!?;:()\-]*'''
PAIR=re.compile(r'''^\s*(?:[-•]\s*)?["“]?('''+ENGLISH+r''')["”]?\s*(?:→|=>)\s*(.+[가-힣].*)$''')
EN_LINE=re.compile(r'''^\s*(?:[-•]\s*)?["“]?('''+ENGLISH+r''')["”]?\s*$''')
KO_LINE=re.compile(r'^\s*(?:→|=>)\s*(.+[가-힣].*)$')


def literal_pairs(value):
    """Only adjacent, explicit English → Korean pairs; never infer table columns."""
    lines=compact(value).splitlines();result=[];i=0
    while i<len(lines):
        match=PAIR.fullmatch(lines[i])
        end=i+1
        if match:
            en,ko=match.groups()
        elif (i+1<len(lines) and (english:=EN_LINE.fullmatch(lines[i]))
              and (korean:=KO_LINE.fullmatch(lines[i+1]))):
            en,ko=english.group(1),korean.group(1);end=i+2
        else:
            i+=1;continue
        en=en.strip().strip('"“”');ko=ko.strip()
        result.append({'english':en,'korean':ko,'start':i,'end':end})
        i=end
    return lines,result


def reading_view(study):
    if not study:return None
    sections={key:[] for key in ('meaning','explanation','usage','caution')}
    examples=[];evidence=[];seen={};example_keys={};evidence_keys={}
    order={key:i for i,key in enumerate(sections)}
    for point in sorted(study['content'].points,key=lambda p:order[p.area]):
        if point.status!='supported':continue
        citation=(point.source_id,point.quote)
        if point.source_id and point.quote and citation not in evidence_keys:
            evidence_keys[citation]=len(evidence)+1
            evidence.append({'number':len(evidence)+1,'source_id':point.source_id,'quote':point.quote})
        reference=evidence_keys.get(citation)
        lines,pairs=literal_pairs(point.text)
        _,source_pairs=literal_pairs(point.quote)
        grounded={(norm(x['english']),norm(x['korean'])) for x in source_pairs}
        excluded=set()
        for pair in pairs:
            key=(norm(pair['english']),norm(pair['korean']))
            # The displayed pair must occur as a pair in the reviewed quote too.
            # Exact strings elsewhere in a paragraph do not establish binding.
            if key not in grounded:continue
            excluded.update(range(pair['start'],pair['end']))
            if key in example_keys:
                entry=example_keys[key]
            else:
                entry={'english':pair['english'],'korean':pair['korean'],'references':[]}
                examples.append(entry);example_keys[key]=entry
            if reference and reference not in entry['references']:entry['references'].append(reference)
        text=compact('\n'.join(line for i,line in enumerate(lines) if i not in excluded))
        if not text:continue
        key=norm(text)
        if key in seen:
            entry=seen[key]
        else:
            entry={'text':text,'references':[]}
            sections[point.area].append(entry);seen[key]=entry
        if reference and reference not in entry['references']:entry['references'].append(reference)
    # A single meaning is the lead summary; further verified meanings remain visible.
    return {'sections':sections,'examples':examples,'evidence':evidence,
            'has_content':any(sections.values()) or bool(examples)}


def reading_preview(study,fallback,limit=180):
    reading=reading_view(study)
    if reading:
        for key in ('meaning','explanation','usage','caution'):
            if reading['sections'][key]:return reading['sections'][key][0]['text'][:limit]
        if reading['examples']:return reading['examples'][0]['korean'][:limit]
        return '확인이 필요한 내용이 있습니다.'
    return compact(fallback)[:limit]
