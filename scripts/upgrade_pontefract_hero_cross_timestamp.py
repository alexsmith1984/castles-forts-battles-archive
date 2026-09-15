#!/usr/bin/env python3
import io, json, hashlib, time
from pathlib import Path
import requests
from PIL import Image

ROOT = Path("recovered/pontefract-castle")
REP = ROOT / "recovery-report.json"
IMG = ROOT / "images"
IDENTITY = "pontefract_castle15"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 PontefractCrossTimestampHeroRecovery"

def get(url, timeout=12):
    r = None
    for n in range(3):
        try:
            r = S.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
        except Exception:
            r = None
        time.sleep(0.7 * (n + 1))
    return r

def image_info(data):
    try:
        im = Image.open(io.BytesIO(data))
        z = (im.width, im.height, im.format)
        im.verify()
        if z[0] < 100 or z[1] < 100:
            return None
        return z
    except Exception:
        return None

def replay_probes(original):
    return [
        "https://web.archive.org/web/2id_/" + original,
        "https://web.archive.org/web/0id_/" + original,
        "https://web.archive.org/web/20221231235959id_/" + original,
        "https://web.archive.org/web/20210918010514id_/" + original,
        "https://web.archive.org/web/20191231235959id_/" + original,
        "https://web.archive.org/web/20181231235959id_/" + original,
        "https://web.archive.org/web/20161231235959id_/" + original,
        "https://web.archive.org/web/20141231235959id_/" + original,
    ]

def archive_timestamp(final_url):
    marker = "/web/"
    if marker not in final_url:
        return "nearest-surviving-capture"
    tail = final_url.split(marker, 1)[1]
    token = tail.split("/", 1)[0].replace("id_", "").replace("im_", "")
    digits = "".join(ch for ch in token if ch.isdigit())
    return digits[:14] if len(digits) >= 14 else "nearest-surviving-capture"

report = json.loads(REP.read_text())
images = {x["identity"]: x for x in report.get("images", [])}
current = images.get(IDENTITY)
current_area = 0
current_sha = None
if current:
    dims = current.get("dimensions") or [0, 0]
    current_area = int(dims[0]) * int(dims[1])
    current_sha = current.get("sha256")

exact_leafs = [
    "Pontefract_Castle15.JPG",
    "Pontefract_Castle15.jpg",
    "pontefract_castle15.JPG",
    "pontefract_castle15.jpg",
]
candidates = []
for scheme in ("http", "https"):
    for host in ("www.castlesfortsbattles.co.uk", "castlesfortsbattles.co.uk"):
        for prefix in ("", "yorkshire/", "m/"):
            for leaf in exact_leafs:
                u = f"{scheme}://{host}/{prefix}{leaf}"
                if u not in candidates:
                    candidates.append(u)

attempts = []
best = None
for original in candidates:
    for probe in replay_probes(original):
        resp = get(probe, 10)
        rec = {"original": original, "probe": probe}
        if not resp:
            rec["result"] = "request-failed"
            attempts.append(rec)
            continue
        rec["status"] = resp.status_code
        rec["final_url"] = resp.url
        if resp.status_code != 200:
            rec["result"] = "not-found"
            attempts.append(rec)
            continue
        z = image_info(resp.content)
        if not z:
            rec["result"] = "not-decodable-image"
            attempts.append(rec)
            continue
        sha = hashlib.sha256(resp.content).hexdigest()
        area = z[0] * z[1]
        rec.update({"result": "decoded-image", "dimensions": [z[0], z[1]], "format": z[2], "bytes": len(resp.content), "sha256": sha})
        attempts.append(rec)
        # Only call this an upgrade if the archived original URL yields a larger image
        # than the surviving 920x372 WebPlus display export (or no current copy exists).
        if sha != current_sha and area > current_area:
            score = area
            if best is None or score > best[0]:
                best = (score, original, resp.url, resp.content, z, sha)

upgraded = False
if best:
    _, original, final_url, data, z, sha = best
    ext = ".png" if z[2] == "PNG" else ".jpg"
    path = IMG / (IDENTITY + ext)
    path.write_bytes(data)
    images[IDENTITY] = {
        "identity": IDENTITY,
        "file": "images/" + path.name,
        "archive_timestamp": archive_timestamp(final_url),
        "archive_original": original,
        "archive_replay": final_url,
        "method": "wayback-cross-timestamp-original-href-replay",
        "dimensions": [z[0], z[1]],
        "format": z[2],
        "bytes": len(data),
        "sha256": sha,
        "quality": "full/near-full",
        "identification": "certain",
    }
    upgraded = True

order = report["desktop_image_identities"]
report["images"] = [images[i] for i in order if i in images]
report["recovered_full_or_near_full"] = sum(x.get("quality") == "full/near-full" for x in report["images"])
report["recovered_thumbnail_or_lower_resolution"] = sum(x.get("quality") != "full/near-full" for x in report["images"])
report["still_missing"] = len(order) - len(report["images"])
report["status"] = "COMPLETE" if report["still_missing"] == 0 else "PARTIAL"
report["cross_timestamp_hero_upgrade_2026_09_15"] = {
    "completed": True,
    "source_original_href": "http://www.castlesfortsbattles.co.uk/Pontefract_Castle15.JPG",
    "candidate_original_urls_checked": len(candidates),
    "probe_count": len(attempts),
    "upgraded": upgraded,
    "best_surviving_version": images.get(IDENTITY),
}
REP.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({
    "upgraded": upgraded,
    "hero": images.get(IDENTITY),
    "full": report["recovered_full_or_near_full"],
    "lower": report["recovered_thumbnail_or_lower_resolution"],
    "missing": report["still_missing"],
}, indent=2))
