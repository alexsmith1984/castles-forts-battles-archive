#!/usr/bin/env python3
import json,re,os
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from PIL import Image
import ftfy
ROOT=Path('recovered/richards-castle'); SRC=ROOT/'source.html'; PAGE=ROOT/'index.html'; REP=ROOT/'recovery-report.json'; IMG=ROOT/'images'

def stem(u): return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()
def main():
    src=BeautifulSoup(SRC.read_text(encoding='utf-8'),'html.parser'); desktop=src.find(id='bp_infinity') or src
    expected=[]
    for im in desktop.find_all('img'):
        par=im.find_parent('a',href=True); href=(par.get('href') or '') if par else ''
        vals=[(im.get(a) or '').strip() for a in ('data-muse-src','data-orig-src','data-src','src')]
        vals=[v for v in vals if v and 'richards_castle' in v.lower() and 'blank.gif' not in v.lower()]
        if 'richards_castle' in href.lower(): ident=stem(href)
        elif vals: ident=stem(vals[0])
        else: continue
        if ident not in expected: expected.append(ident)
    # map existing local images to genuine desktop identities, allowing Muse resize suffixes
    local={p.stem.lower():p for p in IMG.iterdir() if p.is_file()}
    rows=[]; missing=[]
    for ident in expected:
        candidates=[]
        if ident in local: candidates.append((2,local[ident],ident))
        for st,p in local.items():
            if st.startswith(ident) and re.fullmatch(r'\d{2,4}x\d{2,4}',st[len(ident):]): candidates.append((1,p,st))
        if not candidates:
            missing.append({'identity':ident}); continue
        best=None
        for exact,p,st in candidates:
            try:
                with Image.open(p) as im: dims=[im.width,im.height]
            except Exception: continue
            rank=(exact,dims[0]*dims[1])
            if best is None or rank>best[0]: best=(rank,p,st,dims)
        if not best:
            missing.append({'identity':ident}); continue
        _,p,st,dims=best
        rows.append({'identity':ident,'file':'images/'+p.name,'dimensions':dims,'quality':'full/near-full' if st==ident else 'thumbnail/lower-resolution','identification':'certain','source_variant':st})
    # preserve provenance from prior reports where exact file matches
    old=json.loads(REP.read_text(encoding='utf-8')); prov={}
    for x in old.get('images',[]):
        f=x.get('file') or x.get('recovered_file')
        if f: prov[f]=x
    for x in rows:
        q=prov.get(x['file'],{})
        for k in ('archive_original','archive_timestamp','method','associated_original_text'):
            if q.get(k) is not None: x[k]=q[k]
    report={'name':"Richard's Castle",'original_url':'http://www.castlesfortsbattles.co.uk/midlands/richards_castle.html','supplied_captures':['20220826203519','20200728180812'],'best_source_capture':old.get('best_source_capture','20220826203519'),'usable_html_captures_examined':old.get('usable_html_captures_examined',['20220826203519','20200728180812']),'original_image_positions_identified':len(expected),'desktop_image_identities':expected,'recovered_full_or_near_full':sum(x['quality']=='full/near-full' for x in rows),'recovered_thumbnail_or_lower_resolution':sum(x['quality']=='thumbnail/lower-resolution' for x in rows),'still_missing':len(missing),'uncertain_identifications':[],'images':rows,'missing':missing,'counting_method':'Unique Richard’s Castle content-image identities in the desktop bp_infinity source; responsive resize duplicates are not counted as separate original positions.','verification_note':'Every reported local image was opened successfully with Pillow. No unrelated substitute photographs were used.'}
    REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    # Repair encoding artefacts only; do not rewrite wording.
    text=ftfy.fix_text(PAGE.read_text(encoding='utf-8'))
    PAGE.write_text(text,encoding='utf-8')
    assert not any(bad in text for bad in ('â','Ã','�'))
    page=BeautifulSoup(text,'html.parser')
    for im in page.find_all('img',src=True):
        p=ROOT/im['src']; assert p.exists()
        with Image.open(p) as x: x.verify()
    print(json.dumps({k:v for k,v in report.items() if k not in ('images','missing')},indent=2,ensure_ascii=False))
if __name__=='__main__': main()
