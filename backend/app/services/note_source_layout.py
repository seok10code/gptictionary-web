"""Display source fallback using explicit structure only.

Never infer translation binding or flattened table columns from adjacency.
Lost column boundaries cannot be recovered by guessing English/Korean order.
"""
import re


def source_blocks(answer,compact,table_in,literal_pairs):
    # Read native table separators BEFORE compact() removes their boundaries.
    from backend.app.services.note_table_source import native_blocks
    blocks=[]
    for source in native_blocks(answer):
        if source['kind']=='table':
            blocks.append({'kind':'table','headers':source['headers'],'rows':source['rows']})
        else:
            blocks.extend(text_blocks(source['raw_text'],compact,table_in,literal_pairs))
    return blocks


def text_blocks(answer,compact,table_in,literal_pairs):
    paragraphs=[p.strip() for p in re.split(r'\n[ \t]*\n',compact(answer)) if p.strip()]
    blocks=[]
    def append_pair(row):
        if blocks and blocks[-1].get('kind')=='source_examples':blocks[-1]['rows'].append(row)
        else:blocks.append({'kind':'source_examples','headers':['영어 표현','뜻'],'rows':[row]})
    index=0
    while index<len(paragraphs):
        text=paragraphs[index]
        table=table_in(text)
        if table:
            blocks.append({'kind':'table','headers':table[0],'rows':table[1:]});index+=1;continue
        # Only explicit arrows bind English to Korean. A neighboring heading or
        # explanation is not a translation. Markdown/TSV tables retain columns.
        _,explicit=literal_pairs(text)
        if explicit and all(i in {j for p in explicit for j in range(p['start'],p['end'])} for i,line in enumerate(compact(text).splitlines()) if line.strip()):
            for p in explicit:append_pair([p['english'],p['korean']])
            index+=1;continue
        if index+1<len(paragraphs):
            merged_lines,pairs=literal_pairs(text+'\n'+paragraphs[index+1])
            if len(merged_lines)==2 and len(pairs)==1 and pairs[0]['start']==0 and pairs[0]['end']==2:
                append_pair([pairs[0]['english'],pairs[0]['korean']]);index+=2;continue
        blocks.append({'kind':'paragraph','text':text});index+=1
    # Ambiguous source stays verbatim prose, not a synthesized learning document.
    for block in blocks:
        if block['kind']=='source_examples':block['headers']=['영어 표현','뜻']
    return blocks
