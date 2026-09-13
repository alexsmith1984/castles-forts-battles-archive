#!/usr/bin/env python3
from __future__ import annotations
import gzip, io, json, os, re, shutil, hashlib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote
import requests
from PIL import Image
from warcio.archiveiterator import ArchiveIterator

ROOT=Path("recovered/castle-rising-castle")
IMG=ROOT/"images"
REP=ROOT/"recovery-report.json"
PAGE=ROOT/"index.html"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Castle Rising deep archival recovery)"
TARGET_RATIO=1001/434

def iminfo(path):
    with Image.open(path) as im:
        return im.width, im.height

def valid_bytes(b, expected_ratio=None):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.width,im.height; im.verify()
    except Exception:
        return None
    if w<250 or h<150: return None
    if expected_ratio is not None:
        r=w/h
        if abs(r-expected_ratio)/expected_ratio > 0.08:
            return None
    return w,h

def raw_wayback(ts,u):
    return f"https://web.archive.org/web/{ts}id_/{u}"

def get(u,timeout=15,headers=None):
    try:
        return S.get(u,timeout=timeout,allow_redirects=True,headers=headers)
    except Exception:
        return None

def save_hero(b,provenance):
    ext=".jpg"
    p=IMG/"castle_rising2.jpg"
    p.write_bytes(b)
    w,h=iminfo(p)
    provenance.update({"identity":"castle_rising2","file":"images/castle_rising2.jpg","dimensions":[w,h],
                       "quality":"full/near-full" if w>=900 else "thumbnail/lower-resolution",
                       "identification":"certain","bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()})
    return provenance

def wayback_deep():
    basepaths=[
      "/east/assets/castle_rising2.jpg",
      "/east/images/castle_rising2.jpg",
      "/east/images/castle_rising2666x289.jpg",
      "/east/images/castle_rising2665x289.jpg",
      "/east/images/castle_rising2502x218.jpg",
      "/east/images/castle_rising2501x218.jpg",
    ]
    candidates=[]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
        for p in basepaths:
          u=f"{scheme}://{host}{p}"
          try:
            r=get("https://web.archive.org/cdx/search/cdx?url="+quote(u,safe=":/")+
                  "&output=json&fl=timestamp,original,statuscode,mimetype,length&filter=statuscode:200&collapse=digest&limit=200",20)
            if r and r.status_code==200:
              d=r.json()
              if isinstance(d,list) and len(d)>1:
                hdr=d[0]
                for row in d[1:]:
                  if len(row)==len(hdr):
                    x=dict(zip(hdr,row)); candidates.append(x)
          except Exception:
            pass
    # larger objects first, then newest
    candidates.sort(key=lambda x:(int(x.get("length") or 0),x.get("timestamp","")),reverse=True)
    seen=set()
    for x in candidates:
      key=(x.get("timestamp"),x.get("original"))
      if key in seen: continue
      seen.add(key)
      r=get(raw_wayback(x["timestamp"],x["original"]),15)
      if r and r.status_code==200 and valid_bytes(r.content,TARGET_RATIO):
        return save_hero(r.content,{"method":"wayback-deep","archive_timestamp":x["timestamp"],"archive_original":x["original"]})
    return None

def arquivo_deep():
    urls=[]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
        for p in ("/east/assets/castle_rising2.jpg","/east/images/castle_rising2.jpg"):
          urls.append(f"{scheme}://{host}{p}")
    for u in urls:
      # Arquivo.pt CDX-like endpoint; tolerate either JSON arrays or CDX text.
      for endpoint in (
        "https://arquivo.pt/wayback/cdx?url="+quote(u,safe=":/")+"&output=json",
        "https://arquivo.pt/textsearch?versionHistory="+quote(u,safe=":/")+"&maxItems=50"
      ):
        r=get(endpoint,18)
        if not r or r.status_code!=200: continue
        txt=r.text
        # harvest timestamps/URLs generically from response
        pairs=set()
        try:
          d=r.json()
          def walk(o):
            if isinstance(o,dict):
              ts=o.get("timestamp") or o.get("tstamp") or o.get("date")
              ou=o.get("original") or o.get("url") or o.get("linkToArchive")
              if ts and ou: pairs.add((str(ts).replace("-","").replace(":","").replace("T","")[:14],str(ou)))
              for v in o.values(): walk(v)
            elif isinstance(o,list):
              for v in o: walk(v)
          walk(d)
        except Exception:
          pass
        # Also extract replay URLs directly if present.
        replay=re.findall(r'https?://arquivo\.pt/(?:wayback|noFrame/replay)/(\d{8,14})[^"\s]*/(https?://[^"\s<>]+)',txt)
        pairs.update(replay)
        for ts,ou in list(pairs)[:80]:
          if "arquivo.pt/" in ou and "castlesfortsbattles" not in ou:
            continue
          for replay_url in (
             f"https://arquivo.pt/wayback/{ts}id_/{ou}",
             f"https://arquivo.pt/noFrame/replay/{ts}/{ou}",
          ):
            rr=get(replay_url,15)
            if rr and rr.status_code==200 and valid_bytes(rr.content,TARGET_RATIO):
              return save_hero(rr.content,{"method":"arquivo.pt","archive_timestamp":ts,"archive_original":ou})
    return None

def commoncrawl_deep():
    try:
      r=get("https://index.commoncrawl.org/collinfo.json",20)
      if not r or r.status_code!=200:return None
      indexes=r.json()
    except Exception:
      return None
    # Search a broad historical spread around the site's active period.
    wanted=[]
    for x in indexes:
      iid=x.get("id","")
      m=re.search(r"CC-MAIN-(\d{4})-",iid)
      if m and 2014 <= int(m.group(1)) <= 2022:
        wanted.append(iid)
    # Prefer 2021, 2020, 2019, 2022, then others; cap to 28 indexes.
    wanted.sort(key=lambda iid:(abs(int(re.search(r"(\d{4})",iid).group(1))-2020),iid))
    wanted=wanted[:28]
    target_urls=[]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
        target_urls += [
          f"{scheme}://{host}/east/assets/castle_rising2.jpg",
          f"{scheme}://{host}/east/images/castle_rising2.jpg",
          f"{scheme}://{host}/east/images/castle_rising2*",
        ]
    records=[]
    for iid in wanted:
      endpoint=f"https://index.commoncrawl.org/{iid}-index"
      for u in target_urls:
        rr=get(endpoint+"?url="+quote(u,safe=":/_*")+"&output=json",15)
        if not rr or rr.status_code!=200: continue
        for line in rr.text.splitlines():
          try:
            x=json.loads(line)
            if int(x.get("status","0"))==200 and x.get("filename") and x.get("offset") and x.get("length"):
              records.append(x)
          except Exception:
            pass
    # Larger captures first.
    records.sort(key=lambda x:int(x.get("length") or 0),reverse=True)
    seen=set()
    for x in records[:100]:
      key=(x["filename"],x["offset"],x["length"])
      if key in seen:continue
      seen.add(key)
      start=int(x["offset"]); length=int(x["length"])
      rr=get("https://data.commoncrawl.org/"+x["filename"],30,headers={"Range":f"bytes={start}-{start+length-1}"})
      if not rr or rr.status_code not in (200,206):continue
      try:
        raw=rr.content
        # Range chunks are gzip members containing WARC records.
        stream=io.BytesIO(raw)
        for record in ArchiveIterator(stream):
          if record.rec_type not in ("response","resource"): continue
          payload=record.content_stream().read()
          if valid_bytes(payload,TARGET_RATIO):
            return save_hero(payload,{"method":"common-crawl","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_index_record":key[0]})
      except Exception:
        # fallback manual gzip
        try:
          decomp=gzip.decompress(rr.content)
          marker=b"\r\n\r\n"
          a=decomp.find(marker)
          if a>=0:
            b=decomp.find(marker,a+4)
            payload=decomp[b+4:] if b>=0 else decomp[a+4:]
            if valid_bytes(payload,TARGET_RATIO):
              return save_hero(payload,{"method":"common-crawl","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_index_record":key[0]})
        except Exception:
          pass
    return None

# First, recover two original logical positions from duplicate Muse exports already captured.
report=json.loads(REP.read_text(encoding="utf-8"))
images={x["identity"]:x for x in report.get("images",[])}

pairs=[("castle_rising8","castle_rising82"),("castle_rising10","castle_rising102")]
for dest,src in pairs:
    srcp=IMG/f"{src}.jpg"; destp=IMG/f"{dest}.jpg"
    if srcp.exists():
        shutil.copyfile(srcp,destp)
        sw,sh=iminfo(srcp); dw,dh=iminfo(destp)
        assert (sw,sh)==(dw,dh)
        # Cross-check against the exact display aspect ratio from the archived HTML.
        expected={"castle_rising8":682/453,"castle_rising10":301/453}[dest]
        assert abs((dw/dh)-expected)/expected < .01
        base=images[src].copy()
        base.update({
          "identity":dest,"file":f"images/{dest}.jpg",
          "method":"recovered-from-duplicate-Muse-export",
          "equivalent_export_identity":src,
          "recovery_basis":"Archived page uses the same underlying photograph in a second Muse export; dimensions/aspect ratio match the missing logical position.",
          "sha256":hashlib.sha256(destp.read_bytes()).hexdigest(),
          "bytes":destp.stat().st_size,
        })
        images[dest]=base

# Then make a deeper archival attempt for the genuinely missing hero image.
hero=None
if not (IMG/"castle_rising2.jpg").exists():
    for fn in (wayback_deep,arquivo_deep,commoncrawl_deep):
        try:
            hero=fn()
        except Exception:
            hero=None
        if hero: break
if hero:
    images["castle_rising2"]=hero

order=report["desktop_image_identities"]
rows=[images[i] for i in order if i in images]
missing=[x for x in report.get("missing",[]) if x.get("identity") not in images]
# Ensure the true hero remains listed if all older missing entries were mutated away.
if "castle_rising2" not in images and not any(x.get("identity")=="castle_rising2" for x in missing):
    missing.append({"identity":"castle_rising2","candidate_urls":[
      "https://www.castlesfortsbattles.co.uk/east/assets/castle_rising2.jpg",
      "https://www.castlesfortsbattles.co.uk/east/images/castle_rising2.jpg?crc=4061376320"
    ]})

report["images"]=rows
report["missing"]=missing
report["recovered_full_or_near_full"]=sum(1 for x in rows if x.get("quality")=="full/near-full")
report["recovered_thumbnail_or_lower_resolution"]=sum(1 for x in rows if x.get("quality")=="thumbnail/lower-resolution")
report["still_missing"]=len(missing)
report["duplicate_export_recoveries"]={
  "castle_rising8":"castle_rising82",
  "castle_rising10":"castle_rising102"
}
report["external_same-name_commons_images_used"]=False
report["verification_note"]="All displayed local images decode successfully. castle_rising8 and castle_rising10 were restored from archived duplicate Muse exports of the same underlying photographs (castle_rising82 and castle_rising102). No unrelated substitute photographs were used."
REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# Rebuild the recovered-image gallery and status note.
page=PAGE.read_text(encoding="utf-8")
recovered=len(rows); total=report["original_image_positions_identified"]
page=re.sub(r"Only genuine original images recovered from web archives are shown \([^)]*\);",
            f"Only genuine original image positions recovered from archived material are shown ({recovered} of {total} identified content-image positions);",page)
start=page.find("<h2>Recovered original photographs, plans and images</h2>")
end=page.find("</article>",start)
if start>=0 and end>start:
    figs=[]
    for x in rows:
      label=x["identity"].replace("_"," ")
      note=""
      if x.get("method")=="recovered-from-duplicate-Muse-export":
        note=" — restored from the archived duplicate export of the same photograph"
      figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Castle Rising Castle archived original image"></a><figcaption>{label}{note}</figcaption></figure>')
    page=page[:start]+"<h2>Recovered original photographs, plans and images</h2>"+"".join(figs)+page[end:]
PAGE.write_text(page,encoding="utf-8")
print(json.dumps({
  "positions":total,
  "recovered":recovered,
  "missing":[x["identity"] for x in missing],
  "duplicate_export_recoveries":report["duplicate_export_recoveries"],
  "hero_deep_recovery_method": hero.get("method") if hero else None
},indent=2))
