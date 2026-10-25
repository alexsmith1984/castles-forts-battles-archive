#!/usr/bin/env python3
"""Independent Arquivo.pt image-index lookup for the 18 verified Tutbury gallery filenames."""
import hashlib,io,json,re
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image
from bs4 import BeautifulSoup
ROOT=Path('recovered/tutbury-castle');REP=ROOT/'recovery-report.json';IMG=ROOT/'images'
r=json.loads(REP.read_text());old={x['identity']:x for x in r['images']}
names={x['identity']:x for x in r['missing']}
result={'queries':[],'results_total':0,'filename_matches':0,'recovered':[],'api_errors':[],'sample_links':[]}
s=requests.Session();s.headers['User-Agent']='Mozilla/5.0 (Tutbury documented image source recovery)'
def get(url,params=None):
    try:return s.get(url,params=params,timeout=18)
    except:return None
def good(b):
    try:
        im=Image.open(io.BytesIO(b));w,h,f=im.width,im.height,im.format;im.verify()
        return (w,h,f) if w>=70 and h>=55 else None
    except:return None
queries=['Tutbury Castle','Tutbury_Castle','a913c8db479','9bf3cd82f73']
items=[];used=set()
for q in queries:
    params={'q':q,'siteSearch':'castlesfortsbattles.co.uk',
            'maxItems':'200','from':'2014','to':'2025','safeSearch':'off',
            'prettyPrint':'false','more':'imgSrc,imgTimestamp,pageURL,imgLinkToArchive,imgWidth,imgHeight,imgMimeType'}
    resp=get('https://arquivo.pt/imagesearch',params)
    row={'query':q,'status':getattr(resp,'status_code',None)}
    if resp is not None and resp.status_code==200:
        try:
            data=resp.json();batch=data.get('responseItems',[])
            row['count']=len(batch);items+=batch
        except Exception as e:row['json_error']=str(e)[:140]
    result['queries'].append(row)
    print('ARQUIVO IMAGE INDEX',row,flush=True)
result['results_total']=len(items)
for item in items:
    img=item.get('imgSrc') or item.get('imageUrl') or item.get('url') or ''
    found=None
    for ident in names:
        filename=ident.replace('gallery_','')
        if re.search(r'(?<![a-z0-9])'+re.escape(filename)+r't?\.jpe?g',img,re.I):
            found=ident;break
    if not found:continue
    result['filename_matches']+=1
    uris=[item.get(k) for k in ('imgLinkToArchive','imgLink','imgSrc') if item.get(k)]
    ts=str(item.get('imgTimestamp') or item.get('timestamp') or '')
    if ts and img:uris += ['https://arquivo.pt/wayback/'+ts+'id_/'+img]
    result['sample_links'].append({'identity':found,'src':img,'timestamp':ts,'links':uris[:3]})
    if found in old:continue
    for u in uris:
        if u in used:continue
        used.add(u);resp=get(u)
        z=good(resp.content) if resp is not None and resp.status_code==200 else None
        if not z:continue
        p=IMG/(found+('.png' if z[2]=='PNG' else '.jpg'));p.write_bytes(resp.content)
        old[found]={'identity':found,'file':'images/'+p.name,'archive_timestamp':ts,
           'archive_original':img,'method':'arquivo-independent-image-index',
           'dimensions':list(z[:2]),'format':z[2],'bytes':len(resp.content),
           'sha256':hashlib.sha256(resp.content).hexdigest(),
           'quality':'full/near-full' if not re.search(r't\.jpe?g$',img,re.I) else 'thumbnail/lower-resolution',
           'identification':'certain'}
        result['recovered'].append(found)
        print('ARQUIVO RECOVERED',found,z,flush=True)
        break
order=r['desktop_image_identities']
r['images']=[old[i] for i in order if i in old]
r['missing']=[x for x in r['missing'] if x['identity'] not in old]
r['still_missing']=len(r['missing'])
r['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in r['images'])
r['recovered_thumbnail_or_lower_resolution']=len(r['images'])-r['recovered_full_or_near_full']
r['status']='COMPLETE / VERIFIED' if not r['missing'] else 'PARTIAL / SOURCE-VERIFIED'
r['arquivo_image_index_audit_2026_10_25']={k:v for k,v in result.items() if k!='sample_links'}
REP.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
doc=BeautifulSoup((ROOT/'index.html').read_text(),'html.parser')
h=doc.find('h2',string=lambda x:x and 'Recovered original photographs' in x)
if h:
    for f in h.find_all_next('figure'):f.decompose()
    node=h
    for x in r['images']:
        f=doc.new_tag('figure');a=doc.new_tag('a',href=x['file'])
        a.append(doc.new_tag('img',src=x['file'],loading='lazy',alt='Tutbury Castle original archived photograph'))
        f.append(a);t=doc.new_tag('figcaption');t.string=x['identity'].replace('_',' ')
        f.append(t);node.insert_after(f);node=f
note=doc.find('div',class_='note')
if note:note.string=f'Tutbury Castle original page, 26 August 2022. {len(r["images"])} of {len(order)} original images reconstructed, including all six main-page original JPEGs. {r["still_missing"]} slideshow photographs remain unmatched. No outside photographs substituted.'
(ROOT/'index.html').write_text(str(doc))
Path('page-audit/tutbury-arquivo-index.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print('ARQUIVO RESULT',json.dumps({k:v for k,v in result.items() if k!='sample_links'},indent=2),flush=True)
