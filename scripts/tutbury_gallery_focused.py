#!/usr/bin/env python3
"""Focused WebPlus gallery historical recovery; no unrelated images."""
import concurrent.futures as cf,hashlib,html as H,io,json,re,time
from urllib.parse import urljoin,urlsplit,urlunsplit
from pathlib import Path
import requests
from PIL import Image
from bs4 import BeautifulSoup
ROOT=Path('recovered/tutbury-castle');IMG=ROOT/'images';IMG.mkdir(exist_ok=True)
REP=ROOT/'recovery-report.json';r=json.loads(REP.read_text())
raw=(ROOT/'source.html').read_text()
stems=[Path(x).stem for x in re.findall(r'new wp_galleryimage\(\s*"wpimages/([^"]+\.jpg)',raw,re.I)]
assert len(stems)==18,len(stems)
old={x['identity']:x for x in r['images']}
stats={'samples':[],'successful_patterns':[],'full_attempts':0,'found_now':[],'sample_count':0,'errors':[]}
ss=requests.Session();ss.headers['User-Agent']='Mozilla/5.0 (Tutbury WebPlus gallery recovery)'
def imginfo(b):
    try:
        im=Image.open(io.BytesIO(b));w,h,f=im.width,im.height,im.format;im.verify()
        return (w,h,f) if w>=60 and h>=50 else None
    except:return None
def fetch(ts,dir,stem,mode='im_',suffix=''):
    # dir key controls original url; do not trust archive nearest response if it rewrites another image identity
    filename=stem+suffix+'.jpg'
    u=('http://www.castlesfortsbattles.co.uk'+(':80' if ':80' in dir else '')+
        ('/midlands/wpimages/' if 'midlands' in dir else '/wpimages/')+filename)
    url='https://web.archive.org/web/'+ts+mode+'/'+u
    try:
        z=ss.get(url,timeout=12)
        info=imginfo(z.content) if z.status_code==200 else None
        return {'status':z.status_code,'url':url,'final_url':z.url,'mime':z.headers.get('content-type',''),
            'size':len(z.content),'dims':list(info[:2]) if info else None,
            'bytes':z.content if info else None,'stem':stem,'timestamp':ts,'directory':dir,'suffix':suffix}
    except Exception as e:
        return {'status':'error','error':str(e)[:80],'url':url,'stem':stem,'timestamp':ts,'directory':dir,'suffix':suffix}
def save(x,method):
    ident='gallery_'+x['stem']
    if ident in old and old[ident]['quality']=='full/near-full':return False
    data=x['bytes'];z=imginfo(data)
    if not z:return False
    ext='.png' if z[2]=='PNG' else '.jpg'
    (IMG/(ident+ext)).write_bytes(data)
    old[ident]={'identity':ident,'file':'images/'+ident+ext,
       'archive_timestamp':x['timestamp'],'archive_original':x['final_url'],
       'method':method,'dimensions':list(z[:2]),'format':z[2],'bytes':len(data),
       'sha256':hashlib.sha256(data).hexdigest(),
       'quality':'thumbnail/lower-resolution' if x['suffix']=='t' else 'full/near-full','identification':'certain'}
    stats['found_now'].append(ident)
    print('GALLERY RECOVERED',ident,z,x['final_url'],flush=True)
    return True
# Historically, original assets at /midlands/wpimages with :80, unlike standalones at root /wpimages.
patterns=[
    ('20220826211201','midlands','im_',''),
    ('20220826211201',':80_midlands','im_',''),
    ('20220826211201','root','im_',''),
    ('20220826211201',':80_root','im_',''),
    ('20210918014135','midlands','im_',''),
    ('20210918014135',':80_midlands','im_',''),
    ('20210918014135','root','im_',''),
    ('20180720122036',':80_midlands','id_',''),
    ('20180823233219',':80_midlands','id_',''),
    ('20180720122036','midlands','id_',''),
    ('20180823233219','midlands','id_',''),
    ('20220826211201','midlands','id_','t'),
    ('20220826211201','root','im_','t')
]
# Diagnostics: only two sample images, 13 patterns each; then expand any pattern yielding an original file.
for st in stems[:2]:
    for ts,dr,mode,suffix in patterns:
        result=fetch(ts,dr,st,mode,suffix);stats['sample_count']+=1
        stats['samples'].append({k:v for k,v in result.items() if k!='bytes'})
        if result.get('bytes'):
            save(result,'historical-gallery-sample')
            pat=(ts,dr,mode,suffix)
            if pat not in stats['successful_patterns']:stats['successful_patterns'].append(pat)
    print('SAMPLE DONE',st,flush=True)
# If sample works, apply that pattern to all remaining gallery image families; otherwise try exact-date alternatives on 4 more sample identities.
if not stats['successful_patterns']:
    alternatives=[
     ('20220826203844','midlands','im_',''),
     ('20220826203844','root','im_',''),
     ('20220826203844',':80_midlands','im_',''),
     ('20220826203844',':80_root','im_',''),
     ('20220826203844','midlands','id_','t'),
     ('20180720122036',':80_root','id_',''),
     ('20180823233219',':80_root','id_','')
    ]
    for st in stems[:4]:
        for ts,dr,mode,suffix in alternatives:
            z=fetch(ts,dr,st,mode,suffix);stats['sample_count']+=1
            stats['samples'].append({k:v for k,v in z.items() if k!='bytes'})
            if z.get('bytes'):
                save(z,'historical-gallery-alternative')
                pat=(ts,dr,mode,suffix)
                if pat not in stats['successful_patterns']:stats['successful_patterns'].append(pat)
if stats['successful_patterns']:
    patterns=stats['successful_patterns']
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futs=[pool.submit(fetch,ts,dr,st,mode,suffix) for st in stems for ts,dr,mode,suffix in patterns
             if 'gallery_'+st not in old]
        stats['full_attempts']=len(futs)
        for f in cf.as_completed(futs):
            try:z=f.result()
            except:continue
            if z.get('bytes'):save(z,'historical-gallery-pattern')
            else:stats['errors'].append({k:z.get(k) for k in ('status','url','mime')})
# Serialize outcome and preserve all 2022 user-visible writing.
order=r['desktop_image_identities'];images=[old[i] for i in order if i in old]
r['images']=images;r['missing']=[x for x in r['missing'] if x['identity'] not in old]
r['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in images)
r['recovered_thumbnail_or_lower_resolution']=len(images)-r['recovered_full_or_near_full']
r['still_missing']=len(r['missing'])
r['status']='COMPLETE / VERIFIED' if not r['missing'] else 'PARTIAL / HISTORICAL GALLERY CHECKED'
r['historical_gallery_focus_2026_10_25']={'found_now':stats['found_now'],'samples_checked':stats['sample_count'],
    'working_url_patterns':stats['successful_patterns'],'full_attempts':stats['full_attempts']}
REP.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
doc=BeautifulSoup((ROOT/'index.html').read_text(),'html.parser')
h=doc.find('h2',string=lambda x:x and 'Recovered original photographs' in x)
if h:
    for f in h.find_all_next('figure'):f.decompose()
    p=h
    for x in images:
        fig=doc.new_tag('figure');a=doc.new_tag('a',href=x['file'])
        a.append(doc.new_tag('img',src=x['file'],loading='lazy',alt='Original Tutbury Castle site photograph'))
        fig.append(a);cap=doc.new_tag('figcaption')
        cap.string=x['identity'].replace('_',' ')+( ' — lower-resolution original' if x['quality']!='full/near-full' else '')
        fig.append(cap);p.insert_after(fig);p=fig
note=doc.find('div',class_='note')
if note:
    note.string=f'Reconstructed from the archived Tutbury Castle page, captured 26 August 2022. {len(images)} of {len(order)} original content-image positions recovered ({r["recovered_full_or_near_full"]} full/near-full; {r["recovered_thumbnail_or_lower_resolution"]} lower-resolution). {r["still_missing"]} missing; no substitutes.'
(ROOT/'index.html').write_text(str(doc))
Path('page-audit/tutbury-gallery-focused.json').write_text(json.dumps({k:v for k,v in stats.items() if k!='errors'} | {'errors':stats['errors'][:40]},indent=2)+'\n')
print('FOCUSED RESULT',json.dumps({'patterns':stats['successful_patterns'],'new':stats['found_now'],'total':len(images),'missing':r['still_missing'],'sample_count':stats['sample_count']},indent=2),flush=True)
