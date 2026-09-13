#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf
import hashlib, html as H, io, json, os, re, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image
import ftfy

PAGES=[
 {"name":"Bolingbroke Castle","slug":"bolingbroke-castle","ts":"20220826203621","orig":"http://www.castlesfortsbattles.co.uk/midlands/bolingbroke_castle.html"},
 {"name":"Conisbrough Castle","slug":"conisbrough-castle","ts":"20210618022643","orig":"https://www.castlesfortsbattles.co.uk/yorkshire/conisbrough_castle.html"},
 {"name":"Pembroke Castle","slug":"pembroke-castle","ts":"20210918015020","orig":"http://www.castlesfortsbattles.co.uk/south_west_wales/pembroke_castle.html"},
 {"name":"Kenilworth Castle","slug":"kenilworth-castle","ts":"20220826212821","orig":"http://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html"},
 {"name":"Goodrich Castle","slug":"goodrich-castle","ts":"20220826203514","orig":"http://www.castlesfortsbattles.co.uk/midlands/goodrich_castle.html"},
 {"name":"Fotheringhay Castle","slug":"fotheringhay-castle","ts":"20210918020043","orig":"http://www.castlesfortsbattles.co.uk/midlands/fotheringhay_castle.html"},
 {"name":"Framlingham Castle","slug":"framlingham-castle","ts":"20220826211200","orig":"http://www.castlesfortsbattles.co.uk/east/framlingham_castle.html"},
 {"name":"Pevensey Castle","slug":"pevensey-castle","ts":"20170913231910","orig":"http://www.castlesfortsbattles.co.uk/south_east/pevensey_castle.html"},
 {"name":"Pickering Castle","slug":"pickering-castle","ts":"20220524225709","orig":"http://www.castlesfortsbattles.co.uk/yorkshire/pickering_castle.html"},
 {"name":"Pontefract Castle","slug":"pontefract-castle","ts":"20210918010514","orig":"http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html"},
 {"name":"Richmond Castle","slug":"richmond-castle","ts":"20211208101939","orig":"http://www.castlesfortsbattles.co.uk/yorkshire/richmond_castle.html"},
 {"name":"Sandal Castle","slug":"sandal-castle","ts":"20210918024941","orig":"http://www.castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html"},
 {"name":"Warkworth Castle","slug":"warkworth-castle","ts":"20220826205457","orig":"http://www.castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html"},
 {"name":"Whittington Castle","slug":"whittington-castle","ts":"20210918013642","orig":"http://www.castlesfortsbattles.co.uk/north_west/whittington_castle_lancashire.html"},
]
ROOT=Path("recovered")
AUD=Path("page-audit"); AUD.mkdir(exist_ok=True)
INDEX_FILES=[Path("atoz-part1.html"),Path("atoz-part2.html"),Path("atoz-part3.html"),Path("atoz-part4.html"),Path("atoz-part5.html")]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles archival recovery audit)"

DECO=re.compile(r"(facebook|twitter|google|email|print|share|logo|favicon|blank\.gif|castlesfortsbattles(?:-crop)?\.(?:jpg|png)|battlefieldsofbritain(?:-crop)?\.(?:jpg|png)|youtube|pinterest)",re.I)
IMGEXT=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)
DIMSUF=re.compile(r"\d{2,4}x\d{2,4}$")

def get(u,t=12):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def good_html(r):
    return bool(r and r.status_code==200 and len(r.content)>1000 and "<html" in r.text.lower())

def iminfo_bytes(b):
    try:
        im=Image.open(io.BytesIO(b)); return im.width,im.height,im.format
    except Exception:return None

def good_img(r):
    if not r or r.status_code!=200 or len(r.content)<500:return False
    z=iminfo_bytes(r.content)
    return bool(z and z[0]>=80 and z[1]>=60)

def raw(ts,u):return f"https://web.archive.org/web/{ts}id_/{u}"

def cdx(u,limit=12):
    out=[]
    sp=urlsplit(u)
    hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    for scheme in ("http","https"):
      for host in dict.fromkeys(hosts):
        v=urlunsplit((scheme,host,sp.path,"",""))
        try:
          r=S.get("https://web.archive.org/cdx/search/cdx",params={
            "url":v,"output":"json","filter":"statuscode:200",
            "fl":"timestamp,original,length,mimetype","collapse":"digest","limit":limit
          },timeout=8)
          if r.status_code==200:
            d=r.json()
            if isinstance(d,list) and len(d)>1:
              hdr=d[0]
              out.extend(dict(zip(hdr,row)) for row in d[1:] if len(row)==len(hdr))
        except Exception:pass
    return out

def stem(u):return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()

def refs_from(e):
    vals=[]
    if e.name=="img":
      for a in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
        v=(e.get(a) or "").strip()
        if v and not v.startswith("data:") and "blank.gif" not in v.lower() and IMGEXT.search(v):vals.append(v)
    elif e.name=="a":
      v=(e.get("href") or "").strip()
      if IMGEXT.search(v):vals.append(v)
    return vals

def source_page(p):
    r=get(raw(p["ts"],p["orig"]),20)
    if good_html(r):
      return p["ts"],p["orig"],r.text
    candidates=[]
    for x in cdx(p["orig"],20):
      if x.get("timestamp") and x.get("original"):candidates.append((x["timestamp"],x["original"]))
    target=int(p["ts"])
    candidates=sorted(candidates,key=lambda x:abs(int(x[0])-target))
    seen=set()
    for ts,u in candidates[:12]:
      if (ts,u) in seen:continue
      seen.add((ts,u));r=get(raw(ts,u),20)
      if good_html(r):return ts,u,r.text
    return None,None,None

def canonical_identities(soup,corig):
    desktop=soup.find(id="bp_infinity") or soup
    exact=[]
    # Exact names: full-size asset links OR image refs without WIDTHxHEIGHT suffix.
    for e in desktop.find_all(["img","a"]):
      for v in refs_from(e):
        u=urljoin(corig,v); b=os.path.basename(urlsplit(u).path)
        if not b or DECO.search(b):continue
        st=stem(u)
        if not st:continue
        is_asset="/assets/" in urlsplit(u).path.lower()
        has_dims=bool(DIMSUF.search(st))
        if is_asset or not has_dims:
          if st not in exact:exact.append(st)
    # Remove obvious generic layout leftovers.
    exact=[x for x in exact if x not in ("spacer","header","footer","background","menu")]
    return desktop,exact

def map_identity(st,exact):
    if st in exact:return st
    for cand in sorted(exact,key=len,reverse=True):
      if st.startswith(cand) and DIMSUF.fullmatch(st[len(cand):]):return cand
    return None

def all_groups(soup,corig,exact):
    groups={i:[] for i in exact}
    for e in soup.find_all(["img","a"]):
      for v in refs_from(e):
        u=urljoin(corig,v); b=os.path.basename(urlsplit(u).path)
        if not b or DECO.search(b):continue
        ident=map_identity(stem(u),exact)
        if ident and u not in groups[ident]:groups[ident].append(u)
    return groups

def recover_identity(ident,refs,source_ts,corig):
    attempts=[]
    for u in refs:attempts.append((source_ts,u,"same-capture"))
    sp=urlsplit(corig)
    exts=[]
    for u in refs:
      ex=os.path.splitext(urlsplit(u).path)[1].lower()
      if ex and ex not in exts:exts.append(ex)
    if not exts:exts=[".jpg",".png"]
    for directory in ("images","assets"):
      for ex in exts[:2]:
        attempts.append((source_ts,urlunsplit((sp.scheme,sp.netloc,os.path.dirname(sp.path)+f"/{directory}/{ident}{ex}","","")),"same-capture-conventional"))
    best=None;seen=set()
    for ts,u,method in attempts:
      if (ts,u) in seen:continue
      seen.add((ts,u))
      r=get(raw(ts,u),7)
      if not good_img(r):continue
      z=iminfo_bytes(r.content);st=stem(u)
      exactfile=(st==ident)
      variant=st.startswith(ident) and bool(DIMSUF.fullmatch(st[len(ident):]))
      if not exactfile and not variant:continue
      rank=(1 if exactfile else 0,z[0]*z[1],len(r.content))
      if best is None or rank>best[0]:best=(rank,ts,u,method,r.content,z,exactfile)
    return best

def page_keyword(p):
    base=os.path.splitext(os.path.basename(urlsplit(p["orig"]).path))[0].lower()
    for suff in ("_castle_wakefield_1460","_castle_lancashire","_castle_bridge","_castle"):
      if base.endswith(suff):return base[:-len(suff)]
    return base.split("_")[0]

def wildcard_rows(p):
    sp=urlsplit(p["orig"]);key=page_keyword(p)
    rows=[]
    for directory in ("images","assets"):
      pat=urlunsplit((sp.scheme,sp.netloc,os.path.dirname(sp.path)+f"/{directory}/{key}*","",""))
      try:
        r=S.get("https://web.archive.org/cdx/search/cdx",params={
          "url":pat,"output":"json","filter":"statuscode:200",
          "fl":"timestamp,original,length,mimetype","collapse":"digest","limit":1200
        },timeout=12)
        if r.status_code==200:
          d=r.json()
          if isinstance(d,list) and len(d)>1:
            hdr=d[0];rows.extend(dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr))
      except Exception:pass
    return rows

def extract_text(desktop):
    clone=BeautifulSoup(str(desktop),"html.parser")
    for x in clone(["script","style","noscript"]):x.decompose()
    nav={"England","Scotland","Wales","Home","UK Map","A-Z","Links","About Us","Contact Us","Terms and Conditions","CastlesFortsBattles.co.uk","BattlefieldsofBritain.co.uk","A-C","D-G","H-L","M-R","S-Z"}
    blocks=[];seen=set()
    for e in clone.find_all(["h1","h2","h3","h4","p","li"]):
      tx=ftfy.fix_text(" ".join(e.stripped_strings).strip())
      key=re.sub(r"\s+"," ",tx).casefold()
      if not tx or tx in nav or tx.lower() in ("tweet","share","follow") or key in seen:continue
      seen.add(key);blocks.append((e.name,tx))
    return blocks

def render(p,blocks,rows,total,missing):
    body=[]
    headish=re.compile(r"^(History|Historical Background|Design|Gallery|Bibliography|What.?s There|Getting There|Location|Access|Visiting|Origins|Norman|Medieval|Tudor|Civil War|Later History|Description|Keep|Gatehouse|Earthworks|Castle)",re.I)
    for tag,tx in blocks:
      if tag.startswith("h") or (len(tx)<105 and headish.match(tx)):body.append(f"<h2>{H.escape(tx)}</h2>")
      elif tag=="li":body.append(f"<p>• {H.escape(tx)}</p>")
      else:body.append(f"<p>{H.escape(tx)}</p>")
    figs=[]
    order={x:i for i,x in enumerate(p["_exact"])}
    rows=sorted(rows,key=lambda x:order.get(x["identity"],999))
    for x in rows:
      label=x["identity"].replace("_"," ")
      q="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
      figs.append(f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" alt="{H.escape(p["name"])} archived original image"></a><figcaption>{H.escape(label+q)}</figcaption></figure>')
    note=f"Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. {len(rows)} of {total} identified original content-image positions have been recovered"
    if missing:note+=f"; {len(missing)} remain unavailable"
    note+=". No unrelated substitute photographs have been introduced."
    return ftfy.fix_text(f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(p["name"])} | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}@media(max-width:700px){{main{{padding:16px 10px 36px}}.note,article{{padding:15px}}}}</style></head><body><header><h1>{H.escape(p["name"])}</h1></header><main><div class="note">{H.escape(note)}</div><article>{''.join(body)}<h2>Recovered original photographs, plans and images</h2>{''.join(figs) if figs else '<p>No original image files could be recovered from the available archive captures.</p>'}</article><p><a href="../../atoz-archive.html">Back to A–Z index</a></p></main></body></html>''')

def recover_page(p):
    source_ts,corig,rawhtml=source_page(p)
    out=ROOT/p["slug"];imgdir=out/"images";imgdir.mkdir(parents=True,exist_ok=True)
    if not rawhtml:
      return {"name":p["name"],"slug":p["slug"],"status":"source-failed"}
    (out/"source.html").write_text(rawhtml,encoding="utf-8",errors="replace")
    soup=BeautifulSoup(rawhtml,"html.parser")
    desktop,exact=canonical_identities(soup,corig)
    p["_exact"]=exact
    groups=all_groups(soup,corig,exact)
    recovered={};missing=[]
    # Recover identities concurrently.
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
      fut={ex.submit(recover_identity,i,groups[i],source_ts,corig):i for i in exact}
      for f in cf.as_completed(fut):
        ident=fut[f]
        try:best=f.result()
        except Exception:best=None
        if not best:
          missing.append(ident);continue
        _,ts,u,method,b,z,exactfile=best
        ext=os.path.splitext(urlsplit(u).path)[1].lower()
        if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
        dest=imgdir/(ident+ext);dest.write_bytes(b)
        recovered[ident]={
          "identity":ident,"file":"images/"+dest.name,
          "archive_timestamp":ts,"archive_original":u,"method":method,
          "dimensions":[z[0],z[1]],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
          "quality":"full/near-full" if exactfile else "thumbnail/lower-resolution",
          "identification":"certain"
        }
    # One wildcard archive index pass can reveal captures whose source-page URLs were absent/broken.
    if missing:
      rows=wildcard_rows(p)
      mapped={i:[] for i in missing}
      for x in rows:
        u=x.get("original",""); ident=map_identity(stem(u),exact)
        if ident in mapped:mapped[ident].append(x)
      for ident in list(missing):
        cand=sorted(mapped[ident],key=lambda x:int(x.get("length") or 0),reverse=True)[:18]
        best=None
        for x in cand:
          r=get(raw(x["timestamp"],x["original"]),8)
          if not good_img(r):continue
          z=iminfo_bytes(r.content);st=stem(x["original"]);exactfile=(st==ident)
          variant=st.startswith(ident) and bool(DIMSUF.fullmatch(st[len(ident):]))
          if not exactfile and not variant:continue
          rank=(1 if exactfile else 0,z[0]*z[1],len(r.content))
          if best is None or rank>best[0]:best=(rank,x,r.content,z,exactfile)
        if best:
          _,x,b,z,exactfile=best
          ext=os.path.splitext(urlsplit(x["original"]).path)[1].lower()
          if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
          dest=imgdir/(ident+ext);dest.write_bytes(b)
          recovered[ident]={
            "identity":ident,"file":"images/"+dest.name,"archive_timestamp":x["timestamp"],
            "archive_original":x["original"],"method":"cdx-wildcard","dimensions":[z[0],z[1]],
            "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
            "quality":"full/near-full" if exactfile else "thumbnail/lower-resolution",
            "identification":"certain"
          }
          missing.remove(ident)
    rows=[recovered[i] for i in exact if i in recovered]
    blocks=extract_text(desktop)
    (out/"index.html").write_text(render(p,blocks,rows,len(exact),missing),encoding="utf-8")
    report={
      "name":p["name"],"status":"built","original_url":p["orig"],"supplied_capture":p["ts"],
      "source_timestamp_used":source_ts,"source_original_used":corig,
      "text_blocks_preserved":len(blocks),"original_image_positions_identified":len(exact),
      "desktop_image_identities":exact,
      "recovered_full_or_near_full":sum(x["quality"]=="full/near-full" for x in rows),
      "recovered_thumbnail_or_lower_resolution":sum(x["quality"]=="thumbnail/lower-resolution" for x in rows),
      "still_missing":len(missing),"uncertain_identifications":[],
      "images":rows,"missing":[{"identity":i,"candidate_urls":groups.get(i,[])} for i in missing],
      "counting_method":"Unique non-decorative content-image identities from the desktop source. Adobe Muse WIDTHxHEIGHT responsive variants are mapped to the underlying identity and not counted separately.",
      "verification_note":"Every displayed image was recovered from CastlesFortsBattles archive captures. No unrelated substitute photographs were used."
    }
    (out/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return {"name":p["name"],"slug":p["slug"],"status":"built","source":source_ts,
            "positions":len(exact),"full":report["recovered_full_or_near_full"],
            "lower":report["recovered_thumbnail_or_lower_resolution"],"missing":len(missing),
            "missing_identities":missing}

def update_indexes():
    replacements=0
    for path in INDEX_FILES:
      if not path.exists():continue
      s=path.read_text(encoding="utf-8")
      for p in PAGES:
        tail=urlsplit(p["orig"]).path
        # Replace any archived/direct href whose target contains the original path.
        pat=r'href="[^"]*'+re.escape(tail)+r'"'
        s,n=re.subn(pat,f'href="recovered/{p["slug"]}/"',s,flags=re.I)
        replacements+=n
      path.write_text(s,encoding="utf-8")
    return replacements

results=[]
def run_one(p):
    print("AUDITING",p["name"],flush=True)
    try:r=recover_page(p)
    except Exception as e:r={"name":p["name"],"slug":p["slug"],"status":"error","error":repr(e)}
    print(json.dumps(r,ensure_ascii=False),flush=True)
    return r
with cf.ThreadPoolExecutor(max_workers=5) as ex:
    futs={ex.submit(run_one,p):p for p in PAGES}
    byslug={}
    for fut in cf.as_completed(futs):
        r=fut.result();byslug[r["slug"]]=r
results=[byslug[p["slug"]] for p in PAGES]
repl=update_indexes()
summary={"pages":results,"index_links_replaced":repl}
(AUD/"castle-image-audit-batch-2026-09-13.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps(summary,indent=2,ensure_ascii=False))
