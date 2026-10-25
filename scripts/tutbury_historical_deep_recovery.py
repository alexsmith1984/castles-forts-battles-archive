#!/usr/bin/env python3
"""Tutbury authentic-image deep recovery; preserves 2022 article and existing image files."""
from __future__ import annotations
import concurrent.futures as cf,hashlib,html as H,io,json,os,re,time,gzip
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,urljoin
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path('recovered/tutbury-castle'); IMG=ROOT/'images'; IMG.mkdir(parents=True,exist_ok=True)
REP=ROOT/'recovery-report.json'; SOURCE=ROOT/'source.html'
BASE='http://www.castlesfortsbattles.co.uk/'
ORIG=BASE+'midlands/tutbury_castle.html'
TSS=['20180720122036','20180823233219','20180823230000','20180901000000','20210918014135','20220826211201']
DEADLINE=time.monotonic()+375
s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 (Tutbury historic-image forensic recovery)'
report=json.loads(REP.read_text())
seen={x['identity']:x for x in report['images']}
target={x['identity']:x for x in report['missing']}
for x in report['images']:
    if x['quality']!='full/near-full':
        target[x['identity']]={'identity':x['identity'],'full_url':x['archive_original'],'fallback_url':None,
                               'kind':'standalone','upgrade_only':True}
# Supply the actual full-size target from the original 2022 report for existing display derivatives.
for x in report['images']:
    if x['identity'].startswith('tutbury_castle'):
        n=x['identity'].replace('tutbury_castle','')
        base=next((p for p in ('JPG','jpg') if n in ('1','12','22') or p=='jpg'),'jpg')
        target[x['identity']]['full_url']=BASE+'Tutbury_Castle'+n+'.'+base
orig_missing=[x['identity'] for x in report['missing']]
stats={'image_positions':len(report['desktop_image_identities']),'initial_recovered':len(seen),
       'direct_replay_attempts':0,'wayback_cdx_rows':0,'wayback_cdx_errors':0,
       'arquivo_timemap_rows':0,'arquivo_timemap_errors':0,
       'historical_page_rows':0,'historical_page_reads':0,
       'historic_gallery_position_matches':0,'commoncrawl_rows':0,'result':[]}

def alive():return time.monotonic()<DEADLINE
def get(u,t=7,params=None,headers=None):
    if not alive():return None
    try:
        return s.get(u,timeout=min(t,max(1,DEADLINE-time.monotonic())),
                     params=params,headers=headers,allow_redirects=True)
    except:return None
def valid(b):
    try:
        im=Image.open(io.BytesIO(b));w,h,fmt=im.width,im.height,im.format;im.verify()
        return (w,h,fmt) if w>=70 and h>=55 else None
    except:return None
def urlvariants(u):
    p=urlsplit(u)
    # WebPlus relative-gallery originals may be stored at /midlands/wpimages,
    # /wpimages, with :80, and at both scheme/hostname variants.
    paths=[p.path]
    if '/midlands/wpimages/' in p.path:
        paths.append(p.path.replace('/midlands/wpimages/','/wpimages/'))
    elif '/wpimages/' in p.path:
        paths.append(p.path.replace('/wpimages/','/midlands/wpimages/'))
    if '/midlands/assets/' in p.path:paths.append(p.path.replace('/midlands/assets/','/assets/'))
    hosts=['www.castlesfortsbattles.co.uk','www.castlesfortsbattles.co.uk:80','castlesfortsbattles.co.uk']
    return list(dict.fromkeys(urlunsplit((sc,h,pt,'','')) for pt in paths for h in hosts for sc in ('http','https')))
def ident_from_url(u):
    basename=Path(urlsplit(u).path).stem.lower()
    if re.match(r'^(?:[0-9a-f]{11,12})t?$',basename):
        return 'gallery_'+basename.rstrip('t')
    if re.match(r'^tutbury_castle\d+[a-z]?$',basename):return basename
    return None
def save(ident,data,url,ts,method,quality):
    z=valid(data)
    if not z:return None
    ext='.png' if z[2]=='PNG' else '.jpg'
    fn=ident+ext
    (IMG/fn).write_bytes(data)
    return {'identity':ident,'file':'images/'+fn,'archive_timestamp':ts,'archive_original':url,
            'method':method,'dimensions':[z[0],z[1]],'format':z[2],
            'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'quality':quality,'identification':'certain'}
def replay(ident,ts,u,quality,method,host='wayback'):
    prefix='https://web.archive.org/web/' if host=='wayback' else 'https://arquivo.pt/wayback/'
    for mode in ('id_','im_') if host=='wayback' else ('id_',):
        r=get(prefix+ts+mode+'/'+u,6)
        if r is not None and r.status_code==200 and valid(r.content):
            return save(ident,r.content,u,ts,method,quality)
    return None
def choose(ident,record):
    old=seen.get(ident)
    if old is None or (old['quality']!='full/near-full' and record['quality']=='full/near-full') or \
       (old['quality']==record['quality'] and (old['dimensions'][0]*old['dimensions'][1])<(record['dimensions'][0]*record['dimensions'][1])):
        seen[ident]=record
        print('RECOVERED/UPGRADED',ident,record['dimensions'],record['method'],record['archive_timestamp'],flush=True)

# Broad dates plus correct 80-port and both WebPlus image directories.
jobs=[]
for ident,x in target.items():
    for is_full,field in ((True,'full_url'),(False,'fallback_url')):
        u=x.get(field)
        if not u:continue
        for v in urlvariants(u):
            # Optimize: gallery tries 2018 then 2022; standalone tries 2022 then 2018.
            stamps=(['20220826211201','20210918014135','20180720122036'] if ident.startswith('tutbury_') else
                    ['20180720122036','20220826211201','20210918014135'])
            for ts in stamps:
                jobs.append((ident,ts,v,
                             'full/near-full' if is_full else 'thumbnail/lower-resolution','historic-direct-replay'))
# Bound repeated cheap attempts to 12 per identity per class, plus 4 port-specific ones.
by={}
for job in jobs:
    ident,ts,u,q,_=job;by.setdefault((ident,q),[]).append(job)
jobs=[]
for key,arr in by.items():
    # prioritize original middle directory, :80 and current Wayback captures
    preferred=sorted(arr,key=lambda a:(0 if ':80/' in a[2] else 1,
                                        0 if '/midlands/wpimages/' in a[2] else 1,
                                        0 if a[1]=='20180720122036' else 1))
    jobs+=list(dict.fromkeys(preferred))[:14]
stats['direct_replay_attempts']=len(jobs)
with cf.ThreadPoolExecutor(max_workers=28) as ex:
    futures={ex.submit(replay,*job):job for job in jobs}
    for f in cf.as_completed(futures):
        try:
            x=f.result()
            if x:choose(x['identity'],x)
        except Exception as e:pass
print('DIRECT',len(seen),flush=True)

# Compact CDX exact inventories for source filenames; try prefix for Tutbury root photographs.
queries=[]
for ident,x in target.items():
    if ident in seen and seen[ident]['quality']=='full/near-full':continue
    for field in ('full_url','fallback_url'):
        u=x.get(field)
        if not u:continue
        vv=urlvariants(u)
        # prioritize original and port version of each actual file
        qs=[v for v in vv if v.startswith('http://') and 'www.' in v and ('/midlands/wpimages/' in v or '/wpimages/' in v or ident.startswith('tutbury_'))]
        for v in qs[:3]:queries.append((ident,v,'exact'))
for pattern in ('www.castlesfortsbattles.co.uk/Tutbury_Castle*',
                'www.castlesfortsbattles.co.uk:80/Tutbury_Castle*',
                'www.castlesfortsbattles.co.uk/wpimages/*Tutbury*'):
    queries.append((None,pattern,'wildcard'))
queries=list(dict.fromkeys(queries))
def cdx(task):
    ident,u,mode=task
    r=get('https://web.archive.org/cdx/search/cdx',9,params={
       'url':u,'output':'json','filter':'statuscode:200',
       'fl':'timestamp,original,statuscode,mimetype,digest,length','collapse':'digest','limit':'90'})
    if r is None or r.status_code!=200:return [],False
    try:
        data=r.json();h=data[0]
        return [dict(zip(h,x)) for x in data[1:] if len(x)==len(h)],True
    except:return [],False
cdx_rows=[];cdx_failed=0
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    for rows,ok in ex.map(cdx,queries):
        cdx_rows.extend(rows)
        if not ok:cdx_failed+=1
stats['wayback_cdx_rows']=len(cdx_rows);stats['wayback_cdx_errors']=cdx_failed
print('CDX',len(cdx_rows),'errors',cdx_failed,flush=True)

# Replay best matching timestamp record before trying more targets.
matchjobs=[]
for row in cdx_rows:
    ident=ident_from_url(row.get('original',''))
    if not ident or ident not in target:continue
    origin=row['original'];ts=row['timestamp']
    quality='thumbnail/lower-resolution' if (Path(urlsplit(origin).path).stem.lower().endswith('t') or
        '_05_06' in origin.lower()) else 'full/near-full'
    matchjobs.append((ident,ts,origin,quality,'wayback-cdx-exact'))
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    futures=[ex.submit(replay,*v) for v in matchjobs[:260]]
    for f in cf.as_completed(futures):
        try:
            x=f.result()
            if x:choose(x['identity'],x)
        except:pass
print('CDX REPLAY',len(seen),flush=True)

# The crucial recovery method used successfully for Kenilworth: mine historical
# whole-page captures and identify gallery assets in their historic positions.
PAGE_VARIANTS=[ORIG,ORIG.replace('http://','https://'),
               ORIG.replace('www.',''),ORIG.replace('www.','').replace('http://','https://')]
hist=[]
for page in PAGE_VARIANTS:
    for base,marker in [('https://web.archive.org/web/timemap/link/','/web/'),
                        ('https://arquivo.pt/wayback/timemap/link/','/wayback/')]:
        r=get(base+page,13)
        if r is None or r.status_code!=200:continue
        for line in r.text.splitlines():
            if 'memento' not in line or '<' not in line:continue
            uri=line.split('<',1)[1].split('>',1)[0]
            try:
                tsandurl=uri.split(marker,1)[1];ts,original=tsandurl.split('/',1);ts=ts[:14]
                if re.fullmatch(r'\d{14}',ts) and original.startswith(('http://','https://')):
                    hist.append(('arquivo' if 'arquivo.pt' in base else 'wayback',ts,original))
            except:pass
        if len(hist)>300:break
# CDX index for exact page, if available.
for pg in PAGE_VARIANTS:
    rows,ok=cdx((None,pg,'exact'))
    for x in rows:
        if x.get('timestamp') and x.get('original'):
            hist.append(('wayback',x['timestamp'],x['original']))
hist=list(dict.fromkeys(hist));stats['historical_page_rows']=len(hist)
hist.sort(key=lambda x:x[1])
if len(hist)>32:
    idx={0,len(hist)-1}
    for n in range(1,31):idx.add(round(n*(len(hist)-1)/31))
    hist=[hist[i] for i in sorted(idx)]
# Seed known captures, and actual historic capture most likely containing WebPlus gallery archive.
for ts in ('20180720122036','20180823233219','20210918014135','20220826211201'):
    hist.append(('wayback',ts,ORIG))
hist=list(dict.fromkeys(hist))
nowraw=SOURCE.read_text()
nowarr=re.findall(r'new wp_galleryimage\(\s*["\']wpimages/([^"\']+\.jpg)',nowraw,re.I)
currenthash=[Path(a).stem.lower() for a in nowarr]
historical_candidates={}
readpages=0
for host,ts,page in hist:
    if not alive():break
    r=get(('https://arquivo.pt/wayback/' if host=='arquivo' else 'https://web.archive.org/web/')+ts+'id_/'+page,8)
    if r is None or r.status_code!=200 or '<html' not in r.text.lower():continue
    readpages+=1
    arr=re.findall(r'new wp_galleryimage\(\s*["\']wpimages/([^"\']+\.jpg)',r.text,re.I)
    hashes=[Path(a).stem.lower() for a in arr]
    overlap=len(set(currenthash).intersection(hashes))
    # Exact file matches always safe. Position mapping only when index is stable.
    stable= len(hashes)==len(currenthash) and overlap>=max(8,len(currenthash)//2)
    for i,oldname in enumerate(hashes):
        if i>=len(currenthash):break
        ident='gallery_'+oldname
        if ident not in target and stable:ident='gallery_'+currenthash[i]
        if ident not in target:continue
        if ident!='gallery_'+oldname and not stable:continue
        stats['historic_gallery_position_matches']+=1
        filename=arr[i]
        u=urljoin(page,'wpimages/'+filename)
        historical_candidates.setdefault(ident,[]).append((host,ts,u,'full/near-full','historical-gallery-source'))
        historical_candidates.setdefault(ident,[]).append((host,ts,u.replace('.jpg','t.jpg'),'thumbnail/lower-resolution','historical-gallery-thumbnail'))
    ps=BeautifulSoup(r.text,'html.parser')
    for a in ps.find_all('a',href=True):
        hn=ident_from_url(a['href'])
        if hn not in target:continue
        historical_candidates.setdefault(hn,[]).append((host,ts,urljoin(page,a['href']),'full/near-full','historical-page-standalone'))
        im=a.find('img',src=True)
        if im:
            historical_candidates.setdefault(hn,[]).append((host,ts,urljoin(page,im['src']),'thumbnail/lower-resolution','historical-page-display'))
stats['historical_page_reads']=readpages
print('HISTORICAL',stats['historical_page_rows'],'read',readpages,'candidate',sum(map(len,historical_candidates.values())),flush=True)

newjobs=[]
for ident,vals in historical_candidates.items():
    if ident in seen and seen[ident]['quality']=='full/near-full':continue
    for host,ts,u,q,m in vals:
        for uu in urlvariants(u):
            newjobs.append((ident,ts,uu,q,m,host))
# De-dupe per target, prefer full originals and :80 image path (Kenilworth).
jobs={}
for job in newjobs:
    ident,ts,u,q,m,host=job
    key=(ident,ts,u,host)
    jobs.setdefault(key,job)
jobs=sorted(jobs.values(),key=lambda j:(j[3]!='full/near-full',':80/' not in j[2],
                       '/midlands/wpimages/' not in j[2],j[1]))
jobs=jobs[:380]
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    futures=[ex.submit(replay,*job) for job in jobs]
    for f in cf.as_completed(futures):
        try:
            x=f.result()
            if x:choose(x['identity'],x)
        except:pass
print('HISTORY REPLAY',len(seen),flush=True)

# Arquivo per-image TimeMaps, using direct memento timestamp rather than nearest-time guessed replay.
def arquivoinventory(task):
    ident,u=task
    r=get('https://arquivo.pt/wayback/timemap/link/'+u,8)
    if r is None or r.status_code!=200:return [],False
    rows=[]
    for line in r.text.splitlines():
        if 'memento' not in line:continue
        match=re.search(r'/wayback/(\d{14})([^/]*)/(https?://[^>\s]+)',line)
        if match:rows.append((ident,match.group(1),match.group(3)))
    return rows,True
items=[]
for ident,x in target.items():
    if ident in seen and seen[ident]['quality']=='full/near-full':continue
    for field in ('full_url','fallback_url'):
        if x.get(field):
            vs=urlvariants(x[field])
            # highest value variants first; 1 regular and 1 :80 variant
            items.extend((ident,v) for v in vs if v.startswith('http://') and ('www.castlesfortsbattles.co.uk/' in v or ':80/' in v) and (ident.startswith('tutbury_') or '/midlands/wpimages/' in v))
items=list(dict.fromkeys(items))[:120]
arows=[]
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    for rows,ok in ex.map(arquivoinventory,items):
        if ok:arows+=rows
        else:stats['arquivo_timemap_errors']+=1
stats['arquivo_timemap_rows']=len(arows)
print('ARQUIVO',len(arows),'errors',stats['arquivo_timemap_errors'],flush=True)
arjobs=list(dict.fromkeys((ident,ts,u,
               'thumbnail/lower-resolution' if Path(urlsplit(u).path).stem.lower().endswith('t') or '_05_06' in u.lower() else 'full/near-full',
               'arquivo-timemap-discovered','arquivo') for ident,ts,u in arows))
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    futures=[ex.submit(replay,*job) for job in arjobs[:240]]
    for f in cf.as_completed(futures):
        try:
            x=f.result()
            if x:choose(x['identity'],x)
        except:pass

# Build the updated document without deleting any original text content.
bs=BeautifulSoup(nowraw,'html.parser')
skip={'Home','UK Map','A-Z','England','Scotland','Wales','About Us','Contact Us','Terms and Conditions','Share','Tweet'}
blocks=[];seentext=set()
for el in bs.find_all(['p','h1','h2','h3','h4','li']):
    tx=re.sub(r'\s+',' ',' '.join(el.stripped_strings)).strip()
    if not tx or tx in skip or len(tx)<2 or tx.casefold() in seentext:continue
    seentext.add(tx.casefold());blocks.append(tx)
def typ(tx):
    return 'h2' if len(tx)<95 and (tx.isupper() or re.match(r'^(HISTORY|GETTING THERE|WHAT IS THERE|ADDITIONAL NOTES|BIBLIOGRAPHY|GALLERY)',tx,re.I)) else 'p'
body=''.join('<'+typ(tx)+'>'+H.escape(tx)+'</'+typ(tx)+'>' for tx in blocks)
order=report['desktop_image_identities']
images=[seen[i] for i in order if i in seen]
missing=[x for x in report.get('missing',[]) if x['identity'] not in seen]
full=sum(x['quality']=='full/near-full' for x in images)
low=len(images)-full
figs=[]
for x in images:
    cap=x['identity'].replace('gallery_','Gallery photograph: ').replace('_',' ')
    if x['quality']!='full/near-full':cap+=' — lower-resolution archived original'
    rel=H.escape(x['file'],quote=True)
    figs.append(f'<figure><a href="{rel}"><img src="{rel}" loading="lazy" alt="Tutbury Castle authentic archived photograph"></a><figcaption>{H.escape(cap)}</figcaption></figure>')
note=f'Reconstructed from the archived CastlesFortsBattles Tutbury Castle page, captured 26 August 2022. {len(images)} of {len(order)} authenticated content-image positions represented: {full} full or near-full and {low} lower-resolution originals. {len(missing)} remain unlocated. No unrelated substitute photographs.'
doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tutbury Castle | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font:17px/1.62 Georgia,"Times New Roman",serif}}header{{background:#3d3528;color:#fff;padding:29px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 16px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:19px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px;font-size:15px}}h2{{color:#493e2c;margin-top:1.5em}}p{{margin:.85em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}</style></head><body><header><h1>Tutbury Castle</h1></header><main><div class="note">{H.escape(note)}</div><article>{body}<h2>Recovered original photographs and gallery</h2>{''.join(figs) if figs else '<p>Original photographs could not be retrieved from available archives.</p>'}</article><p><a href="../../atoz-part5.html#t">Back to the T index</a></p></main></body></html>'''
(ROOT/'index.html').write_text(doc)
report['images']=images;report['missing']=missing;report['still_missing']=len(missing)
report['recovered_full_or_near_full']=full
report['recovered_thumbnail_or_lower_resolution']=low
report['status']='COMPLETE / VERIFIED' if not missing else 'PARTIAL / FURTHER DEEP RECOVERY ATTEMPTED'
stats.update({'final_recovered':len(images),'final_full':full,'final_low':low,
              'final_missing':len(missing),'new_identities':[i for i in orig_missing if i in seen],
              'upgraded':[i for i in report['desktop_image_identities'] if i not in orig_missing and seen[i]['quality']=='full/near-full']})
report.setdefault('deep_recovery_history',[]).append({'date':'2026-10-25','methods':['WebPlus :80 /midlands/wpimages/ and root replay','Wayback exact/wildcard CDX','historic gallery-position continuity','Wayback+Arquivo TimeMaps','historic source full and display references'],'results':stats})
REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
Path('page-audit/tutbury-castle-deep-pass.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False)+'\n')
print('FINAL',json.dumps({k:stats[k] for k in ('initial_recovered','final_recovered','final_full','final_low','final_missing','new_identities','upgraded','historical_page_reads','wayback_cdx_rows','arquivo_timemap_rows')},ensure_ascii=False),flush=True)
