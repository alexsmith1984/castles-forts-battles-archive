#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, re, shutil, time
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path('recovered/richards-castle'); SRC=ROOT/'source.html'; REP=ROOT/'recovery-report.json'; IMG=ROOT/'images'; PAGE=ROOT/'index.html'
ORIG='http://www.castlesfortsbattles.co.uk/midlands/richards_castle.html'
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 Richard Castle archive final verification'

def get(u,timeout=30,tries=2):
    last=None
    for i in range(tries):
        try:
            r=S.get(u,timeout=timeout,allow_redirects=True)
            if r.status_code==200:return r
            last=r
        except Exception as e:last=e
        time.sleep(1+i)
    return last

def okimg(r):
    if not hasattr(r,'status_code') or r.status_code!=200:return False
    b=r.content; ct=(r.headers.get('content-type') or '').lower()
    return len(b)>150 and ('image/' in ct or b[:2]==b'\xff\xd8' or b[:8]==b'\x89PNG\r\n\x1a\n' or b[:6] in (b'GIF87a',b'GIF89a'))

def info(p):
    with Image.open(p) as im:return [im.width,im.height]

def basename(u):return os.path.basename(urlsplit(u).path)
def stem(u):return os.path.splitext(basename(u))[0].lower()

def cdx(q):
    api='https://web.archive.org/cdx/search/cdx?url='+quote(q,safe=':/_*')+'&output=json&fl=timestamp,original,mimetype,length&filter=statuscode:200&limit=500&collapse=digest'
    r=get(api,45,2)
    if not hasattr(r,'status_code') or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    if not isinstance(d,list) or len(d)<2:return []
    return [dict(zip(d[0],x)) for x in d[1:] if len(x)==len(d[0])]

def main():
    soup=BeautifulSoup(SRC.read_text(encoding='utf-8'),'html.parser')
    desktop=soup.find(id='bp_infinity') or soup
    expected=[]; expected_meta={}
    for im in desktop.find_all('img'):
        vals=[]
        for a in ('data-muse-src','data-orig-src','data-src','src'):
            v=(im.get(a) or '').strip()
            if v and 'richards_castle' in v.lower() and 'blank.gif' not in v.lower():vals.append(v)
        par=im.find_parent('a',href=True)
        href=(par.get('href') or '') if par else ''
        if 'richards_castle' not in href.lower() and not vals:continue
        identity=stem(href) if 'richards_castle' in href.lower() else stem(vals[0])
        if identity not in expected:
            expected.append(identity)
            nxt=''
            anchor=par or im
            for sib in anchor.find_all_next(['p'],limit=4):
                t=' '.join(sib.stripped_strings).strip()
                if t:
                    nxt=t;break
            expected_meta[identity]={'desktop_href':urljoin(ORIG,href) if href else None,'desktop_src':urljoin(ORIG,vals[0]) if vals else None,'associated_original_text':nxt}
    # Collect every responsive/source variant and map it only to known desktop identities.
    def match_identity(s):
        s=s.lower()
        if s in expected:return s
        for e in sorted(expected,key=len,reverse=True):
            if s.startswith(e):
                tail=s[len(e):]
                if re.fullmatch(r'\d{2,4}x\d{2,4}',tail):return e
        return None
    refs={e:[] for e in expected}
    for im in soup.find_all('img'):
        vals=[]
        par=im.find_parent('a',href=True)
        if par and 'richards_castle' in (par.get('href') or '').lower():vals.append(par['href'])
        for a in ('data-muse-src','data-orig-src','data-src','src'):
            v=(im.get(a) or '').strip()
            if v and 'richards_castle' in v.lower() and 'blank.gif' not in v.lower():vals.append(v)
        for v in vals:
            u=urljoin(ORIG,v); e=match_identity(stem(u))
            if e and u not in refs[e]:refs[e].append(u)

    old=json.loads(REP.read_text(encoding='utf-8'))
    # Map existing verified local objects to actual desktop image identities.
    recovered={}
    provenance=[]
    for item in old.get('images',[]):
        f=item.get('recovered_file') or item.get('file'); logical=(item.get('logical') or stem(item.get('archive_original',''))).lower()
        e=match_identity(logical)
        if not e or not f:continue
        p=ROOT/f
        if not p.exists():continue
        try:dims=info(p)
        except Exception:continue
        entry={'identity':e,'file':f,'dimensions':dims,'archive_original':item.get('archive_original'),'archive_timestamp':item.get('archive_timestamp'),'method':'initial-wayback-recovery','source_variant':logical}
        # Prefer exact native identity over resized variants, then larger pixel area.
        rank=(1 if logical==e else 0,dims[0]*dims[1])
        if e not in recovered or rank>recovered[e][0]:recovered[e]=(rank,entry)

    # Deep Wayback pass only for genuine desktop positions still absent.
    for e in expected:
        if e in recovered:continue
        candidates=list(refs[e])
        meta=expected_meta[e]
        for u in (meta.get('desktop_href'),meta.get('desktop_src')):
            if u and u not in candidates:candidates.insert(0,u)
        ext=os.path.splitext(basename(meta.get('desktop_src') or meta.get('desktop_href') or 'x.jpg'))[1] or '.jpg'
        native=f'{e}{ext}'
        for u in [f'http://www.castlesfortsbattles.co.uk/midlands/images/{native}',f'http://www.castlesfortsbattles.co.uk/midlands/assets/{native}',f'http://castlesfortsbattles.co.uk/midlands/images/{native}',f'https://www.castlesfortsbattles.co.uk/midlands/images/{native}']:
            if u not in candidates:candidates.append(u)
        rows=[]
        for u in candidates:
            rows += cdx(u)
        for patt in [f'http://www.castlesfortsbattles.co.uk/*/{e}*',f'http://www.castlesfortsbattles.co.uk/midlands/images/{e}*',f'https://www.castlesfortsbattles.co.uk/midlands/images/{e}*']:
            rows += cdx(patt)
        uniq={}
        for r in rows:
            k=(r.get('timestamp'),r.get('original'));uniq[k]=r
        rows=list(uniq.values())
        rows.sort(key=lambda r:int(r.get('length') or 0),reverse=True)
        best=None
        for r in rows[:80]:
            if match_identity(stem(r.get('original','')))!=e:continue
            rr=get(f"https://web.archive.org/web/{r['timestamp']}id_/{r['original']}",30,2)
            if not okimg(rr):continue
            tmp=IMG/f'.candidate-{e}-{hashlib.sha1((r["timestamp"]+r["original"]).encode()).hexdigest()[:8]}.img'
            tmp.write_bytes(rr.content)
            try:dims=info(tmp)
            except Exception:
                tmp.unlink(missing_ok=True);continue
            rank=(1 if stem(r['original'])==e else 0,dims[0]*dims[1],len(rr.content))
            if best is None or rank>best[0]:
                if best:best[4].unlink(missing_ok=True)
                best=(rank,r,rr,dims,tmp)
            else:tmp.unlink(missing_ok=True)
        if best:
            rank,r,rr,dims,tmp=best
            ext=os.path.splitext(basename(r['original']))[1].lower()
            if ext not in ('.jpg','.jpeg','.png','.gif','.webp'):ext='.jpg'
            dest=IMG/f'{e}{ext}';shutil.move(tmp,dest)
            recovered[e]=(rank,{'identity':e,'file':'images/'+dest.name,'dimensions':dims,'archive_original':r['original'],'archive_timestamp':r['timestamp'],'method':'deep-wayback-cdx-recovery','source_variant':stem(r['original'])})

    # Normalize lower-resolution filenames to the true desktop identity for stable local paths.
    for e,(rank,item) in list(recovered.items()):
        p=ROOT/item['file']; native_ext=p.suffix.lower(); dest=IMG/f'{e}{native_ext}'
        if p!=dest and not dest.exists():shutil.copy2(p,dest);item['file']='images/'+dest.name
        variant=item.get('source_variant') or e
        dims=item['dimensions']
        resized=variant!=e
        item['quality']='thumbnail/lower-resolution' if resized or max(dims)<400 else 'full/near-full'
        item['associated_original_text']=expected_meta[e].get('associated_original_text','')
        provenance.append(item)

    missing=[{'identity':e,'candidate_urls':refs[e],'associated_original_text':expected_meta[e].get('associated_original_text','')} for e in expected if e not in recovered]
    full=sum(x['quality']=='full/near-full' for x in provenance); low=sum(x['quality']=='thumbnail/lower-resolution' for x in provenance)
    report={
      'name':"Richard's Castle",'original_url':ORIG,'supplied_captures':['20220826203519','20200728180812'],
      'best_source_capture':old.get('best_source_capture','20220826203519'),'usable_html_captures_examined':old.get('usable_html_captures_examined',[]),
      'original_image_positions_identified':len(expected),'desktop_image_identities':expected,
      'recovered_full_or_near_full':full,'recovered_thumbnail_or_lower_resolution':low,'still_missing':len(missing),
      'uncertain_identifications':[],'images':provenance,'missing':missing,
      'counting_method':'Unique Richard’s Castle content-image identities in the desktop bp_infinity source; responsive resize duplicates are not counted as separate original positions.',
      'verification_note':'All reported recovered files were opened successfully with Pillow; no unrelated substitute photographs were used.'}
    REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

    # Replace generated figures with one deterministic gallery containing each verified original position once.
    ps=BeautifulSoup(PAGE.read_text(encoding='utf-8'),'html.parser'); article=ps.find('article') or ps.body
    for f in article.find_all('figure'):f.decompose()
    h=ps.new_tag('h2');h.string='Recovered original photographs, plans and images';article.append(h)
    for e in expected:
        if e not in recovered:continue
        item=recovered[e][1];fig=ps.new_tag('figure');im=ps.new_tag('img',src=item['file'],alt=e.replace('_',' '));fig.append(im)
        cap=ps.new_tag('figcaption');assoc=expected_meta[e].get('associated_original_text','');cap.string=assoc if assoc and len(assoc)<350 else e.replace('_',' ');fig.append(cap);article.append(fig)
    PAGE.write_text(str(ps),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('images','missing')},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
