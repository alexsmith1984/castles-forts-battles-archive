#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/fotheringhay-castle")
IMG=ROOT/"images"; IMG.mkdir(parents=True, exist_ok=True)
REP=ROOT/"recovery-report.json"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 FotheringhayArchiveRecovery/1"

def get(u,t=6,headers=None):
    h=dict(S.headers)
    if headers: h.update(headers)
    try: return S.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception: return None

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.size; fmt=im.format; im.verify(); return w,h,fmt
    except Exception: return None

def valid(b):
    z=info(b)
    return z if z and z[0]>=100 and z[1]>=80 else None

def save(identity,b,meta):
    z=valid(b)
    if not z: return None
    ext=".png" if z[2]=="PNG" else ".jpg"
    p=IMG/(identity+ext); p.write_bytes(b)
    meta.update({
      "identity":identity,"file":"images/"+p.name,"dimensions":[z[0],z[1]],"format":z[2],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":"full/near-full" if max(z[0],z[1])>=700 else "thumbnail/lower-resolution",
      "identification":"certain"
    })
    return meta

def variants(url):
    out=[url]
    if "://" in url:
      out += [url.replace("http://","https://",1),url.replace("https://","http://",1)]
      out += [u.replace("://www.","://",1) for u in list(out) if "://www." in u]
    # add no-query form and case variants for extension
    more=[]
    for u in list(out):
      p=urlsplit(u); noq=urlunsplit((p.scheme,p.netloc,p.path,"",""))
      more.append(noq)
      if p.path.lower().endswith(".jpg"):
        more.append(noq[:-4]+".JPG")
    out += more
    return list(dict.fromkeys(out))

def wayback(identity,cands):
    urls=[]
    for c in cands: urls += variants(c)
    rows=[]
    def q(u):
      ep="https://web.archive.org/cdx/search/cdx?url="+quote(u,safe=":/?=&")+"&output=json&fl=timestamp,original,statuscode,mimetype&filter=statuscode:200&collapse=digest"
      r=get(ep,5)
      if not r or r.status_code!=200:return []
      try:d=r.json()
      except Exception:return []
      return d[1:] if isinstance(d,list) and d else []
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
      for part in ex.map(q,urls): rows.extend(part)
    seen=set()
    for row in reversed(rows):
      if len(row)<2:continue
      ts,orig=row[0],row[1]
      key=(ts,orig)
      if key in seen:continue
      seen.add(key)
      for mod in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mod}/{orig}",7)
        if r and r.status_code==200 and valid(r.content):
          return save(identity,r.content,{"method":"wayback-exact-variant","archive_timestamp":ts,"archive_original":orig})
    return None

def arquivo(identity,cands):
    urls=[]
    for c in cands: urls += variants(c)
    rows=[]
    def q(u):
      ep="https://arquivo.pt/wayback/cdx?url="+quote(u,safe=":/?=&")+"&output=json"
      r=get(ep,5)
      if not r or r.status_code!=200:return []
      try:d=r.json()
      except Exception:return []
      if isinstance(d,list) and d and isinstance(d[0],list): return d[1:]
      return d if isinstance(d,list) else []
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
      for part in ex.map(q,urls): rows.extend(part)
    seen=set()
    for row in reversed(rows):
      if isinstance(row,list) and len(row)>=2:
        ts,orig=str(row[0]),str(row[1])
      elif isinstance(row,dict):
        ts=str(row.get("timestamp") or ""); orig=str(row.get("url") or row.get("original") or "")
      else: continue
      if not ts or not orig: continue
      replay=f"https://arquivo.pt/wayback/{ts}id_/{orig}"
      if replay in seen: continue
      seen.add(replay)
      r=get(replay,7)
      if r and r.status_code==200 and valid(r.content):
        return save(identity,r.content,{"method":"arquivo.pt-exact-variant","archive_timestamp":ts,"archive_original":orig})
    return None

def cc_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",6)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    by={}
    for x in d:
      iid=x.get("id",""); m=re.search(r"CC-MAIN-(\d{4})-",iid)
      if m and 2018<=int(m.group(1))<=2023: by.setdefault(m.group(1),[]).append(iid)
    return [sorted(by[y],reverse=True)[0] for y in sorted(by)]
INDEXES=cc_indexes()

def cc_query(iid,u):
    ep=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/?=&")+"&output=json"
    r=get(ep,5)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
      try:
        x=json.loads(line)
        if str(x.get("status"))=="200" and all(x.get(k) for k in ("filename","offset","length")):out.append(x)
      except Exception:pass
    return out

def commoncrawl(identity,cands):
    urls=[]
    for c in cands:
      # prioritize no-query exact URLs and only a few protocol variants
      vv=variants(c)
      urls += [urlunsplit((*urlsplit(u)[:3],"","")) for u in vv[:4]]
    urls=list(dict.fromkeys(urls))
    recs=[]
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
      futs=[ex.submit(cc_query,i,u) for i in INDEXES for u in urls]
      for fut in cf.as_completed(futs):
        try: recs.extend(fut.result())
        except Exception: pass
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs}
    for x in sorted(uniq.values(),key=lambda q:int(q.get("length") or 0),reverse=True)[:20]:
      st=int(x["offset"]);ln=int(x["length"])
      r=get("https://data.commoncrawl.org/"+x["filename"],10,{"Range":f"bytes={st}-{st+ln-1}"})
      if not r or r.status_code not in (200,206):continue
      try:payload=gzip.decompress(r.content).split(b"\r\n\r\n")[-1]
      except Exception:continue
      if valid(payload):
        return save(identity,payload,{"method":"common-crawl-exact-variant","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename")})
    return None

rep=json.loads(REP.read_text(encoding="utf-8"))
targets={x["identity"]:x.get("candidate_urls",[]) for x in rep.get("missing",[])}
def recover(item):
    identity,cands=item
    for f in (wayback,arquivo,commoncrawl):
      x=f(identity,cands)
      if x:return identity,x
    return identity,None

found={}
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    for identity,x in ex.map(recover,targets.items()):
      if x:found[identity]=x

by={x["identity"]:x for x in rep.get("images",[])}; by.update(found)
order=rep.get("desktop_image_identities",[])
rep["images"]=[by[i] for i in order if i in by]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(order)-len(rep["images"])
rep["missing"]=[{"identity":i,"candidate_urls":targets.get(i,[])} for i in order if i not in by]
rep["fresh_deep_search_2026_09_14"]={
  "completed":True,
  "methods":["Wayback CDX exact URL/query/case/protocol variants","Arquivo.pt exact URL/query/case/protocol variants","Common Crawl representative 2018-2023 indexes"],
  "found":sorted(found),
  "commoncrawl_indexes_checked":INDEXES
}
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

p=ROOT/"index.html"; soup=BeautifulSoup(p.read_text(encoding="utf-8"),"html.parser")
h=soup.find("h2",string=lambda s:s and "Recovered original photographs" in s)
if h:
  # remove existing figures after heading, then rebuild in source identity order
  for fig in list(h.find_all_next("figure")): fig.decompose()
  anchor=h
  for identity in order:
    if identity not in by: continue
    fig=soup.new_tag("figure"); a=soup.new_tag("a",href=by[identity]["file"])
    im=soup.new_tag("img",src=by[identity]["file"],alt="Fotheringhay Castle archived original image")
    a.append(im); fig.append(a); cap=soup.new_tag("figcaption")
    cap.string=identity.replace("_"," ")+(" — lower-resolution archived recovery" if by[identity].get("quality")!="full/near-full" else "")
    fig.append(cap); anchor.insert_after(fig); anchor=fig
note=soup.find("div",class_="note")
if note:
  note.string=(f"Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. "
               f"{len(rep['images'])} of {len(order)} identified original content-image positions have been recovered; "
               f"{rep['still_missing']} remain unavailable. No unrelated substitute photographs have been introduced.")
p.write_text(str(soup),encoding="utf-8")
print(json.dumps(rep["fresh_deep_search_2026_09_14"],indent=2))
print(json.dumps({"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"]},indent=2))
