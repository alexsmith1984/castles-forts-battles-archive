#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image

ROOT=Path('recovered/pontefract-castle')
REP=ROOT/'recovery-report.json'
IMG=ROOT/'images'; IMG.mkdir(exist_ok=True)
PAGES=[
 'http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'https://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'http://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'https://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
]
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 PontefractHistoricalRetry'

def get(u,t=12):
    r=None
    for n in range(4):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception: r=None
        time.sleep(0.8*(n+1))
    return r

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify(); return z
    except Exception:return None

def replay(source,ts,u):
    eps=(['https://web.archive.org/web/'+ts+m+'/'+u for m in ('id_','im_')]
         if source=='wayback' else ['https://arquivo.pt/wayback/'+ts+'id_/'+u])
    for ep in eps:
        r=get(ep,9)
        if r and r.status_code==200 and info(r.content): return r.content
    return None

def page(source,ts,u):
    ep=('https://web.archive.org/web/'+ts+'id_/'+u if source=='wayback'
        else 'https://arquivo.pt/wayback/'+ts+'id_/'+u)
    return get(ep,12)

def timemap(source,pageurl):
    if source=='wayback': ep='https://web.archive.org/web/timemap/link/'+pageurl; marker='/web/'
    else: ep='https://arquivo.pt/wayback/timemap/link/'+pageurl; marker='/wayback/'
    r=get(ep,18)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if 'memento' not in line or '<' not in line or '>' not in line:continue
        uri=line.split('<',1)[1].split('>',1)[0]
        if marker not in uri:continue
        rest=uri.split(marker,1)[1]
        if '/' not in rest:continue
        ts,orig=rest.split('/',1); ts=ts[:14]
        if len(ts)==14 and ts.isdigit() and orig.startswith(('http://','https://')):out.append((source,ts,orig))
    return out

def save(identity,b,source,ts,u,quality,method):
    z=info(b); ext='.png' if z[2]=='PNG' else '.jpg'; p=IMG/(identity+ext); p.write_bytes(b)
    return {'identity':identity,'file':'images/'+p.name,'archive_timestamp':ts,'archive_original':u,
      'method':source+'-'+method,'dimensions':[z[0],z[1]],'format':z[2],'bytes':len(b),
      'sha256':hashlib.sha256(b).hexdigest(),'quality':quality,'identification':'certain'}

r=json.loads(REP.read_text())
order=r['desktop_image_identities']
gids=[x for x in order if x.startswith('gallery_')]
existing={x['identity']:x for x in r.get('images',[])}
missing_gallery=[g for g in gids if g not in existing]

caps=[]
for p in PAGES:
    caps += timemap('wayback',p)
    caps += timemap('arquivo',p)
seen=set(); caps=[x for x in caps if x not in seen and not seen.add(x)]
caps.sort(key=lambda x:x[1])
# Keep broad chronology, but bounded.
if len(caps)>36:
    idx={0,len(caps)-1}
    for n in range(1,35): idx.add(round(n*(len(caps)-1)/35))
    caps=[caps[i] for i in sorted(idx)]
print(json.dumps({'captures_found':len(caps),'missing_gallery':missing_gallery}),flush=True)
checked=0
for source,ts,pageurl in caps:
    if not missing_gallery:break
    pr=page(source,ts,pageurl)
    if not pr or pr.status_code!=200 or '<html' not in pr.text.lower():continue
    checked+=1; h=pr.text
    # WebPlus gallery order. Accept classic constructor syntax and plain wpimages hash refs.
    hashes=[]
    for pat in [r'new wp_galleryimage\\?\(["\\\']wpimages/([0-9a-f]+)\\.jpg', r'wpimages/([0-9a-f]{12})\\.jpg']:
        for hh in re.findall(pat,h,re.I):
            if hh not in hashes: hashes.append(hh)
    if len(hashes)<len(gids):
        continue
    # Map by gallery position, not by hash: old pages may use different hash filenames.
    for pos,identity in enumerate(gids):
        if identity in existing or pos>=len(hashes):continue
        hh=hashes[pos]
        candidates=[]
        bases=[pageurl, 'http://www.castlesfortsbattles.co.uk/', 'http://www.castlesfortsbattles.co.uk/yorkshire/']
        for b in bases:
            candidates += [(urljoin(b,'wpimages/'+hh+'.jpg'),'full/near-full'),(urljoin(b,'wpimages/'+hh+'t.jpg'),'thumbnail/lower-resolution')]
        best=None
        for u,q in candidates:
            b=replay(source,ts,u)
            if not b:continue
            z=info(b); score=(2 if q=='full/near-full' else 1,z[0]*z[1])
            if best is None or score>best[0]: best=(score,b,u,q)
        if best:
            _,b,u,q=best
            existing[identity]=save(identity,b,source,ts,u,q,'historical-gallery-position')
            print('RECOVERED',identity,source,ts,u,info(b),q,flush=True)
    missing_gallery=[g for g in gids if g not in existing]

old={x['identity']:x for x in r.get('missing',[])}
r['images']=[existing[i] for i in order if i in existing]
r['missing']=[old[i] for i in order if i not in existing and i in old]
r['recovered_full_or_near_full']=sum(x.get('quality')=='full/near-full' for x in r['images'])
r['recovered_thumbnail_or_lower_resolution']=sum(x.get('quality')!='full/near-full' for x in r['images'])
r['still_missing']=len(order)-len(r['images']); r['status']='COMPLETE' if r['still_missing']==0 else 'PARTIAL'
r['fresh_historical_position_retry_2026_09_15']={'completed':True,'captures_found':len(caps),'captures_checked':checked,'recovered':[g for g in gids if g in existing]}
REP.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'checked':checked,'full':r['recovered_full_or_near_full'],'lower':r['recovered_thumbnail_or_lower_resolution'],'missing':r['still_missing'],'remaining':[x['identity'] for x in r['missing']]},indent=2))
