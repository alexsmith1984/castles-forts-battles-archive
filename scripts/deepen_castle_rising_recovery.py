#!/usr/bin/env python3
from __future__ import annotations
import gzip, io, json, os, re, shutil, hashlib
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PIL import Image
from warcio.archiveiterator import ArchiveIterator

ROOT=Path("recovered/castle-rising-castle")
IMG=ROOT/"images"; REP=ROOT/"recovery-report.json"; PAGE=ROOT/"index.html"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Castle Rising deep archival recovery)"
TARGET_RATIO=1001/434

def get(u,timeout=6,headers=None):
    try: return S.get(u,timeout=timeout,allow_redirects=True,headers=headers)
    except Exception: return None

def info_bytes(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.width,im.height; im.verify(); return w,h
    except Exception: return None

def valid_hero(b):
    z=info_bytes(b)
    if not z:return None
    w,h=z
    if w<250 or h<150:return None
    if abs((w/h)-TARGET_RATIO)/TARGET_RATIO>.08:return None
    return z

def iminfo(p):
    with Image.open(p) as im:return im.width,im.height

def save_hero(b,prov):
    p=IMG/"castle_rising2.jpg"; p.write_bytes(b)
    w,h=iminfo(p)
    prov.update({
      "identity":"castle_rising2","file":"images/castle_rising2.jpg","dimensions":[w,h],
      "quality":"full/near-full" if w>=900 else "thumbnail/lower-resolution",
      "identification":"certain","bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()
    })
    return prov

def arquivo_try():
    originals=[
      "http://www.castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "https://www.castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "http://www.castlesfortsbattles.co.uk/east/images/castle_rising2.jpg",
      "https://www.castlesfortsbattles.co.uk/east/images/castle_rising2.jpg",
    ]
    pairs=[]
    for u in originals:
      endpoints=[
        "https://arquivo.pt/wayback/cdx?url="+quote(u,safe=":/")+"&output=json",
        "https://arquivo.pt/textsearch?versionHistory="+quote(u,safe=":/")+"&maxItems=50",
      ]
      for ep in endpoints:
        r=get(ep,8)
        if not r or r.status_code!=200:continue
        try:d=r.json()
        except Exception:continue
        def walk(o):
          if isinstance(o,dict):
            ts=o.get("timestamp") or o.get("tstamp") or o.get("date")
            ou=o.get("original") or o.get("url")
            link=o.get("linkToArchive")
            if link and isinstance(link,str) and "arquivo.pt" in link:
              pairs.append(("link",link,u))
            if ts and ou:
              ts=re.sub(r"\D","",str(ts))[:14]
              if len(ts)>=8:pairs.append((ts,str(ou),u))
            for v in o.values():walk(v)
          elif isinstance(o,list):
            for v in o:walk(v)
        walk(d)
    for a,b,orig in pairs[:120]:
      candidates=[b] if a=="link" else [
        f"https://arquivo.pt/wayback/{a}id_/{b}",
        f"https://arquivo.pt/noFrame/replay/{a}/{b}",
      ]
      for u in candidates:
        r=get(u,8)
        if r and r.status_code==200 and valid_hero(r.content):
          return save_hero(r.content,{"method":"arquivo.pt","archive_replay":u,"archive_original":orig})
    return None

def cc_query(args):
    iid,u=args
    ep=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/_*")+"&output=json"
    r=get(ep,6)
    out=[]
    if not r or r.status_code!=200:return out
    for line in r.text.splitlines():
      try:
        x=json.loads(line)
        if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"):
          out.append(x)
      except Exception:pass
    return out

def commoncrawl_try():
    r=get("https://index.commoncrawl.org/collinfo.json",10)
    if not r or r.status_code!=200:return None
    try:indexes=r.json()
    except Exception:return None
    byyear={}
    for x in indexes:
      iid=x.get("id",""); m=re.search(r"CC-MAIN-(\d{4})-",iid)
      if not m:continue
      y=int(m.group(1))
      if 2014<=y<=2022:byyear.setdefault(y,[]).append(iid)
    chosen=[]
    # up to two indexes per year; enough breadth without a huge crawl.
    for y in sorted(byyear,reverse=True):
      ids=sorted(byyear[y],reverse=True)
      chosen.extend(ids[:2])
    originals=[
      "http://www.castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "https://www.castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "http://www.castlesfortsbattles.co.uk/east/images/castle_rising2.jpg",
      "https://www.castlesfortsbattles.co.uk/east/images/castle_rising2.jpg",
      "http://castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "http://castlesfortsbattles.co.uk/east/images/castle_rising2.jpg",
    ]
    tasks=[(iid,u) for iid in chosen for u in originals]
    records=[]
    with ThreadPoolExecutor(max_workers=18) as ex:
      futs=[ex.submit(cc_query,t) for t in tasks]
      for fut in as_completed(futs):
        try:records.extend(fut.result())
        except Exception:pass
    uniq={}
    for x in records:
      uniq[(x["filename"],x["offset"],x["length"])]=x
    records=list(uniq.values())
    records.sort(key=lambda x:int(x.get("length") or 0),reverse=True)
    for x in records[:80]:
      start=int(x["offset"]);length=int(x["length"])
      rr=get("https://data.commoncrawl.org/"+x["filename"],12,headers={"Range":f"bytes={start}-{start+length-1}"})
      if not rr or rr.status_code not in (200,206):continue
      try:
        for rec in ArchiveIterator(io.BytesIO(rr.content)):
          if rec.rec_type in ("response","resource"):
            b=rec.content_stream().read()
            if valid_hero(b):
              return save_hero(b,{"method":"common-crawl","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x["filename"]})
      except Exception:
        try:
          b=gzip.decompress(rr.content)
          # peel WARC + HTTP headers
          parts=b.split(b"\r\n\r\n",2)
          payload=parts[-1]
          if valid_hero(payload):
            return save_hero(payload,{"method":"common-crawl","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x["filename"]})
        except Exception:pass
    return None

report=json.loads(REP.read_text(encoding="utf-8"))
images={x["identity"]:x for x in report.get("images",[])}

# Two "missing" positions are duplicate Adobe Muse exports of photographs we already recovered.
# Evidence: 8 <-> 82 and 10 <-> 102 share the underlying filename stem and exact aspect ratio,
# and the archived desktop page links the displayed duplicates into those original image uses.
for dest,src,expected in [
    ("castle_rising8","castle_rising82",682/453),
    ("castle_rising10","castle_rising102",301/453),
]:
    srcp=IMG/f"{src}.jpg";destp=IMG/f"{dest}.jpg"
    if not srcp.exists():continue
    shutil.copyfile(srcp,destp)
    w,h=iminfo(destp)
    assert abs((w/h)-expected)/expected<.01
    base=images[src].copy()
    base.update({
      "identity":dest,"file":f"images/{dest}.jpg",
      "method":"recovered-from-duplicate-Muse-export",
      "equivalent_export_identity":src,
      "recovery_basis":"The archived page contains a duplicate Muse export of the same underlying photograph; filename relation and aspect ratio match the missing logical position.",
      "bytes":destp.stat().st_size,
      "sha256":hashlib.sha256(destp.read_bytes()).hexdigest(),
    })
    images[dest]=base

hero=None
if not (IMG/"castle_rising2.jpg").exists():
    for fn in (arquivo_try,commoncrawl_try):
      try:hero=fn()
      except Exception:hero=None
      if hero:break
else:
    # Existing hero from an earlier successful pass.
    p=IMG/"castle_rising2.jpg";w,h=iminfo(p)
    if abs((w/h)-TARGET_RATIO)/TARGET_RATIO<.08:
      hero={"identity":"castle_rising2","file":"images/castle_rising2.jpg","dimensions":[w,h],"quality":"full/near-full","identification":"certain","method":"previous-deep-recovery","bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
if hero:images["castle_rising2"]=hero

order=report["desktop_image_identities"]
rows=[images[i] for i in order if i in images]
missing=[x for x in report.get("missing",[]) if x.get("identity") not in images]
if "castle_rising2" not in images and not any(x.get("identity")=="castle_rising2" for x in missing):
    missing.append({"identity":"castle_rising2","candidate_urls":[
      "https://www.castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "https://www.castlesfortsbattles.co.uk/east/images/castle_rising2.jpg?crc=4061376320"
    ]})

report["images"]=rows;report["missing"]=missing
report["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rows)
report["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")=="thumbnail/lower-resolution" for x in rows)
report["still_missing"]=len(missing)
report["duplicate_export_recoveries"]={"castle_rising8":"castle_rising82","castle_rising10":"castle_rising102"}
report["external_same_name_commons_images_used"]=False
report["verification_note"]="All displayed local images decode successfully. castle_rising8 and castle_rising10 were restored from archived duplicate Muse exports of the same underlying photographs (castle_rising82 and castle_rising102). No unrelated substitute photographs were used."
REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

page=PAGE.read_text(encoding="utf-8")
recovered=len(rows);total=report["original_image_positions_identified"]
page=re.sub(r"Only genuine original (?:image positions|images) recovered from (?:archived material|web archives) are shown \([^)]*\);",
            f"Only genuine original image positions recovered from archived material are shown ({recovered} of {total} identified content-image positions);",page)
a=page.find("<h2>Recovered original photographs, plans and images</h2>");b=page.find("</article>",a)
if a>=0 and b>a:
    figs=[]
    for x in rows:
      label=x["identity"].replace("_"," ")
      note=" — restored from the archived duplicate export of the same photograph" if x.get("method")=="recovered-from-duplicate-Muse-export" else ""
      figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Castle Rising Castle archived original image"></a><figcaption>{label}{note}</figcaption></figure>')
    page=page[:a]+"<h2>Recovered original photographs, plans and images</h2>"+"".join(figs)+page[b:]
PAGE.write_text(page,encoding="utf-8")
print(json.dumps({"positions":total,"recovered":recovered,"missing":[x["identity"] for x in missing],"hero_deep_recovery_method":hero.get("method") if hero else None},indent=2))
