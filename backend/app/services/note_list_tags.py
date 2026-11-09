"""Small display-only labels from stored keywords/headings. No DB/API or mutation."""
import json
import re
import unicodedata

_GENERIC={'영어','영어학습','영어표현','영어문법','문법','표현','문장','시제','시제차이','차이','차이점','비교',
          '기본개념','개념','핵심정리','정리','요약','예문','사용예','사용예문','문장구조','문장유형','문장유형비교',
          '문장구조및예문','사용법','사용조건','사용조건및예외','상황별표현','상황과핵심뜻',
          'grammar','expression','sentence','english','examples','summary'}

def key(value):
    return re.sub(r'[^a-z0-9가-힣]','',unicodedata.normalize('NFKC',value).lower())

def saved_terms(value):
    if isinstance(value,list):return [v for v in value if isinstance(v,str)]
    if not isinstance(value,str) or not value.strip():return []
    if value.lstrip().startswith('['):
        try:
            decoded=json.loads(value)
            if isinstance(decoded,list):return saved_terms(decoded)
        except (ValueError,TypeError):pass
    # Flat space-joined metadata cannot safely recover multiword phrases.
    # Preserve it as a phrase, rather than splitting 'be going to' into fragments.
    return re.split(r'[,;，；\n]+',value)

def clean(value,title_key):
    if not isinstance(value,str):return ''
    value=unicodedata.normalize('NFKC',value)
    value=re.sub(r'[`*#]','',value).strip()
    value=re.sub(r'^(?:\d+[.)]|[①②③④⑤⑥⑦⑧⑨⑩])\s*','',value)
    value=re.sub(r'\s+',' ',value)
    # Keep a literal short subheading after a title prefix or em dash.
    if ' — ' in value:value=value.rsplit(' — ',1)[1]
    if '의 ' in value:
        prefix,rest=value.split('의 ',1)
        parts=[key(p) for p in re.split(r'와|과|랑|하고|\s+(?:vs|and)\s+',prefix) if key(p)]
        if parts and all(part in title_key for part in parts):value=rest
    value=re.sub(r'의 경우$','',value).strip()
    return value

def note_tags(title,subject,keywords,document=None,stored_keywords=None):
    title_key=key(title or '')
    context=title_key+key(subject or '')
    sections=(document or {}).get('sections',[]) if isinstance(document,dict) else []
    candidates=saved_terms(stored_keywords)
    candidates += [s.get('heading','') for s in sections if isinstance(s,dict)]
    candidates += saved_terms(keywords)
    result=[];seen=set()
    for raw in candidates:
        label=clean(raw,title_key);normalized=key(label)
        if not normalized or normalized in _GENERIC or len(label)>28:continue
        if normalized in context:continue
        reduced=normalized
        for generic in ('일부동사','기본개념','사용조건','사용','조건','예외','예문','및','의'):
            reduced=reduced.replace(generic,'')
        if reduced and reduced in title_key:continue
        if any(normalized in previous or previous in normalized for previous in seen):continue
        seen.add(normalized);result.append(label)
        if len(result)==3:break
    return result
