#!/usr/bin/env python3
import json,re,time,os
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup

ORIG='http://www.castlesfortsbattles.co.uk/midlands/tutbury_castle.html'
TIMES=['20220826211201','20210918014135']
s=requests.Session()
s.headers['User-Agent']='Mozilla/5.0 (CastlesFortsBattles original-page archival preservation)'
def get(url,timeout=22):
    try:return s.get(url,timeout=timeout,allow_redirects=True)
    except Exception as e:return e
results=[]; selected=None
for ts in TIMES:
    for mode in ('id_',''):
      for orig in (ORIG,ORIG.replace('http://','https://'),ORIG.replace('www.','')):
        u=f'https://web.archive.org/web/{ts}{mode}/{orig}'
        r=get(u)
        if isinstance(r,Exception):
            results.append({'date':ts,'url':u,'error':repr(r)[:250]});continue
        good=r.status_code==200 and '<html' in r.text.lower() and ('tutbury' in r.text.lower()) and len(r.content)>1500
        results.append({'date':ts,'url':u,'status':r.status_code,'size':len(r.content),'good':good,'final_url':r.url})
        if good: selected=(ts,orig,r.text);break
      if selected:break
    if selected:break
if not selected:
    Path('page-audit').mkdir(exist_ok=True)
    Path('page-audit/tutbury-inspection.json').write_text(json.dumps({'status':'source-unavailable','attempts':results},indent=2))
    print(json.dumps({'status':'source-unavailable','attempts':results},indent=2));raise SystemExit(0)
ts,orig,raw=selected
root=Path('recovered/tutbury-castle');root.mkdir(parents=True,exist_ok=True)
(root/'source.html').write_text(raw,encoding='utf-8')
soup=BeautifulSoup(raw,'html.parser')
refs=[]
for tag in soup.find_all(['img','a','source','input']):
    for attr in ('src','href','data-orig-src','data-muse-src','data-src','data-hidpi-src','srcset','data-image','data-image-url'):
        v=tag.get(attr)
        if not v:continue
        for vv in ([v] if attr!='srcset' else [part.strip().split(' ')[0] for part in v.split(',')]):
            if re.search(r'\.(?:jpe?g|png|gif|webp)(?:\?|$)',vv,re.I):
                refs.append({'tag':tag.name,'attr':attr,'raw':vv,'url':urljoin(orig,vv)})
scripts=[]
for tag in soup.find_all('script'):
    tx=(tag.string or tag.get_text() or '')
    src=tag.get('src') or ''
    if re.search(r'(wp_imgArray|ImageInclude|images|gallery|thumbnail|lightbox|\.jpe?g)',tx+' '+src,re.I):
        scripts.append({'src':src,'excerpt':tx[:3000]})
textblocks=[]
for tag in soup.find_all(['h1','h2','h3','h4','p','li']):
    tx=' '.join(tag.stripped_strings)
    if tx:textblocks.append({'tag':tag.name,'text':tx[:500]})
audit={'status':'source-obtained','selected_timestamp':ts,'source_url':orig,'source_bytes':len(raw.encode('utf-8')),
       'title':soup.title.get_text(' ',strip=True) if soup.title else None,
       'attempts':results,'image_refs':refs,'image_ref_count':len(refs),
       'scripts':scripts,'text_blocks':textblocks,'text_block_count':len(textblocks),
       'image_include_count':len(soup.select('.ImageInclude')), 'figure_count':len(soup.find_all('figure'))}
Path('page-audit').mkdir(exist_ok=True)
Path('page-audit/tutbury-inspection.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':audit['status'],'date':ts,'title':audit['title'],'source_bytes':audit['source_bytes'],'image_refs':refs[:90],'scripts':scripts[:4],'textblocks':textblocks[:15]},ensure_ascii=False,indent=2))
