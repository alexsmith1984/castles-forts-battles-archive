#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image

ROOT=Path('recovered/pontefract-castle')
REP=ROOT/'recovery-report.json'
SRC=ROOT/'source.html'
IMG=ROOT/'images'; IMG.mkdir(exist_ok=True)
PAGES=[
 'http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'https://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'http://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'https://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
]
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 PontefractExactGalleryArrayRetry'

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

def gallery_hashes(html):
    # Isolate the WebPlus pg_4 image-array declaration itself. This deliberately
    # ignores navigation graphics, gallery controls and thumbnail-only references.
    blocks=[]
    patterns=[
      r'wp_imgArray_pg_4\s*=\s*\[(.*?)\]\s*;',
      r'wp_imgArray_pg_4\s*=\s*new\s+Array\s*\((.*?)\)\s*;',
    ]
    for pat in patterns:
        blocks += re.findall(pat,html,re.I|re.S)
    if not blocks:
        p=html.find('wp_imgArray_pg_4')
        if p>=0:
            # WebPlus pages normally declare nImgNum_pg_4 immediately after the array.
            q=html.find('nImgNum_pg_4',p)
            if q<0:q=min(len(html),p+12000)
            blocks=[html[p:q]]
    out=[]
    for block in blocks:
        for hh in re.findall(r'wpimages/([0-9a-f]{12})\.jpg',block,re.I):
            if hh not in out:out.append(hh)
    return out

def save(identity,b,source,ts,u,quality,method):
    z=info(b); ext='.png' if z[2]=='PNG' else '.jpg'; p=IMG/(identity+ext); p.write_bytes(b)
    return {'identity':identity,'file':'images/'+p.name,'archive_timestamp':ts,'archive_original':u,
      'method':source+'-'+method,'dimensions':[z[0],z[1]],'format':z[2],'bytes':len(b),
      'sha256':hashlib.sha256(b).hexdigest(),'quality':quality,'identification':'certain'}

r=json.loads(REP.read_text())
order=r['desktop_image_identities']
gids=[x for x in order if x.startswith('gallery_')]
expected=[x.replace('gallery_','') for x in gids]
current=gallery_hashes(SRC.read_text(errors='replace'))
print(json.dumps({'current_array_hashes':current,'expected_hashes':expected,'parser_valid':current[:len(expected)]==expected},indent=2),flush=True)
if current[:len(expected)]!=expected:
    raise SystemExit('ABORT: exact pg_4 parser did not reproduce the known current Pontefract gallery order')

existing={x['identity']:x for x in r.get('images',[])}
missing_gallery=[g for g in gids if g not in existing]
caps=[]
for p in PAGES:
    caps += timemap('wayback',p)
    caps += timemap('arquivo',p)
seen=set(); caps=[x for x in caps if x not in seen and not seen.add(x)]
caps.sort(key=lambda x:x[1])
if len(caps)>40:
    idx={0,len(caps)-1}
    for n in range(1,39): idx.add(round(n*(len(caps)-1)/39))
    caps=[caps[i] for i in sorted(idx)]

checked=0; arrays_seen=[]; distinct=[]
for source,ts,pageurl in caps:
    if not missing_gallery:break
    pr=page(source,ts,pageurl)
    if not pr or pr.status_code!=200 or '<html' not in pr.text.lower():continue
    checked+=1
    hashes=gallery_hashes(pr.text)
    if hashes:
        rec={'source':source,'timestamp':ts,'count':len(hashes),'hashes':hashes[:len(gids)]}
        arrays_seen.append(rec)
        key=tuple(hashes[:len(gids)])
        if key not in [tuple(x) for x in distinct]:distinct.append(list(key))
        print('ARRAY',source,ts,len(hashes),hashes[:len(gids)],flush=True)
    if len(hashes)<len(gids):continue
    for pos,identity in enumerate(gids):
        if identity in existing:continue
        hh=hashes[pos]
        candidates=[]
        bases=[
          pageurl,
          'http://www.castlesfortsbattles.co.uk/',
          'https://www.castlesfortsbattles.co.uk/',
          'http://www.castlesfortsbattles.co.uk/yorkshire/',
          'https://www.castlesfortsbattles.co.uk/yorkshire/',
          'http://castlesfortsbattles.co.uk/',
          'https://castlesfortsbattles.co.uk/',
        ]
        for base in bases:
            candidates += [(urljoin(base,'wpimages/'+hh+'.jpg'),'full/near-full'),(urljoin(base,'wpimages/'+hh+'t.jpg'),'thumbnail/lower-resolution')]
        best=None
        for u,q in dict.fromkeys(candidates):
            b=replay(source,ts,u)
            if not b:continue
            z=info(b); score=(2 if q=='full/near-full' else 1,z[0]*z[1])
            if best is None or score>best[0]:best=(score,b,u,q)
        if best:
            _,b,u,q=best
            existing[identity]=save(identity,b,source,ts,u,q,'validated-historical-gallery-position')
            print('RECOVERED',identity,source,ts,u,info(b),q,flush=True)
    missing_gallery=[g for g in gids if g not in existing]

old={x['identity']:x for x in r.get('missing',[])}
r['images']=[existing[i] for i in order if i in existing]
r['missing']=[old[i] for i in order if i not in existing and i in old]
r['recovered_full_or_near_full']=sum(x.get('quality')=='full/near-full' for x in r['images'])
r['recovered_thumbnail_or_lower_resolution']=sum(x.get('quality')!='full/near-full' for x in r['images'])
r['still_missing']=len(order)-len(r['images']); r['status']='COMPLETE' if r['still_missing']==0 else 'PARTIAL'
r['validated_gallery_array_retry_2026_09_15']={
  'completed':True,'parser_validated_against_current_source':True,
  'current_array_hashes':current[:len(gids)],'captures_found':len(caps),'captures_checked':checked,
  'captures_with_valid_gallery_array':len(arrays_seen),'distinct_gallery_sequences_seen':distinct,
  'arrays_seen':arrays_seen,'recovered':[g for g in gids if g in existing]
}
REP.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'checked':checked,'arrays_seen':len(arrays_seen),'distinct_sequences':len(distinct),'full':r['recovered_full_or_near_full'],'lower':r['recovered_thumbnail_or_lower_resolution'],'missing':r['still_missing'],'remaining':[x['identity'] for x in r['missing']]},indent=2))
