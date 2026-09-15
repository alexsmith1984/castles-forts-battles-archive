#!/usr/bin/env python3
# Trigger validated Pontefract recovery after workflow_run installation.
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image

ROOT=Path('recovered/pontefract-castle'); REP=ROOT/'recovery-report.json'; SRC=ROOT/'source.html'; IMG=ROOT/'images'; IMG.mkdir(exist_ok=True)
PAGES=['http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html','https://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html','http://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html','https://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html']
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 PontefractValidatedArrayRetry'

def get(u,t=12):
    r=None
    for n in range(4):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception:r=None
        time.sleep(.8*(n+1))
    return r

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify(); return z
    except Exception:return None

def hashes(html):
    pat=r'wp_imgArray_pg_4\s*\[\s*nImgNum_pg_4\+\+\s*\]\s*=\s*new\s+wp_galleryimage\s*\(\s*["\']wpimages/([0-9a-f]{10,14})\.jpg'
    return re.findall(pat,html,re.I)

def timemap(source,u):
    ep=('https://web.archive.org/web/timemap/link/'+u if source=='wayback' else 'https://arquivo.pt/wayback/timemap/link/'+u); marker='/web/' if source=='wayback' else '/wayback/'
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

def page(source,ts,u):
    return get(('https://web.archive.org/web/'+ts+'id_/'+u) if source=='wayback' else ('https://arquivo.pt/wayback/'+ts+'id_/'+u),12)

def replay(source,ts,u):
    eps=(['https://web.archive.org/web/'+ts+m+'/'+u for m in ('id_','im_')] if source=='wayback' else ['https://arquivo.pt/wayback/'+ts+'id_/'+u])
    for ep in eps:
        r=get(ep,8)
        if r and r.status_code==200 and info(r.content):return r.content

def save(i,b,source,ts,u,q):
    z=info(b); ext='.png' if z[2]=='PNG' else '.jpg'; p=IMG/(i+ext); p.write_bytes(b)
    return {'identity':i,'file':'images/'+p.name,'archive_timestamp':ts,'archive_original':u,'method':source+'-validated-historical-gallery-position','dimensions':[z[0],z[1]],'format':z[2],'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'quality':q,'identification':'certain'}

r=json.loads(REP.read_text()); order=r['desktop_image_identities']; gids=[x for x in order if x.startswith('gallery_')]; expected=[x[8:] for x in gids]
current=hashes(SRC.read_text(errors='replace'))
print(json.dumps({'current_array_hashes':current,'expected':expected,'parser_valid':current==expected},indent=2),flush=True)
if current!=expected: raise SystemExit('ABORT: Pontefract pg_4 assignment parser failed current-source validation')
existing={x['identity']:x for x in r.get('images',[])}
caps=[]
for u in PAGES:
    caps+=timemap('wayback',u); caps+=timemap('arquivo',u)
seen=set(); caps=[x for x in caps if x not in seen and not seen.add(x)]; caps.sort(key=lambda x:x[1])
if len(caps)>40:
    idx={0,len(caps)-1}; [idx.add(round(n*(len(caps)-1)/39)) for n in range(1,39)]; caps=[caps[i] for i in sorted(idx)]
checked=0; arrays=[]; distinct=[]
for source,ts,pageurl in caps:
    pr=page(source,ts,pageurl)
    if not pr or pr.status_code!=200 or '<html' not in pr.text.lower():continue
    checked+=1; hs=hashes(pr.text)
    if hs:
        arrays.append({'source':source,'timestamp':ts,'count':len(hs),'hashes':hs})
        if hs not in distinct:distinct.append(hs)
        print('ARRAY',source,ts,len(hs),hs,flush=True)
    if len(hs)<len(gids):continue
    for pos,i in enumerate(gids):
        if i in existing:continue
        hh=hs[pos]; best=None
        bases=[pageurl,'http://www.castlesfortsbattles.co.uk/','https://www.castlesfortsbattles.co.uk/','http://www.castlesfortsbattles.co.uk/yorkshire/','https://www.castlesfortsbattles.co.uk/yorkshire/','http://castlesfortsbattles.co.uk/','https://castlesfortsbattles.co.uk/']
        for base in bases:
            for leaf,q in [(hh+'.jpg','full/near-full'),(hh+'t.jpg','thumbnail/lower-resolution')]:
                u=urljoin(base,'wpimages/'+leaf); b=replay(source,ts,u)
                if not b:continue
                z=info(b); score=(2 if q=='full/near-full' else 1,z[0]*z[1])
                if best is None or score>best[0]:best=(score,b,u,q)
        if best:
            _,b,u,q=best; existing[i]=save(i,b,source,ts,u,q); print('RECOVERED',i,source,ts,u,info(b),q,flush=True)
old={x['identity']:x for x in r.get('missing',[])}
r['images']=[existing[i] for i in order if i in existing]; r['missing']=[old[i] for i in order if i not in existing and i in old]
r['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in r['images']); r['recovered_thumbnail_or_lower_resolution']=sum(x['quality']!='full/near-full' for x in r['images']); r['still_missing']=len(order)-len(r['images']); r['status']='COMPLETE' if not r['still_missing'] else 'PARTIAL'
r['validated_gallery_array_retry_v2_2026_09_15']={'completed':True,'parser_validated_against_current_source':True,'captures_found':len(caps),'captures_checked':checked,'captures_with_valid_gallery_array':len(arrays),'distinct_gallery_sequences_seen':distinct,'arrays_seen':arrays,'recovered':[i for i in gids if i in existing]}
REP.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'checked':checked,'arrays':len(arrays),'distinct_sequences':len(distinct),'full':r['recovered_full_or_near_full'],'lower':r['recovered_thumbnail_or_lower_resolution'],'missing':r['still_missing'],'remaining':[x['identity'] for x in r['missing']]},indent=2))
