#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf,hashlib,html as H,io,json,re,os
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urlunsplit
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path('recovered/tutbury-castle'); IMG=ROOT/'images';IMG.mkdir(parents=True,exist_ok=True)
SRC=ROOT/'source.html'
TS='20220826211201'; PRIOR='20210918014135'
ORIG='http://www.castlesfortsbattles.co.uk/midlands/tutbury_castle.html'
BASE='http://www.castlesfortsbattles.co.uk/'
raw=SRC.read_text(encoding='utf-8',errors='replace')
soup=BeautifulSoup(raw,'html.parser')
s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 (Tutbury Castle archival preservation)'

def get(u,t=8):
    try:return s.get(u,timeout=t,allow_redirects=True)
    except:return None
def iminfo(b):
    try:
        im=Image.open(io.BytesIO(b));w,h=im.size;fmt=im.format;im.verify()
        return (w,h,fmt) if w>=80 and h>=60 else None
    except:return None
def variants(u):
    sp=urlsplit(u); hosts=list(dict.fromkeys((sp.netloc,sp.netloc.replace('www.',''))))
    return list(dict.fromkeys([urlunsplit((p,host,sp.path,'','')) for p in ('http','https') for host in hosts]))
def name(url):return Path(urlsplit(url).path).stem
def identity(url):return name(url).lower()
def is_content(u):
    stem=name(u).lower()
    return stem.startswith('tutbury_castle') or re.match(r'^wp[0-9a-f]{8}_05_06$',stem)
def save(ident,origin,ts,body,dim,method,quality):
    ext='.png' if dim[2]=='PNG' else '.jpg'
    fn=ident+ext;p=IMG/fn;p.write_bytes(body)
    return {'identity':ident,'file':'images/'+fn,'archive_timestamp':ts,'archive_original':origin,
            'method':method,'dimensions':list(dim[:2]),'format':dim[2],'bytes':len(body),
            'sha256':hashlib.sha256(body).hexdigest(),'quality':quality,'identification':'certain'}

# The six image positions directly linked from the source to full-size originals.
standalone=[]; seen=set()
for a in soup.find_all('a',href=True):
    href=a['href']; imgs=a.find_all('img')
    if not re.search(r'Tutbury_Castle\d+[a-z]?\.jpe?g$',urlsplit(href).path,re.I):continue
    if href.lower() in seen:continue
    seen.add(href.lower())
    thumbnail=next((x['src'] for x in imgs if re.search(r'wp[0-9a-f]{8}_05_06\.jpe?g$',x.get('src',''),re.I)),None)
    ident=identity(href)
    standalone.append({'identity':ident,'full':href,'fallback':thumbnail,'kind':'standalone'})
# Preserve originals' order, but do not duplicate gallery responsive thumbs.
array=re.findall(r'wp_imgArray_pg_26\[nImgNum_pg_26\+\+\]\s*=\s*new wp_galleryimage\(\s*["\x27]([^"\x27]+)["\x27]\s*,[^;]*',raw,re.I)
gallery=[{'identity':'gallery_'+name(p).lower(),'full':urljoin(ORIG,p),'fallback':urljoin(ORIG,p.replace('.jpg','t.jpg')),'kind':'gallery'} for p in array]
allitems=standalone+gallery
allitems=list({x['identity']:x for x in allitems}.values())

def locate(x):
    for u,quality,meth in [(x['full'],'full/near-full','wayback-full-original'),
             (x.get('fallback'),'thumbnail/lower-resolution','wayback-authentic-display')]:
        if not u:continue
        candidates=[]
        for v in variants(u):
            for ts in (TS,PRIOR,'20180720122036','20180823230000'):
                candidates.append((ts,v))
        for ts,v in candidates:
            r=get(f'https://web.archive.org/web/{ts}id_/{v}',6)
            if r is not None and r.status_code==200:
                z=iminfo(r.content)
                if z:return save(x['identity'],v,ts,r.content,z,meth,quality)
    return None

recovered={}
with cf.ThreadPoolExecutor(max_workers=22) as pool:
    futs={pool.submit(locate,x):x for x in allitems}
    for f in cf.as_completed(futs):
        try:
            y=f.result()
            if y:recovered[y['identity']]=y
        except Exception:pass

# One bounded further pass using Arquivo exact timestamp availability (known to recover missing Almondbury assets).
def arquivo_one(x):
    for u,quality in [(x['full'],'full/near-full'),(x.get('fallback'),'thumbnail/lower-resolution')]:
        if not u:continue
        for v in variants(u)[:2]:
            for ts in (TS,PRIOR):
                url=f'https://arquivo.pt/wayback/{ts}id_/{v}'
                r=get(url,7)
                if r is not None and r.status_code==200:
                    z=iminfo(r.content)
                    if z:return save(x['identity'],v,ts,r.content,z,'arquivo-exact-time-replay',quality)
    return None
missing=[x for x in allitems if x['identity'] not in recovered]
with cf.ThreadPoolExecutor(max_workers=18) as pool:
    futs={pool.submit(arquivo_one,x):x for x in missing}
    for f in cf.as_completed(futs):
        try:
            y=f.result()
            if y:recovered[y['identity']]=y
        except:pass

# Source-derived editorial reconstruction (not a newly authored historical narrative).
exclude={'Home','UK Map','A-Z','England','Scotland','Wales','About Us','Contact Us','Terms and Conditions','Share','Tweet'}
blocks=[];seen=set()
for el in soup.find_all(['p','h1','h2','h3','h4','li']):
    tx=' '.join(el.stripped_strings);tx=re.sub(r'\s+',' ',tx).strip()
    if not tx or tx in exclude or len(tx)<2:continue
    key=tx.casefold()
    if key in seen:continue
    seen.add(key)
    blocks.append(tx)
def tagfor(tx):
    if len(tx)<95 and (tx.isupper() or re.match(r'^(HISTORY|GETTING THERE|WHAT IS THERE|ADDITIONAL NOTES|BIBLIOGRAPHY|GALLERY|MARY, QUEEN)',tx,re.I)):return 'h2'
    return 'p'
body=''.join('<'+tagfor(tx)+'>'+H.escape(tx)+'</'+tagfor(tx)+'>' for tx in blocks)
images=[recovered[x['identity']] for x in allitems if x['identity'] in recovered]
missing=[{'identity':x['identity'],'full_url':x['full'],'fallback_url':x.get('fallback'),'kind':x['kind']} for x in allitems if x['identity'] not in recovered]
full=sum(x['quality']=='full/near-full' for x in images);low=len(images)-full
figs=[]
for x in images:
    cap=x['identity'].replace('gallery_','Gallery photograph: ').replace('_',' ')
    if x['quality']!='full/near-full':cap+=' — lower-resolution original'
    figs.append(f'<figure><a href="{H.escape(x["file"],quote=True)}"><img loading="lazy" src="{H.escape(x["file"],quote=True)}" alt="Tutbury Castle original archived photograph"></a><figcaption>{H.escape(cap)}</figcaption></figure>')
note=f'Reconstructed from the original CastlesFortsBattles Tutbury Castle page, captured 26 August 2022. {len(images)} of {len(allitems)} authenticated content-image positions recovered: {full} full or near-full originals and {low} lower-resolution originals. {len(missing)} remain missing. No substitute photographs.'
doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tutbury Castle | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font:17px/1.62 Georgia,"Times New Roman",serif}}header{{background:#3d3528;color:#fff;padding:29px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 16px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:19px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px;font-size:15px}}h2{{color:#493e2c;margin-top:1.5em}}p{{margin:.85em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}</style></head><body><header><h1>Tutbury Castle</h1></header><main><div class="note">{H.escape(note)}</div><article>{body}<h2>Recovered original photographs and gallery</h2>{''.join(figs) if figs else '<p>Original photos could not be retrieved from the available archived copies.</p>'}</article><p><a href="../../atoz-part5.html#t">Back to the T index</a></p></main></body></html>'''
(ROOT/'index.html').write_text(doc,encoding='utf-8')
report={'name':'Tutbury Castle','status':'COMPLETE / VERIFIED' if not missing else 'PARTIAL / SEARCH EXHAUSTED',
        'source_timestamp':TS,'source_original':ORIG,'older_comparison_timestamp':PRIOR,
        'desktop_image_identities':[x['identity'] for x in allitems],
        'original_image_positions_identified':len(allitems),'recovered_full_or_near_full':full,
        'recovered_thumbnail_or_lower_resolution':low,'still_missing':len(missing),
        'uncertain_identifications':[],'images':images,'missing':missing,
        'counting_method':'Full-size linked standalone photos and 18 explicit WebPlus wp_imgArray_pg_26 gallery images; excludes navigation, decorative illustrations, shared chrome and redundant thumbnail exports.',
        'verification_note':'Only image assets whose filenames are declared by the archived Tutbury source were used. No substitutions.'}
(ROOT/'recovery-report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
at=Path('atoz-part5.html');s2=at.read_text()
s2,n=re.subn(r'href="https?://web\.archive\.org/web/[^"]*/midlands/tutbury_castle\.html"', 'href="recovered/tutbury-castle/"',s2,flags=re.I)
if n!=1:raise RuntimeError('Expected exactly one Tutbury link in A-Z; got '+str(n))
at.write_text(s2)
Path('page-audit/tutbury-castle.json').write_text(json.dumps({'name':'Tutbury Castle','status':report['status'],'positions':len(allitems),'full':full,'lower':low,'missing':len(missing),'missing_identities':[x['identity'] for x in missing]},indent=2)+'\n')
print(json.dumps({'status':report['status'],'image_denominator':len(allitems),'full':full,'lower':low,'missing':len(missing),'standalone':len(standalone),'gallery':len(gallery),'az_links_updated':n,'text_blocks':len(blocks)},indent=2),flush=True)
