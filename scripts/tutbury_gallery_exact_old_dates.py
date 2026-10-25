#!/usr/bin/env python3
"""Verify gallery files against exact, actually-existing 2017–2018 page captures."""
import concurrent.futures as cf,hashlib,io,json,re
from pathlib import Path
from urllib.parse import urlsplit
import requests
from PIL import Image
from bs4 import BeautifulSoup
root=Path('recovered/tutbury-castle');img=root/'images'
rep=json.loads((root/'recovery-report.json').read_text())
raw=(root/'source.html').read_text()
names=[Path(x).stem for x in re.findall(r'new wp_galleryimage\(\s*"wpimages/([^"]+\.jpg)',raw,re.I)]
assert len(names)==18
s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 (Tutbury actual historical capture verification)'
dates=['20171105011747','20180709030457','20180810002445','20220826203844']
folders=['midlands/wpimages','wpimages',':80/midlands/wpimages',':80/wpimages']
# Each exact archival location is tested only for the first two known source gallery identifiers.
results={'tested':[],'working_patterns':[],'recovered':[],'count_before':len(rep['images'])}
old={x['identity']:x for x in rep['images']}
def dim(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=70 and z[1]>=50 else None
    except:return None
def fetch(d,f,stem,thumbnail=False):
    folder=f.replace(':80/','')
    host='www.castlesfortsbattles.co.uk:80' if f.startswith(':80/') else 'www.castlesfortsbattles.co.uk'
    url='http://'+host+'/'+folder+'/'+stem+('t' if thumbnail else '')+'.jpg'
    arch='https://web.archive.org/web/'+d+'id_/'+url
    try:
        r=s.get(arch,timeout=10)
        z=dim(r.content) if r.status_code==200 else None
        return {'date':d,'folder':f,'stem':stem,'thumbnail':thumbnail,
                'http_status':r.status_code,'archive_final':r.url,'dims':list(z[:2]) if z else None,'payload':r.content if z else None}
    except Exception as e:return {'date':d,'folder':f,'stem':stem,'thumbnail':thumbnail,'error':str(e)[:110]}
def preserve(x):
    ident='gallery_'+x['stem']
    if ident in old or ident not in rep['desktop_image_identities']:return
    data=x['payload'];z=dim(data)
    if not z:return
    ext='.png' if z[2]=='PNG' else '.jpg'
    p=img/(ident+ext);p.write_bytes(data)
    old[ident]={'identity':ident,'file':'images/'+p.name,'archive_timestamp':x['date'],
       'archive_original':x['archive_final'],'method':'wayback-exact-historical-gallery',
       'dimensions':list(z[:2]),'format':z[2],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
       'quality':'thumbnail/lower-resolution' if x['thumbnail'] else 'full/near-full',
       'identification':'certain'}
    results['recovered'].append(ident)
    print('RECOVER',ident,z,x['archive_final'],flush=True)
for name in names[:2]:
    for date in dates:
        for folder in folders:
            for thumb in (False,True):
                z=fetch(date,folder,name,thumb)
                results['tested'].append({k:v for k,v in z.items() if k!='payload'})
                if z.get('payload'):
                    pattern=[date,folder,thumb]
                    if pattern not in results['working_patterns']:results['working_patterns'].append(pattern)
                    preserve(z)
    print('OLDER SAMPLE',name,flush=True)
# If any pattern succeeds, apply to all 18 identities, using no other patterns.
if results['working_patterns']:
    tasks=[(d,f,name,th) for name in names for d,f,th in results['working_patterns'] if 'gallery_'+name not in old]
    with cf.ThreadPoolExecutor(max_workers=5) as p:
        for z in p.map(lambda a:fetch(*a),tasks):
            if z.get('payload'):preserve(z)
            else:results['tested'].append({k:v for k,v in z.items() if k!='payload'})
rep['images']=[old[i] for i in rep['desktop_image_identities'] if i in old]
rep['missing']=[m for m in rep['missing'] if m['identity'] not in old]
rep['still_missing']=len(rep['missing'])
rep['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in rep['images'])
rep['recovered_thumbnail_or_lower_resolution']=len(rep['images'])-rep['recovered_full_or_near_full']
rep['status']='COMPLETE / VERIFIED' if not rep['missing'] else 'PARTIAL / HISTORIC DATE CHECKED'
rep['specific_historical_dates_2026_10_25']={'source_dates_tested':dates,
      'gallery_archive_matches':results['recovered'],'patterns':results['working_patterns'],
      'sample_tests':len(results['tested'])}
(root/'recovery-report.json').write_text(json.dumps(rep,indent=2,ensure_ascii=False)+'\n')
soup=BeautifulSoup((root/'index.html').read_text(),'html.parser')
h=soup.find('h2',string=lambda t:t and 'Recovered original photographs' in t)
if h:
    for f in h.find_all_next('figure'):f.decompose()
    p=h
    for x in rep['images']:
        fig=soup.new_tag('figure');a=soup.new_tag('a',href=x['file'])
        a.append(soup.new_tag('img',src=x['file'],loading='lazy',alt='Tutbury Castle original historical photograph'))
        fig.append(a);caption=soup.new_tag('figcaption')
        caption.string=x['identity'].replace('_',' ')+(' — original-site display quality' if x['quality']!='full/near-full' else '')
        fig.append(caption);p.insert_after(fig);p=fig
note=soup.find('div',class_='note')
if note:note.string=f'Tutbury Castle reconstructed from CastlesFortsBattles 26 August 2022 capture. {len(rep["images"])} of {len(rep["desktop_image_identities"])} authenticated content images preserved, including all six main-page photographs. {rep["still_missing"]} gallery images remain without a verified archive source. No unrelated substitutes.'
(root/'index.html').write_text(str(soup))
Path('page-audit/tutbury-gallery-actual-historical-dates.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
print('HISTORICAL RESULT',json.dumps({'samples':len(results['tested']),'status':{},
     'patterns':results['working_patterns'],'new':results['recovered'],
     'total':len(rep['images']),'missing':rep['still_missing']}),flush=True)
