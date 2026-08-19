import os,re,json,hashlib,html as H,sys,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin,urlunsplit
from io import BytesIO
import requests
from bs4 import BeautifulSoup
from PIL import Image

name=os.environ['NAME']; slug=os.environ['SLUG']; ts=os.environ['TS']; orig=os.environ['ORIG']
s=requests.Session(); s.headers['User-Agent']='Mozilla/5.0 (CastlesFortsBattles recovery)'

def get(u,t=12):
    try:return s.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def good_html(r): return bool(r and r.status_code==200 and '<html' in r.text.lower() and len(r.content)>1000)
def good_img(r):
    if not r or r.status_code!=200 or len(r.content)<700:return False
    try:
        im=Image.open(BytesIO(r.content)); w,h=im.size
        return w>=80 and h>=60
    except Exception:return False

def page_source():
    candidates=[(ts,orig)]
    sp=urlsplit(orig); hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith('www.') else 'www.'+sp.netloc]
    for scheme in ('http','https'):
        for h in dict.fromkeys(hosts):
            v=urlunsplit((scheme,h,sp.path,'',''))
            try:
                q=s.get('https://web.archive.org/cdx/search/cdx',params={'url':v,'output':'json','filter':['statuscode:200','mimetype:text/html'],'fl':'timestamp,original','collapse':'digest'},timeout=12)
                if q.status_code==200:
                    d=q.json(); rows=d[1:] if isinstance(d,list) and len(d)>1 else []
                    for row in reversed(rows[-6:]):candidates.append((row[0],row[1]))
            except Exception:pass
    seen=set()
    for cts,cu in candidates:
        if (cts,cu) in seen:continue
        seen.add((cts,cu)); r=get(f'https://web.archive.org/web/{cts}id_/{cu}',20)
        if good_html(r):return cts,cu,r
    return None,None,None

cts,corig,r=page_source()
if not r:
    Path('page-audit').mkdir(exist_ok=True)
    Path(f'page-audit/{slug}-failed.json').write_text(json.dumps({'name':name,'status':'source-failed'},indent=2))
    sys.exit(0)
raw=r.text; out=Path('recovered')/slug; imgdir=out/'images'; imgdir.mkdir(parents=True,exist_ok=True)
(out/'source.html').write_text(raw,encoding='utf-8',errors='replace')
soup=BeautifulSoup(raw,'html.parser')
deco=re.compile(r'(facebook|twitter|google|email|print|share|logo|favicon|blank\.gif|castlesfortsbattles(?:-crop)?\.(?:jpg|png)|battlefieldsofbritain(?:-crop)?\.(?:jpg|png))',re.I)
refs=[]
for e in soup.find_all(['img','a']):
    vals=[]
    if e.name=='img':
        for a in ('data-orig-src','data-muse-src','data-src','data-hidpi-src','src'):
            v=(e.get(a) or '').strip()
            if v and 'blank.gif' not in v.lower() and not v.startswith('data:'):vals.append(v)
    else:
        v=(e.get('href') or '').strip()
        if re.search(r'\.(?:jpe?g|png|gif|webp)(?:\?|$)',v,re.I):vals.append(v)
    for v in vals:
        u=urljoin(corig,v); b=os.path.basename(urlsplit(u).path)
        if b and not deco.search(b) and u not in refs:refs.append(u)

# Recover same-capture bytes first; exact CDX fallback only for missing key resources.
def recover_img(u):
    candidates=[(cts,u)]
    sp=urlsplit(u); hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith('www.') else 'www.'+sp.netloc]
    for scheme in ('http','https'):
        for h in dict.fromkeys(hosts):
            v=urlunsplit((scheme,h,sp.path,'',''))
            try:
                q=s.get('https://web.archive.org/cdx/search/cdx',params={'url':v,'output':'json','filter':'statuscode:200','fl':'timestamp,original','collapse':'digest','limit':4},timeout=7)
                if q.status_code==200:
                    d=q.json(); rows=d[1:] if isinstance(d,list) and len(d)>1 else []
                    for row in reversed(rows):candidates.append((row[0],row[1]))
            except Exception:pass
    seen=set()
    for its,iu in candidates:
        if (its,iu) in seen:continue
        seen.add((its,iu)); rr=get(f'https://web.archive.org/web/{its}id_/{iu}',7)
        if good_img(rr):
            h=hashlib.sha256(rr.content).hexdigest(); fn=re.sub(r'[^A-Za-z0-9._-]+','_',os.path.basename(urlsplit(u).path) or 'image.jpg')
            p=imgdir/fn
            if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()!=h:
                stem,suf=os.path.splitext(fn); fn=f'{stem}-{h[:8]}{suf}'; p=imgdir/fn
            p.write_bytes(rr.content)
            try:dims=list(Image.open(BytesIO(rr.content)).size)
            except Exception:dims=None
            return {'status':'recovered','file':'images/'+fn,'sha256':h,'timestamp':its,'dimensions':dims,'requested':u}
    return {'status':'unrecovered','requested':u}

results=[];shown=[];hashes=set()
for u in refs[:35]:
    x=recover_img(u);results.append(x)
    if x['status']=='recovered' and x['sha256'] not in hashes:
        hashes.add(x['sha256']);shown.append((u,x['file']))
    time.sleep(.04)

for x in soup(['script','style','noscript']):x.decompose()
nav={'England','Scotland','Wales','Home','UK Map','A-Z','Links','About Us','Contact Us','Terms and Conditions','CastlesFortsBattles.co.uk','BattlefieldsofBritain.co.uk','A-C','D-G','H-L','M-R','S-Z'}
blocks=[];seen=set()
for e in soup.find_all(['h1','h2','h3','h4','p','li']):
    tx=' '.join(e.stripped_strings).strip(); key=re.sub(r'\s+',' ',tx).casefold()
    if not tx or tx in nav or key in seen or tx.lower() in ('tweet','share','follow'):continue
    seen.add(key);blocks.append((e.name,tx))
body=[]
for tag,tx in blocks:
    if tag.startswith('h') or (len(tx)<95 and re.match(r'^(History|Historical Background|Prelude|Numbers|The Battle|Battle|Aftermath|Bibliography|What.s There|Getting There|Gallery|Design|Location|Access|Visiting|Statistics|Forces|Action)',tx,re.I)):body.append(f'<h2>{H.escape(tx)}</h2>')
    elif tag=='li':body.append(f'<p>• {H.escape(tx)}</p>')
    else:body.append(f'<p>{H.escape(tx)}</p>')
figs=[]
for u,rel in shown:
    cap=os.path.splitext(os.path.basename(urlsplit(u).path))[0].replace('_',' ');figs.append(f'<figure><img src="{H.escape(rel,quote=True)}" alt="{H.escape(name)}"><figcaption>{H.escape(cap)}</figcaption></figure>')

doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(name)} | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}</style></head><body><header><h1>{H.escape(name)}</h1></header><main><div class="note">Recovered from the archived page. The archived written content is preserved. Only genuine original images successfully recovered from web archives are shown ({len(shown)} distinct images).</div><article>{''.join(body)}<h2>Recovered original photographs, plans and images</h2>{''.join(figs) if figs else '<p>No original image files could be recovered from the available archive copy.</p>'}</article><p><a href="../../atoz-archive.html">Back to A–Z index</a></p></main></body></html>'''
(out/'index.html').write_text(doc,encoding='utf-8')
rep={'name':name,'status':'built','source_timestamp':cts,'source_original':corig,'text_blocks':len(blocks),'image_refs':len(refs),'images_recovered':len(shown),'images':results,'public_path':f'recovered/{slug}/index.html'}
(out/'recovery-report.json').write_text(json.dumps(rep,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({'name':name,'text_blocks':len(blocks),'refs':len(refs),'recovered':len(shown)}))
