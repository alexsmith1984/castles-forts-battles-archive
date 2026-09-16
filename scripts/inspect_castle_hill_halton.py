#!/usr/bin/env python3
import re,json,time
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

ORIG="http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html"
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 HaltonCastleInspector"
DECO=re.compile(r'(facebook|twitter|google|email|print|share|logo|favicon|blank|button|menu|arrow|spacer|home|castlesfortsbattles|battlefieldsofbritain|museutils|jquery)',re.I)
IMGEXT=re.compile(r'\.(?:jpe?g|png|gif|webp)(?:\?|$)',re.I)

def get(u,t=8,params=None):
    try:return S.get(u,params=params,timeout=t,allow_redirects=True)
    except:return None

def cleanstem(u):
    s=urlparse(u).path.rsplit("/",1)[-1]
    s=re.sub(r'\.(?:jpe?g|png|gif|webp)$','',s,flags=re.I)
    s=re.sub(r'(\d{2,4})x(\d{2,4})$','',s)
    return s

def parse(html,page):
    soup=BeautifulSoup(html,"html.parser")
    refs=[]
    # linked originals
    for a in soup.find_all("a",href=True):
        href=a.get("href","")
        if a.find("img") and IMGEXT.search(href):
            u=urljoin(page,href);b=urlparse(u).path.rsplit("/",1)[-1]
            if b and not DECO.search(b): refs.append(("asset-link",u))
    # all content imgs
    for im in soup.find_all("img"):
        kind="gallery" if "ImageInclude" in (im.get("class") or []) else "display"
        for attr in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
            v=im.get(attr)
            if not v or v.startswith("data:") or "blank.gif" in v.lower() or not IMGEXT.search(v): continue
            u=urljoin(page,v);b=urlparse(u).path.rsplit("/",1)[-1]
            if b and not DECO.search(b): refs.append((kind,u))
    asset=[];gallery=[];display=[]
    for kind,u in refs:
        st=cleanstem(u)
        if not st: continue
        target=asset if kind=="asset-link" else gallery if kind=="gallery" else display
        if st not in target: target.append(st)
    union=[]
    for st in asset+gallery+display:
        if re.search(r'(halton|castle|hill|motte|tower|keep|plan|view|gate|bailey|ditch|wall|ruin)',st,re.I) and st not in union:
            union.append(st)
    return {"asset":asset,"gallery":gallery,"display":display,"union":union}

urls=[]
for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
    urls.append(f"{scheme}://{host}/north_west/halton_castle_motte.html")
rows=[]
for u in urls:
    r=get("https://web.archive.org/cdx/search/cdx",10,{"url":u,"output":"json","filter":["statuscode:200","mimetype:text/html"],"fl":"timestamp,original,digest","collapse":"digest","from":"2014","to":"2023","limit":"200"})
    if not r or r.status_code!=200: continue
    try:
        j=r.json()
        for row in j[1:]:
            rows.append({"timestamp":row[0],"original":row[1],"digest":row[2] if len(row)>2 else ""})
    except: pass
seen=set();ded=[]
for x in rows:
    k=(x["timestamp"],x["original"])
    if k not in seen:seen.add(k);ded.append(x)
rows=ded
# Sample all if <=30 else spread.
rows.sort(key=lambda x:x["timestamp"])
if len(rows)>30:
    idx={0,len(rows)-1}
    for n in range(1,29):idx.add(round(n*(len(rows)-1)/29))
    rows=[rows[i] for i in sorted(idx)]
captures=[]
for x in rows:
    r=get(f'https://web.archive.org/web/{x["timestamp"]}id_/{x["original"]}',10)
    if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
    p=parse(r.text,x["original"])
    captures.append({"timestamp":x["timestamp"],"original":x["original"],"count":len(p["union"]),**p})
best=max(captures,key=lambda x:(x["count"],x["timestamp"])) if captures else None
print(json.dumps({"captures_found":len(captures),"best":best,"captures":[{"timestamp":x["timestamp"],"count":x["count"],"union":x["union"]} for x in captures]},indent=2))
