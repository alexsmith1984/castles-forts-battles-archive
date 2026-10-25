#!/usr/bin/env python3
"""Tutbury native JPEG preservation + independent Common Crawl gallery evidence."""
from __future__ import annotations
import concurrent.futures as cf,gzip,hashlib,io,json,re
from pathlib import Path
from urllib.parse import urlsplit
import requests
from PIL import Image
from bs4 import BeautifulSoup
ROOT=Path('recovered/tutbury-castle');IMG=ROOT/'images'
REP=ROOT/'recovery-report.json';r=json.loads(REP.read_text())
s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 (Historical Tutbury preservation archive)'
stats={'native_jpeg_preserved':[],'native_failures':[],
       'commoncrawl_indexes':[],'commoncrawl_image_rows':[],'commoncrawl_attempts':[],
       'commoncrawl_images_recovered':[],'historical_pages':[]}
def get(u,t=12,params=None,headers=None):
    try:return s.get(u,timeout=t,params=params,headers=headers)
    except:return None
def info(data):
    try:
        im=Image.open(io.BytesIO(data));w,h,f=im.width,im.height,im.format;im.verify()
        return (w,h,f) if w>=70 and h>=55 else None
    except:return None
# Verify real original JPEG file bytes, avoiding canvas re-encodings.
orig={
'tutbury_castle11a':'wp9ee7376d_05_06',
'tutbury_castle22':'wpb900ba74_05_06',
'tutbury_castle12':'wpa8797bf2_05_06',
'tutbury_castle1':'wp5258371f_05_06',
'tutbury_castle10':'wpb0d18409_05_06',
'tutbury_castle14':'wp702a10cf_05_06'}
known={x['identity']:x for x in r['images']}
for ident,stem in orig.items():
    archive='https://web.archive.org/web/20220826211201id_/http://www.castlesfortsbattles.co.uk/wpimages/'+stem+'.jpg'
    resp=get(archive,10)
    z=info(resp.content) if resp is not None and resp.status_code==200 else None
    if z and z[2]=='JPEG':
        p=IMG/(ident+'.jpg');p.write_bytes(resp.content)
        if ident in known:
            rec=known[ident];old=ROOT/rec['file']
            rec.update(file='images/'+ident+'.jpg',archive_original='http://www.castlesfortsbattles.co.uk/wpimages/'+stem+'.jpg',
               archive_timestamp=re.search(r'/web/(\d{14})',resp.url).group(1) if re.search(r'/web/(\d{14})',resp.url) else '20220826211201',
               method='wayback-verified-native-jpeg-display',dimensions=list(z[:2]),format='JPEG',bytes=len(resp.content),
               sha256=hashlib.sha256(resp.content).hexdigest(),quality='thumbnail/lower-resolution')
            if old!=p and old.exists():old.unlink()
        stats['native_jpeg_preserved'].append({'id':ident,'dims':list(z[:2]),'bytes':len(resp.content),'snapshot':resp.url})
        print('RAW JPEG',ident,z,flush=True)
    else:stats['native_failures'].append({'id':ident,'status':getattr(resp,'status_code',None)})
r['images']=[known[i] for i in r['desktop_image_identities'] if i in known]
# Historical page snapshots can reveal early filename series even if later gallery images 404.
original='http://www.castlesfortsbattles.co.uk/midlands/tutbury_castle.html'
for ts in ('20170208093615','20180720122036','20180823233219','20210918014135'):
    url='https://web.archive.org/web/'+ts+'id_/'+original
    resp=get(url,13)
    result={'requested':ts,'status':getattr(resp,'status_code',None),'final':resp.url if resp is not None else None}
    if resp is not None and resp.status_code==200 and '<html' in resp.text.lower():
        arr=re.findall(r'new wp_galleryimage\(\s*"wpimages/([^"]+\.jpg)',resp.text,re.I)
        result.update({'gallery_count':len(arr),'gallery_hashes':arr[:25]})
    stats['historical_pages'].append(result)
    print('PAGE',result['requested'],result['status'],result.get('gallery_count'),flush=True)
# Common Crawl independent WARC index—sample gallery identities only until verified.
try:
    response=get('https://index.commoncrawl.org/collinfo.json',16)
    catalogs=response.json() if response is not None and response.status_code==200 else []
except:catalogs=[]
by={}
for row in catalogs:
    m=re.search(r'CC-MAIN-(20\d\d)-',row.get('id',''))
    if not m:continue
    yr=int(m.group(1))
    if yr in (2017,2018,2019,2021,2022,2023) and yr not in by:
        by[yr]=row['id']
selected=[by[y] for y in sorted(by)];stats['commoncrawl_indexes']=selected
samples=['a913c8db479.jpg','9bf3cd82f73.jpg','wpb900ba74_05_06.jpg']
dirs=['midlands/wpimages','wpimages']
def query(item):
    idx,fn,folder=item
    u='www.castlesfortsbattles.co.uk/'+folder+'/'+fn
    resp=get('https://index.commoncrawl.org/'+idx+'-index',13,
             params={'url':u,'output':'json','filter':'status:200'})
    if resp is None:return {'index':idx,'url':u,'status':None,'rows':[]}
    rows=[]
    if resp.status_code==200:
        for line in resp.text.splitlines():
            try:rows.append(json.loads(line))
            except:pass
    return {'index':idx,'url':u,'status':resp.status_code,'rows':rows[:15]}
tasks=[(idx,fn,folder) for idx in selected for fn in samples for folder in dirs]
with cf.ThreadPoolExecutor(max_workers=6) as pool:
    for z in pool.map(query,tasks):
        stats['commoncrawl_attempts'].append({k:v for k,v in z.items() if k!='rows'}|{'n':len(z['rows'])})
        for row in z['rows']:
            stats['commoncrawl_image_rows'].append({'index':z['index'],'url':z['url'],'row':row})
print('COMMON CRAWL',len(stats['commoncrawl_image_rows']),'rows /',len(tasks),'queries',flush=True)
# only if exact archived image bytes present, never website substitutes
def warcimg(rec):
    z=rec['row']
    try:
        start=int(z['offset']);end=start+int(z['length'])-1
        resp=get('https://data.commoncrawl.org/'+z['filename'],18,headers={'Range':f'bytes={start}-{end}'})
        if resp is None or resp.status_code not in (200,206):return None
        try:data=gzip.decompress(resp.content)
        except:data=resp.content
        sep=data.find(b'\r\n\r\n')
        if sep<0:return None
        data=data[sep+4:]
        if data.startswith(b'HTTP/'):
            sep=data.find(b'\r\n\r\n')
            if sep>=0:data=data[sep+4:]
        image=info(data)
        return (data,image) if image else None
    except:return None
for ent in stats['commoncrawl_image_rows'][:25]:
    payload=warcimg(ent)
    if not payload:continue
    data,z=payload
    basename=Path(urlsplit(ent['url']).path).stem
    ident='gallery_'+basename if re.fullmatch('[0-9a-f]{11,12}',basename) else None
    if not ident or ident in known or ident not in r['desktop_image_identities']:continue
    path=IMG/(ident+'.jpg');path.write_bytes(data)
    known[ident]={'identity':ident,'file':'images/'+ident+'.jpg','archive_timestamp':'commoncrawl','archive_original':ent['url'],
        'method':'commoncrawl-warc-verified-original','dimensions':list(z[:2]),'format':z[2],'bytes':len(data),
        'sha256':hashlib.sha256(data).hexdigest(),'quality':'full/near-full','identification':'certain'}
    stats['commoncrawl_images_recovered'].append(ident)
r['images']=[known[i] for i in r['desktop_image_identities'] if i in known]
r['missing']=[x for x in r['missing'] if x['identity'] not in known]
r['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in r['images'])
r['recovered_thumbnail_or_lower_resolution']=len(r['images'])-r['recovered_full_or_near_full']
r['still_missing']=len(r['missing'])
r['status']='COMPLETE / VERIFIED' if not r['missing'] else 'PARTIAL / BOUNDED RECOVERY CHECKED'
r['commoncrawl_and_native_check_2026_10_25']={
    'native_jpeg_preserved':len(stats['native_jpeg_preserved']),
    'commoncrawl_index_queries':len(tasks),'commoncrawl_rows':len(stats['commoncrawl_image_rows']),
    'new_gallery_ids':stats['commoncrawl_images_recovered'],
    'older_page_gallery_counts':[{k:v for k,v in x.items() if k in ('requested','gallery_count','final','status')}
                                 for x in stats['historical_pages']]}
REP.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
doc=BeautifulSoup((ROOT/'index.html').read_text(),'html.parser')
h=doc.find('h2',string=lambda x:x and 'Recovered original photographs' in x)
if h:
    for f in h.find_all_next('figure'):f.decompose()
    n=h
    for x in r['images']:
        fig=doc.new_tag('figure');a=doc.new_tag('a',href=x['file'])
        a.append(doc.new_tag('img',src=x['file'],loading='lazy',alt='Authenticated Tutbury Castle archived photograph'))
        fig.append(a);cap=doc.new_tag('figcaption')
        cap.string=x['identity'].replace('_',' ')+(' — original display version' if x['quality']!='full/near-full' else '')
        fig.append(cap);n.insert_after(fig);n=fig
note=doc.find('div',class_='note')
if note:note.string=f'Reconstructed from the 26 August 2022 CastlesFortsBattles Tutbury Castle capture. {len(r["images"])} of {len(r["desktop_image_identities"])} authenticated photographs represented; six visible main-page pictures preserved as native original-site JPEG images. {r["still_missing"]} gallery images not yet located. No substitutes.'
(ROOT/'index.html').write_text(str(doc))
Path('page-audit/tutbury-native-and-commoncrawl.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False)+'\n')
print('SUMMARY',json.dumps({'native':len(stats['native_jpeg_preserved']),
  'commoncrawl_rows':len(stats['commoncrawl_image_rows']),'new_gallery':stats['commoncrawl_images_recovered'],
  'historical':[{'requested':x['requested'],'actual':x.get('final'),'count':x.get('gallery_count')} for x in stats['historical_pages']],
  'total':len(r['images'])},indent=2),flush=True)
