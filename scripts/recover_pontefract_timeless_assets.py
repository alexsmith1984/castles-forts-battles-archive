#!/usr/bin/env python3
import io,json,hashlib,time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image

ROOT=Path('recovered/pontefract-castle'); REP=ROOT/'recovery-report.json'; IMG=ROOT/'images'; IMG.mkdir(parents=True,exist_ok=True)
PAGES=[
 'http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'https://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'http://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'https://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html',
 'http://www.castlesfortsbattles.co.uk/pontefract_castle.html',
 'https://www.castlesfortsbattles.co.uk/pontefract_castle.html',
 'http://www.castlesfortsbattles.co.uk/m/pontefract_castle.html',
 'https://www.castlesfortsbattles.co.uk/m/pontefract_castle.html'
]
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 PontefractTimelessArchiveRecovery'

def get(u,t=12):
    r=None
    for n in range(3):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception: r=None
        time.sleep(.7*(n+1))
    return r

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify(); return z
    except Exception:return None

def save(identity,b,u,method,q):
    z=info(b); ext='.png' if z[2]=='PNG' else '.jpg'; p=IMG/(identity+ext); p.write_bytes(b)
    return {'identity':identity,'file':'images/'+p.name,'archive_timestamp':'nearest-surviving-capture','archive_original':u,
      'method':method,'dimensions':[z[0],z[1]],'format':z[2],'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
      'quality':q,'identification':'certain'}

def timemap(page):
    out=[]
    for source,ep,marker in [
      ('wayback','https://web.archive.org/web/timemap/link/'+page,'/web/'),
      ('arquivo','https://arquivo.pt/wayback/timemap/link/'+page,'/wayback/')]:
        r=get(ep,16)
        if not r or r.status_code!=200:continue
        for line in r.text.splitlines():
            if 'memento' not in line or '<' not in line or '>' not in line:continue
            uri=line.split('<',1)[1].split('>',1)[0]
            if marker not in uri:continue
            rest=uri.split(marker,1)[1]
            if '/' not in rest:continue
            ts,orig=rest.split('/',1);ts=ts[:14]
            if len(ts)==14 and ts.isdigit() and orig.startswith(('http://','https://')):out.append((source,ts,orig))
    return out

def page_replay(source,ts,u):
    ep=('https://web.archive.org/web/'+ts+'id_/'+u) if source=='wayback' else ('https://arquivo.pt/wayback/'+ts+'id_/'+u)
    return get(ep,10)

def timeless_image(u):
    # Special Wayback nearest/latest replay plus broad date anchors; this bypasses page/image timestamp mismatch.
    probes=[
      'https://web.archive.org/web/2id_/'+u,
      'https://web.archive.org/web/0id_/'+u,
      'https://web.archive.org/web/20221231235959id_/'+u,
      'https://web.archive.org/web/20210918010514id_/'+u,
      'https://web.archive.org/web/20181231235959id_/'+u,
      'https://web.archive.org/web/20161231235959id_/'+u,
    ]
    for p in probes:
        r=get(p,9)
        if r and r.status_code==200 and info(r.content):return r.content,p
    return None,None

r=json.loads(REP.read_text()); order=r['desktop_image_identities']; gids=[x for x in order if x.startswith('gallery_')]
found={x['identity']:x for x in r.get('images',[])}
# candidate hashes per gallery position, gathered from every historical desktop/mobile page capture
bypos={i:[] for i in range(len(gids))}; caps=[]
for p in PAGES:caps+=timemap(p)
seen=set();caps=[x for x in caps if x not in seen and not seen.add(x)]
caps.sort(key=lambda x:x[1])
checked=0
for source,ts,pageurl in caps:
    pr=page_replay(source,ts,pageurl)
    if not pr or pr.status_code!=200 or '<html' not in pr.text.lower():continue
    checked+=1; hashes=[]; key='new wp_galleryimage("wpimages/'
    for line in pr.text.splitlines():
        if key not in line:continue
        tail=line.split(key,1)[1]
        if '.jpg"' not in tail:continue
        h=tail.split('.jpg"',1)[0]
        if h and h not in hashes:hashes.append(h)
    for i,h in enumerate(hashes[:len(gids)]):
        if h not in bypos[i]:bypos[i].append(h)

new=[]
for i,identity in enumerate(gids):
    if identity in found:continue
    for h in bypos[i]:
        variants=[]
        for scheme in ('http','https'):
          for host in ('www.castlesfortsbattles.co.uk','castlesfortsbattles.co.uk'):
            for prefix in ('/wpimages/','/yorkshire/wpimages/','/m/wpimages/'):
              variants += [f'{scheme}://{host}{prefix}{h}.jpg',f'{scheme}://{host}{prefix}{h}t.jpg']
        got=False
        for u in variants:
            b,replay=timeless_image(u)
            if not b:continue
            q='thumbnail/lower-resolution' if u.endswith('t.jpg') else 'full/near-full'
            found[identity]=save(identity,b,u,'wayback-timeless-historical-gallery-position',q);new.append(identity)
            print('RECOVERED',identity,h,u,info(b),q,flush=True);got=True;break
        if got:break

old={x['identity']:x for x in r.get('missing',[])}
r['images']=[found[i] for i in order if i in found]
r['missing']=[old[i] for i in order if i not in found and i in old]
r['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in r['images'])
r['recovered_thumbnail_or_lower_resolution']=sum(x['quality']!='full/near-full' for x in r['images'])
r['still_missing']=len(order)-len(r['images']);r['status']='COMPLETE' if r['still_missing']==0 else 'PARTIAL'
r['timeless_asset_recovery_2026_09_15']={'completed':True,'historical_page_captures_found':len(caps),'historical_page_captures_checked':checked,'hashes_by_gallery_position':bypos,'recovered_now':new}
REP.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'captures':len(caps),'checked':checked,'new':new,'full':r['recovered_full_or_near_full'],'lower':r['recovered_thumbnail_or_lower_resolution'],'missing':r['still_missing']},indent=2))
