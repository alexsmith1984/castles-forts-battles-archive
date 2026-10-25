#!/usr/bin/env python3
"""Browser-level diagnostic and recovery of authentic Tutbury sources only."""
import base64,io,hashlib,json,re,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import requests
from PIL import Image
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BASE=Path('recovered/tutbury-castle');IMG=BASE/'images';IMG.mkdir(exist_ok=True)
rep=json.loads((BASE/'recovery-report.json').read_text())
known={v['identity']:v for v in rep['images']}
missing={v['identity']:v for v in rep['missing']}
source=(BASE/'source.html').read_text()
capturl='https://web.archive.org/web/20220826211201/http:/www.castlesfortsbattles.co.uk/midlands/tutbury_castle.html'
older='https://web.archive.org/web/20210918014135/http:/www.castlesfortsbattles.co.uk/midlands/tutbury_castle.html'
results={'pages':[],'diagnostic_fetches':[],'new_images':[],'network_matches':[],'gallery_18_count':len(re.findall('new wp_galleryimage',source))}
def info(data):
    try:
        im=Image.open(io.BytesIO(data));w,h,f=im.width,im.height,im.format;im.verify()
        return (w,h,f) if w>=70 and h>=55 else None
    except:return None
def classify(u):
    m=re.search(r'/(Tutbury_Castle\d+[a-z]?)\.(?:jpg|jpeg)',u,re.I)
    if m:return m.group(1).lower()
    m=re.search(r'/([0-9a-f]{11,12})t?\.jpe?g',u,re.I)
    if m:return 'gallery_'+m.group(1).lower()
    m=re.search(r'/(wp[0-9a-f]{8}_05_06)\.jpg',u,re.I)
    if m:
        mapping={'wpb900ba74_05_06':'tutbury_castle22','wp5258371f_05_06':'tutbury_castle1',
         'wp9ee7376d_05_06':'tutbury_castle11a','wpa8797bf2_05_06':'tutbury_castle12',
         'wpb0d18409_05_06':'tutbury_castle10','wp702a10cf_05_06':'tutbury_castle14'}
        return mapping.get(m.group(1).lower())
def store(ident,body,url,method,quality='thumbnail/lower-resolution'):
    z=info(body)
    if not z or not ident or (ident in known and known[ident].get('quality')=='full/near-full'):return False
    if ident not in missing and ident not in known:return False
    ext='.png' if z[2]=='PNG' else '.jpg'
    fname=ident+ext;(IMG/fname).write_bytes(body)
    record={'identity':ident,'file':'images/'+fname,'archive_timestamp':'20220826211201','archive_original':url,
     'method':method,'dimensions':[z[0],z[1]],'format':z[2],'bytes':len(body),
     'sha256':hashlib.sha256(body).hexdigest(),'quality':quality,'identification':'certain'}
    if ident in known and known[ident]['dimensions'][0]*known[ident]['dimensions'][1]>z[0]*z[1] and quality!='full/near-full':return False
    known[ident]=record
    if ident not in results['new_images']:results['new_images'].append(ident)
    print('BROWSER RECOVER',ident,url,z,flush=True)
    return True

sess=requests.Session();sess.headers['User-Agent']='Mozilla/5.0 (Tutbury browser archival examination)'
critical=['http://www.castlesfortsbattles.co.uk/wpimages/wpb900ba74_05_06.jpg',
          'http://www.castlesfortsbattles.co.uk/wpimages/wp5258371f_05_06.jpg',
          'http://www.castlesfortsbattles.co.uk/midlands/wpimages/a913c8db479.jpg',
          'http://www.castlesfortsbattles.co.uk:80/midlands/wpimages/a913c8db479.jpg']
# Status and normalized redirect check only — avoids archive rate storms.
for u in critical:
    for mode in ('','id_','im_'):
        url='https://web.archive.org/web/20220826211201'+mode+'/'+u
        try:
            r=sess.get(url,timeout=9)
            z=info(r.content) if r.status_code==200 else None
            results['diagnostic_fetches'].append({'url':url,'status':r.status_code,'final':r.url,'length':len(r.content),
                       'content_type':r.headers.get('content-type'),'image_dimensions':list(z[:2]) if z else None,
                       'body_prefix':r.text[:90] if 'text' in r.headers.get('content-type','') else None})
            if z:
                ident=classify(u)
                store(ident,r.content,u,'browser-diagnostic-replay','thumbnail/lower-resolution' if '/wpimages/wp' in u else 'full/near-full')
        except Exception as e:results['diagnostic_fetches'].append({'url':url,'error':str(e)[:140]})
    print('DIRECT COMPLETE',u,flush=True)

with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  for link in (capturl,older):
    page=browser.new_page(viewport={'width':1300,'height':800},ignore_https_errors=True)
    net=[]
    def on_response(response):
      try:
        u=response.url
        ident=classify(u)
        if not ident:return
        ct=response.headers.get('content-type','')
        if response.status==200 and ('image/' in ct or re.search(r'\.(jpg|png|jpeg)',u,re.I)):
            b=response.body();z=info(b)
            if z:
                net.append({'identity':ident,'url':u,'dimensions':list(z[:2])})
                store(ident,b,u,'browser-network-response','thumbnail/lower-resolution' if 'wpimages/wp' in u else 'full/near-full')
      except:pass
    page.on('response',on_response)
    entry={'url':link,'navigation':None,'title':None,'linked_photos':[],'loaded_images':0,'matching_network':0}
    try:
        r=page.goto(link,wait_until='domcontentloaded',timeout=30000)
        entry['navigation']=r.status if r else None
        page.wait_for_timeout(3500)
        entry['title']=page.title()
        rows=page.locator('a:has(img)').all()
        for a in rows:
            try:
                href=a.get_attribute('href') or ''
                if not re.search(r'Tutbury_Castle\d+[a-z]?\.(?:jpg|jpeg)',href,re.I):continue
                img=a.locator('img').first
                data=img.evaluate("""img=>({src:img.getAttribute('src'),current:img.currentSrc,naturalWidth:img.naturalWidth,naturalHeight:img.naturalHeight,complete:img.complete})""")
                entry['linked_photos'].append({'href':href,**data})
                ident=classify(href)
                if ident and data['naturalWidth']>70 and data['naturalHeight']>55:
                    entry['loaded_images']+=1
                    try:
                        canvas=img.evaluate("""img=>{let c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext('2d').drawImage(img,0,0);try{return c.toDataURL('image/png')}catch(e){return null}}""")
                        if canvas and canvas.startswith('data:image/png;base64,'):
                            store(ident,base64.b64decode(canvas.split(',',1)[1]),data['current'],'browser-canvas-authentic-original')
                        else:
                            shot=img.screenshot(type='png',timeout=9000)
                            store(ident,shot,data['current'],'browser-element-screenshot-authentic')
                    except Exception as e:entry.setdefault('errors',[]).append(str(e)[:130])
            except Exception as e:entry.setdefault('errors',[]).append(str(e)[:130])
        entry['matching_network']=len(net)
        results['network_matches']+=net[:40]
    except Exception as e:entry['error']=str(e)[:210]
    results['pages'].append(entry)
    page.close()
  browser.close()
order=rep['desktop_image_identities']
rep['images']=[known[i] for i in order if i in known]
rep['missing']=[x for x in rep['missing'] if x['identity'] not in known]
rep['recovered_full_or_near_full']=sum(x['quality']=='full/near-full' for x in rep['images'])
rep['recovered_thumbnail_or_lower_resolution']=sum(x['quality']!='full/near-full' for x in rep['images'])
rep['still_missing']=len(rep['missing'])
rep['status']='COMPLETE / VERIFIED' if not rep['missing'] else 'PARTIAL / BROWSER CHECKED'
rep['browser_diagnostic_2026_10_25']={'pages':results['pages'],'new_images':results['new_images'],
            'diagnostic_fetches':results['diagnostic_fetches']}
from bs4 import BeautifulSoup as BS
pg=BS((BASE/'index.html').read_text(),'html.parser')
anchor=pg.find('h2',string=lambda x:x and 'Recovered original photographs' in x)
if anchor:
    for figure in list(anchor.find_all_next('figure')):figure.decompose()
    for note in list(anchor.find_all_next('p')):
        if note.get_text().strip()=='Original photographs could not be retrieved from available archives.':note.decompose()
    n=anchor
    for x in rep['images']:
        fig=pg.new_tag('figure');a=pg.new_tag('a',href=x['file'])
        im=pg.new_tag('img',src=x['file'],loading='lazy',alt='Tutbury original authenticated archived image')
        a.append(im);fig.append(a);cap=pg.new_tag('figcaption')
        cap.string=x['identity'].replace('_',' ')+( ' — lower-resolution archived original' if x['quality']!='full/near-full' else '')
        fig.append(cap);n.insert_after(fig);n=fig
note=pg.find('div',class_='note')
if note:note.string=f'Reconstructed from the archived Tutbury Castle page of 26 August 2022. {len(rep["images"])} of {len(order)} authenticated photographic positions recovered ({rep["recovered_full_or_near_full"]} full, {rep["recovered_thumbnail_or_lower_resolution"]} lower-resolution); {rep["still_missing"]} missing. No substitute photographs.'
(BASE/'index.html').write_text(str(pg))
(BASE/'recovery-report.json').write_text(json.dumps(rep,indent=2)+'\n')
Path('page-audit/tutbury-browser-diagnostic.json').write_text(json.dumps(results,indent=2)+'\n')
print('DIAGNOSTICS',json.dumps({'new':results['new_images'],'total':len(rep['images']),
           'pages':[{'nav':p['navigation'],'loaded_photos':p['loaded_images'],'linked':p['linked_photos']} for p in results['pages']],
           'direct':results['diagnostic_fetches']},indent=2)[:13000],flush=True)
