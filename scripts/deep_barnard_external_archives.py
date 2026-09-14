#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, os, re
from pathlib import Path
from urllib.parse import quote, urlsplit
import requests
from PIL import Image

ROOT=Path("recovered/barnard-castle"); IMG=ROOT/"images"; REP=ROOT/"recovery-report.json"
TARGETS=["63b957bcfce4","19f116199cea","437bac9c274a","444adbef8dfa","160c94cfc368"]
UA={"User-Agent":"Mozilla/5.0 (Barnard Castle external archive recovery)"}

def get(u,t=8,headers=None):
    h=dict(UA)
    if headers:h.update(headers)
    try:return requests.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception:return None

def info(b):
    try:
        im=Image.open(io.BytesIO(b));w,h=im.width,im.height;fmt=im.format;im.verify();return w,h,fmt
    except Exception:return None

def valid(b):
    z=info(b)
    if not z or z[0]<80 or z[1]<60:return None
    if abs((z[0]/z[1])-(470/313))/(470/313)>.04:return None
    return z

def save(target,b,meta):
    z=valid(b)
    if not z:return None
    p=IMG/("gallery_"+target+".jpg");p.write_bytes(b)
    meta.update({"identity":"gallery_"+target,"file":"images/"+p.name,"dimensions":[z[0],z[1]],
                 "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"identification":"certain"})
    return meta

def arquivo(target):
    originals=[]
    for suffix in (".jpg","t.jpg"):
      for scheme in ("http","https"):
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
          originals.append(f"{scheme}://{host}/wpimages/{target}{suffix}")
    replays=[]
    for u in originals:
      for ep in (
        "https://arquivo.pt/wayback/cdx?url="+quote(u,safe=":/")+"&output=json",
        "https://arquivo.pt/textsearch?versionHistory="+quote(u,safe=":/")+"&maxItems=50",
      ):
        r=get(ep,8)
        if not r or r.status_code!=200:continue
        txt=r.text
        try:
          d=r.json()
          def walk(o):
            if isinstance(o,dict):
              for key in ("linkToArchive","linkToOriginalFile","url"):
                v=o.get(key)
                if isinstance(v,str) and "arquivo.pt" in v:replays.append((v,u))
              ts=o.get("timestamp") or o.get("tstamp") or o.get("date")
              ou=o.get("original") or o.get("url")
              if ts and ou and "castlesfortsbattles" in str(ou):
                digits=re.sub(r"\D","",str(ts))[:14]
                if len(digits)>=8:
                  replays.append((f"https://arquivo.pt/wayback/{digits}id_/{ou}",u))
                  replays.append((f"https://arquivo.pt/noFrame/replay/{digits}/{ou}",u))
              for v in o.values():walk(v)
            elif isinstance(o,list):
              for v in o:walk(v)
          walk(d)
        except Exception:pass
    seen=set()
    for replay,orig in replays[:100]:
      if replay in seen:continue
      seen.add(replay)
      r=get(replay,9)
      if r and r.status_code==200 and valid(r.content):
        isfull=not orig.lower().endswith("t.jpg")
        return save(target,r.content,{"method":"arquivo.pt-exact-hash","archive_replay":replay,
          "archive_original":orig,"quality":"full/near-full" if isfull else "thumbnail/lower-resolution"})
    return None

def commoncrawl_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",10)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except:return []
    per={}
    for x in d:
      iid=x.get("id","");m=re.search(r"CC-MAIN-(\d{4})-",iid)
      if m and 2014<=int(m.group(1))<=2022:
        per.setdefault(int(m.group(1)),[]).append(iid)
    return [sorted(per[y],reverse=True)[0] for y in sorted(per)]

INDEXES=commoncrawl_indexes()

def cc_query(args):
    iid,u=args
    q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
    r=get(q,7);out=[]
    if not r or r.status_code!=200:return out
    for line in r.text.splitlines():
      try:
        x=json.loads(line)
        if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"):out.append(x)
      except Exception:pass
    return out

def commoncrawl(target):
    urls=[]
    for suffix in (".jpg","t.jpg"):
      for scheme in ("http","https"):
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
          urls.append(f"{scheme}://{host}/wpimages/{target}{suffix}")
    tasks=[(iid,u) for iid in INDEXES for u in urls]
    recs=[]
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
      for rows in ex.map(cc_query,tasks):
        recs.extend(rows)
    uniq={}
    for x in recs:uniq[(x["filename"],x["offset"],x["length"])]=x
    cand=sorted(uniq.values(),key=lambda x:int(x.get("length") or 0),reverse=True)[:20]
    for x in cand:
      st=int(x["offset"]);ln=int(x["length"])
      r=get("https://data.commoncrawl.org/"+x["filename"],12,headers={"Range":f"bytes={st}-{st+ln-1}"})
      if not r or r.status_code not in (200,206):continue
      try:
        raw=gzip.decompress(r.content)
        # WARC header + HTTP header + payload; pick image-looking suffix chunks.
        chunks=raw.split(b"\r\n\r\n")
        payload=chunks[-1]
      except Exception:continue
      if valid(payload):
        isfull=not str(x.get("url","")).lower().endswith("t.jpg")
        return save(target,payload,{"method":"common-crawl-exact-hash","commoncrawl_url":x.get("url"),
          "commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename"),
          "quality":"full/near-full" if isfull else "thumbnail/lower-resolution"})
    return None

def recover(target):
    x=arquivo(target)
    if x:return target,x
    return target,commoncrawl(target)

found={}
with cf.ThreadPoolExecutor(max_workers=5) as ex:
  for target,x in ex.map(recover,TARGETS):
    if x:found[target]=x

rep=json.loads(REP.read_text(encoding="utf-8"))
images={x["identity"]:x for x in rep.get("images",[])}
images.update({x["identity"]:x for x in found.values()})
order=["barnard_castle1","barnard_castle4"]+["gallery_"+t for t in TARGETS]
rep["images"]=[images[i] for i in order if i in images]
rep["missing"]=[m for m in rep.get("missing",[]) if m["identity"] not in images]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")=="thumbnail/lower-resolution" for x in rep["images"])
rep["still_missing"]=len(rep["missing"])
rep["external_archive_search_completed"]=True
rep["external_archive_methods"]=["Arquivo.pt exact-hash search","Common Crawl exact-hash search"]
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

page=(ROOT/"index.html").read_text(encoding="utf-8")
rec=len(rep["images"]);total=rep["original_image_positions_identified"]
page=re.sub(r"\d+ of \d+ identified original content-image positions have been recovered",f"{rec} of {total} identified original content-image positions have been recovered",page)
page=re.sub(r"; \d+ remain unavailable",f"; {rep['still_missing']} remain unavailable" if rep["still_missing"] else "",page)
a=page.find("<h2>Recovered original photographs</h2>");b=page.find("</article>",a)
if a>=0 and b>a:
  figs=[]
  for x in rep["images"]:
    note="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
    figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Barnard Castle archived original image"></a><figcaption>{x["identity"].replace("_"," ")+note}</figcaption></figure>')
  page=page[:a]+"<h2>Recovered original photographs</h2>"+"".join(figs)+page[b:]
(ROOT/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({"commoncrawl_indexes_checked":len(INDEXES),"found_now":sorted(found),
 "still_missing":[m["identity"] for m in rep["missing"]],"recovered_total":len(rep["images"])},indent=2))
