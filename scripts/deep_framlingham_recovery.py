#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, re
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/framlingham-castle")
IMG=ROOT/"images"; IMG.mkdir(parents=True, exist_ok=True)
REP=ROOT/"recovery-report.json"
SRC=ROOT/"source.html"
TS="20220826211200"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 FramlinghamArchiveRecovery/1"

NAMED={
 "framlingham_castle3":"http://www.castlesfortsbattles.co.uk/Framlingham_Castle3.JPG",
 "framlingham_castle32":"http://www.castlesfortsbattles.co.uk/Framlingham_Castle32.JPG",
 "framlingham_layout":"http://www.castlesfortsbattles.co.uk/Framlingham_Layout.png",
 "framlingham_castle5":"http://www.castlesfortsbattles.co.uk/Framlingham_Castle5.JPG",
 "framlingham_castle29":"http://www.castlesfortsbattles.co.uk/Framlingham_Castle29.jpg",
}
GALLERY=[
 "fb0085ed27b5","46620e058757","8dbc3bb267bf","f683b7e82778","c5c218958b8b",
 "39d041d44c73","d0545ccc19c9","1e98c6c07de9","ba54b5bdbc44","d291e75811da",
 "d51b9b6c98c","53f44a5cd527","51487b2a281","42238eb8e26"
]
ORDER=list(NAMED)+["gallery_"+x for x in GALLERY]

def get(u,t=7,headers=None):
    h=dict(S.headers)
    if headers:h.update(headers)
    try:return S.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception:return None

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.size; fmt=im.format; im.verify(); return w,h,fmt
    except Exception:return None

def save(identity,b,meta,quality=None):
    z=info(b)
    if not z or z[0]<100 or z[1]<80:return None
    ext=".png" if z[2]=="PNG" else ".jpg"
    p=IMG/(identity+ext); p.write_bytes(b)
    if quality is None: quality="full/near-full" if max(z[0],z[1])>=700 else "thumbnail/lower-resolution"
    meta.update({"identity":identity,"file":"images/"+p.name,"dimensions":[z[0],z[1]],"format":z[2],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":quality,"identification":"certain"})
    return meta

def protocol_variants(u):
    out=[u,u.replace("http://","https://",1)]
    if "://www." in u:
        out += [x.replace("://www.","://",1) for x in list(out)]
    # extension case
    for x in list(out):
        if x.lower().endswith(".jpg"):
            out.append(x[:-4]+".JPG")
    return list(dict.fromkeys(out))

def wayback_same(identity,u,quality=None):
    for v in protocol_variants(u):
        for mod in ("id_","im_"):
            r=get(f"https://web.archive.org/web/{TS}{mod}/{v}")
            if r and r.status_code==200 and info(r.content):
                return save(identity,r.content,{"method":"same-capture","archive_timestamp":TS,"archive_original":v},quality)
    return None

def wayback_history(identity,u,quality=None):
    for v in protocol_variants(u):
        q="https://web.archive.org/cdx/search/cdx?url="+quote(v,safe=":/")+"&output=json&fl=timestamp,original,statuscode,mimetype&filter=statuscode:200&collapse=digest"
        r=get(q,6)
        if not r or r.status_code!=200:continue
        try:rows=r.json()[1:]
        except Exception:continue
        for row in reversed(rows[-30:]):
            ts,orig=row[0],row[1]
            rr=get(f"https://web.archive.org/web/{ts}id_/{orig}",7)
            if rr and rr.status_code==200 and info(rr.content):
                return save(identity,rr.content,{"method":"wayback-history","archive_timestamp":ts,"archive_original":orig},quality)
    return None

def arquivo(identity,u,quality=None):
    for v in protocol_variants(u):
        q="https://arquivo.pt/wayback/cdx?url="+quote(v,safe=":/")+"&output=json"
        r=get(q,6)
        if not r or r.status_code!=200:continue
        try:d=r.json()
        except Exception:continue
        rows=d[1:] if isinstance(d,list) and d and isinstance(d[0],list) else (d if isinstance(d,list) else [])
        for row in reversed(rows[-30:]):
            if not isinstance(row,list) or len(row)<2:continue
            ts,orig=str(row[0]),str(row[1])
            rr=get(f"https://arquivo.pt/wayback/{ts}id_/{orig}",7)
            if rr and rr.status_code==200 and info(rr.content):
                return save(identity,rr.content,{"method":"arquivo.pt","archive_timestamp":ts,"archive_original":orig},quality)
    return None

def cc_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",6)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    by={}
    for x in d:
        iid=x.get("id",""); m=re.search(r"CC-MAIN-(\d{4})-",iid)
        if m and 2016<=int(m.group(1))<=2023:by.setdefault(m.group(1),[]).append(iid)
    return [sorted(by[y],reverse=True)[0] for y in sorted(by)]
INDEXES=cc_indexes()

def commoncrawl(identity,u,quality=None):
    recs=[]
    def q(pair):
        iid,v=pair
        ep=f"https://index.commoncrawl.org/{iid}-index?url="+quote(v,safe=":/")+"&output=json"
        r=get(ep,5)
        if not r or r.status_code!=200:return []
        out=[]
        for line in r.text.splitlines():
            try:
                x=json.loads(line)
                if str(x.get("status"))=="200" and all(x.get(k) for k in ("filename","offset","length")):out.append(x)
            except Exception:pass
        return out
    pairs=[(i,v) for i in INDEXES for v in protocol_variants(u)[:4]]
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for part in ex.map(q,pairs):recs.extend(part)
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs}
    for x in sorted(uniq.values(),key=lambda q:int(q.get("length") or 0),reverse=True)[:12]:
        st=int(x["offset"]);ln=int(x["length"])
        r=get("https://data.commoncrawl.org/"+x["filename"],10,{"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206):continue
        try:payload=gzip.decompress(r.content).split(b"\r\n\r\n")[-1]
        except Exception:continue
        if info(payload):
            return save(identity,payload,{"method":"common-crawl","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename")},quality)
    return None

def recover_gallery(h):
    ident="gallery_"+h; u=f"http://www.castlesfortsbattles.co.uk/wpimages/{h}.jpg"
    # WebPlus gallery files themselves are the page's genuine gallery originals.
    for fn in (wayback_same,wayback_history,arquivo,commoncrawl):
        x=fn(ident,u,"full/near-full")
        if x:return ident,x
    # Last resort authenticated gallery thumbnail
    tu=f"http://www.castlesfortsbattles.co.uk/wpimages/{h}t.jpg"
    for fn in (wayback_same,wayback_history,arquivo,commoncrawl):
        x=fn(ident,tu,"thumbnail/lower-resolution")
        if x:return ident,x
    return ident,None

def recover_named(item):
    ident,u=item
    for fn in (wayback_same,wayback_history,arquivo,commoncrawl):
        x=fn(ident,u)
        if x:return ident,x
    # authenticated same-page display export mapping from source
    src=SRC.read_text(encoding="utf-8",errors="ignore")
    m=re.search(r'href="'+re.escape(u)+r'"[^>]*>\s*<img[^>]+src="(http://www\.castlesfortsbattles\.co\.uk/wpimages/[^"]+)"',src,re.I)
    if m:
        du=m.group(1)
        for fn in (wayback_same,wayback_history,arquivo,commoncrawl):
            x=fn(ident,du,"thumbnail/lower-resolution")
            if x:
                x["method"]="same-image-WebPlus-display-export"
                x["source_original_target"]=u
                return ident,x
    return ident,None

found={}
with cf.ThreadPoolExecutor(max_workers=6) as ex:
    futs=[ex.submit(recover_named,x) for x in NAMED.items()]+[ex.submit(recover_gallery,h) for h in GALLERY]
    for fut in cf.as_completed(futs):
        ident,x=fut.result()
        if x:found[ident]=x

rep=json.loads(REP.read_text(encoding="utf-8"))
rep["original_image_positions_identified"]=len(ORDER)
rep["desktop_image_identities"]=ORDER
rep["images"]=[found[i] for i in ORDER if i in found]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(ORDER)-len(rep["images"])
rep["missing"]=[]
for i in ORDER:
    if i in found:continue
    if i in NAMED:rep["missing"].append({"identity":i,"candidate_urls":protocol_variants(NAMED[i])})
    else:
        h=i.replace("gallery_","");rep["missing"].append({"identity":i,"candidate_urls":[f"http://www.castlesfortsbattles.co.uk/wpimages/{h}.jpg",f"http://www.castlesfortsbattles.co.uk/wpimages/{h}t.jpg"]})
rep["counting_method"]="Five standalone content-image positions plus fourteen genuine WebPlus gallery photographs declared in wp_imgArray_pg_7. Navigation/UI/social graphics and gallery thumbnails are not counted separately."
rep["deep_recovery_history"]=rep.get("deep_recovery_history",[])+[{"date":"2026-09-14","method":"same capture + Wayback history + Arquivo.pt + Common Crawl + authenticated WebPlus display fallbacks","recovered":sorted(found),"remaining":[x["identity"] for x in rep["missing"]]}]
rep["external_archive_search_completed"]=True
rep["external_archive_methods"]=["Wayback supplied capture","Wayback exact-history CDX","Arquivo.pt exact filename","Common Crawl representative 2016-2023 indexes"]
rep["status"]="COMPLETE" if rep["still_missing"]==0 else "PARTIAL"
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# Rebuild image section only.
p=ROOT/"index.html";soup=BeautifulSoup(p.read_text(encoding="utf-8"),"html.parser")
h=soup.find("h2",string=lambda s:s and "Recovered original photographs" in s)
if h:
    for fig in list(h.find_all_next("figure")):fig.decompose()
    anchor=h
    for ident in ORDER:
        x=found.get(ident)
        if not x:continue
        fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"])
        im=soup.new_tag("img",src=x["file"],alt="Framlingham Castle archived original image")
        a.append(im);fig.append(a)
        cap=soup.new_tag("figcaption");cap.string=ident.replace("_"," ")+(" — lower-resolution archived recovery" if x["quality"]!="full/near-full" else "")
        fig.append(cap);anchor.insert_after(fig);anchor=fig
note=soup.find("div",class_="note")
if note:
    note.string=(f"Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. "
                 f"{len(rep['images'])} of {len(ORDER)} identified original content-image positions have been recovered; "
                 f"{rep['still_missing']} remain unavailable. No unrelated substitute photographs have been introduced.")
p.write_text(str(soup),encoding="utf-8")

audit=Path("page-audit/framlingham-castle.json")
audit.write_text(json.dumps({"name":"Framlingham Castle","slug":"framlingham-castle","status":rep["status"],"source":TS,
 "positions":len(ORDER),"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],
 "missing":rep["still_missing"],"missing_identities":[x["identity"] for x in rep["missing"]]},indent=2)+"\n")
print(json.dumps({"positions":len(ORDER),"recovered":len(rep["images"]),"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"],"found":sorted(found)},indent=2))
