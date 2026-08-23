#!/usr/bin/env python3
from __future__ import annotations
import os,re,time,hashlib
from pathlib import Path
from urllib.parse import urljoin,urlsplit,quote
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path('recovered/richards-castle'); SRC=ROOT/'source.html'; IMG=ROOT/'images'
ORIG='http://www.castlesfortsbattles.co.uk/midlands/richards_castle.html'
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 CastlesFortsBattles Richard Castle targeted recovery'

def get(u,timeout=10):
    try:return S.get(u,timeout=timeout,allow_redirects=True)
    except Exception:return None

def stem(u):return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()
def image_ok(r):
    if not r or r.status_code!=200 or len(r.content)<150:return False
    b=r.content;ct=(r.headers.get('content-type') or '').lower()
    return 'image/' in ct or b[:2]==b'\xff\xd8' or b[:8]==b'\x89PNG\r\n\x1a\n' or b[:6] in (b'GIF87a',b'GIF89a')
def dims_bytes(b):
    p=ROOT/'.tmp-richards-image';p.write_bytes(b)
    try:
        with Image.open(p) as im:return (im.width,im.height)
    finally:p.unlink(missing_ok=True)

def cdx(pattern):
    u='https://web.archive.org/cdx/search/cdx?url='+quote(pattern,safe=':/_*')+'&output=json&fl=timestamp,original,length&filter=statuscode:200&collapse=digest&limit=200'
    r=get(u,12)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    if not isinstance(d,list) or len(d)<2:return []
    return [dict(zip(d[0],x)) for x in d[1:] if len(x)==len(d[0])]

def main():
    soup=BeautifulSoup(SRC.read_text(encoding='utf-8'),'html.parser'); desktop=soup.find(id='bp_infinity') or soup
    positions=[];variants={}
    for im in desktop.find_all('img'):
        par=im.find_parent('a',href=True);href=(par.get('href') or '') if par else ''
        vals=[(im.get(a) or '').strip() for a in ('data-muse-src','data-orig-src','data-src','src')]
        vals=[v for v in vals if v and 'richards_castle' in v.lower() and 'blank.gif' not in v.lower()]
        if 'richards_castle' in href.lower():ident=stem(href)
        elif vals:ident=stem(vals[0])
        else:continue
        if ident not in positions:positions.append(ident)
        variants.setdefault(ident,set())
        if href:variants[ident].add(urljoin(ORIG,href))
        for v in vals:variants[ident].add(urljoin(ORIG,v))
    # include responsive variants from every breakpoint by matching prefix against genuine desktop identities
    for im in soup.find_all('img'):
        par=im.find_parent('a',href=True);href=(par.get('href') or '') if par else ''
        vals=[(im.get(a) or '').strip() for a in ('data-muse-src','data-orig-src','data-src','src')]
        vals=[v for v in vals if v and 'richards_castle' in v.lower() and 'blank.gif' not in v.lower()]
        identity=None
        if 'richards_castle' in href.lower():identity=stem(href)
        if identity not in positions:
            for v in vals:
                st=stem(v)
                for e in sorted(positions,key=len,reverse=True):
                    if st==e or (st.startswith(e) and re.fullmatch(r'\d{2,4}x\d{2,4}',st[len(e):])):
                        identity=e;break
                if identity in positions:break
        if identity in positions:
            if href:variants[identity].add(urljoin(ORIG,href))
            for v in vals:variants[identity].add(urljoin(ORIG,v))
    local_stems={p.stem.lower() for p in IMG.iterdir() if p.is_file()}
    def present(e):return e in local_stems or any(s.startswith(e) and re.fullmatch(r'\d{2,4}x\d{2,4}',s[len(e):]) for s in local_stems)
    missing=[e for e in positions if not present(e)]
    print('Targeted missing identities:',missing)
    for ident in missing:
        cand=list(variants.get(ident,set()))
        # add plausible native forms and wildcard discovery
        for ext in ('.jpg','.png','.jpeg'):
            for host in ('http://www.castlesfortsbattles.co.uk','http://castlesfortsbattles.co.uk','https://www.castlesfortsbattles.co.uk'):
                for d in ('midlands/images','midlands/assets'):
                    u=f'{host}/{d}/{ident}{ext}'
                    if u not in cand:cand.append(u)
        rows=[]
        for u in cand[:25]:rows.extend(cdx(u))
        rows.extend(cdx(f'http://www.castlesfortsbattles.co.uk/midlands/images/{ident}*'))
        rows.extend(cdx(f'https://www.castlesfortsbattles.co.uk/midlands/images/{ident}*'))
        uniq={(r.get('timestamp'),r.get('original')):r for r in rows if r.get('timestamp') and r.get('original')}
        rows=list(uniq.values());rows.sort(key=lambda r:int(r.get('length') or 0),reverse=True)
        attempts=[]
        for r in rows[:35]:attempts.append((r['timestamp'],r['original'],'cdx'))
        for u in cand[:20]:
            for ts in ('20220826203519','20220826203520','20220826204300','20220826204800','20200728180812'):
                attempts.append((ts,u,'timestamp-probe'))
        best=None
        for ts,u,method in attempts[:100]:
            r=get(f'https://web.archive.org/web/{ts}id_/{u}',10)
            if not image_ok(r):continue
            try:wh=dims_bytes(r.content)
            except Exception:continue
            st=stem(u);exact=(st==ident);rank=(1 if exact else 0,wh[0]*wh[1],len(r.content))
            if best is None or rank>best[0]:best=(rank,ts,u,method,r.content,wh,st)
        if not best:
            print('UNRECOVERED',ident);continue
        _,ts,u,method,b,wh,st=best
        ext=os.path.splitext(urlsplit(u).path)[1].lower()
        if ext not in ('.jpg','.jpeg','.png','.gif','.webp'):ext='.jpg'
        dest=IMG/(ident+ext);dest.write_bytes(b)
        print('RECOVERED',ident,wh,ts,u,'source_variant',st,method)

if __name__=='__main__':main()
