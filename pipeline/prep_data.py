"""Download TikHarm (Harmful + Safe only) on the pod, cut one 10 s window per video,
normalize with ffmpeg, and append rows to the manifest in queue order.

LIRIS-ACCEDE is not on the volume, so per the handoff fallback TikHarm is used for
distillation AND the stress readout, with a held-out split grouped by uploader.
"""
import csv
import hashlib
import json
import os
import random
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import CLIPS, LOGS, MANIFEST, W, progress

MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "1200"))
N_DEMO = 8
WIN = 10.0
TOKEN = os.environ.get("KAGGLE_API_TOKEN") or os.environ.get("KAGGLE_KEY")
H = {"Authorization": f"Bearer {TOKEN}"}
DS = "anhoangvo/tikharm-dataset"
RAW = Path("/root/raw")
RAW.mkdir(parents=True, exist_ok=True)
COLS = ["clip_id", "dataset", "source_group", "path", "duration_s", "valence", "arousal",
        "stress_label", "split", "prio", "orig_split", "orig_class", "src_file"]
lock = threading.Lock()


def list_files():
    files, tok = [], None
    while True:
        u = f"https://www.kaggle.com/api/v1/datasets/list/{DS}?pageSize=200"
        if tok:
            u += "&pageToken=" + urllib.parse.quote(tok)
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60))
        files += [(f["name"], f["totalBytes"]) for f in d["datasetFiles"]]
        tok = d.get("nextPageTokenNullable")
        if not tok:
            return files


def download(name, dest: Path):
    url = f"https://www.kaggle.com/api/v1/datasets/download/{DS}/" + urllib.parse.quote(name, safe="")
    tmp = dest.with_suffix(".part")
    err = None
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            with open(tmp, "rb") as f:
                head = f.read(2)
            if head == b"PK":  # sometimes served zipped
                with zipfile.ZipFile(tmp) as z:
                    inner = z.namelist()[0]
                    with z.open(inner) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
                tmp.unlink()
            else:
                os.replace(tmp, dest)
            return True
        except Exception as e:
            err = e
            time.sleep(min(60, 5 * 2 ** attempt) if "429" in str(e) else 2)  # Kaggle rate limit
    raise RuntimeError(f"download failed {name}: {err}")


def probe_duration(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def normalize(src: Path, mp4: Path, wav: Path):
    dur = probe_duration(src)
    start = max(0.0, min(3.0, dur - WIN))
    vf = "scale='if(gt(iw,ih),-2,256)':'if(gt(iw,ih),256,-2)',fps=24,format=yuv420p"
    base = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{WIN}", "-i", str(src)]
    r = subprocess.run(base + ["-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                               "-crf", "23", "-c:a", "aac", "-ac", "1", "-ar", "16000", "-movflags", "+faststart", str(mp4)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not wav.exists():  # no audio track: silent wav keeps all pipelines aligned
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t",
                        f"{probe_duration(mp4):.2f}", str(wav)], check=True)
    return probe_duration(mp4)


def append_row(row):
    with lock:
        new = not MANIFEST.exists()
        with open(MANIFEST, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerow(row)


def main():
    files = list_files()
    vids = [(n, s) for n, s in files if n.lower().endswith(".mp4")
            and n.split("/")[2] in ("Harmful Content", "Safe")]
    print(f"TikHarm Harmful+Safe videos: {len(vids)}")
    rng = random.Random(0)

    def group(n):  # uploader = filename up to the last "_<videoid>"
        stem = Path(n).stem
        return stem.rsplit("_", 1)[0].lstrip(".") or stem

    groups = sorted({group(n) for n, _ in vids})
    rng.shuffle(groups)
    gsplit = {}
    for i, g in enumerate(groups):
        f = i / len(groups)
        gsplit[g] = "train" if f < 0.70 else ("val" if f < 0.85 else "test")

    items = []
    for n, s in vids:
        cls = n.split("/")[2]
        vid = Path(n).stem.rsplit("_", 1)[-1]
        cid = "th_" + vid[-12:] + "_" + hashlib.md5(n.encode()).hexdigest()[:6]
        items.append(dict(name=n, size=s, cls=cls, orig_split=n.split("/")[1], group=group(n),
                          split=gsplit[group(n)], label=1 if cls == "Harmful Content" else 0, cid=cid))

    # demo: user-uploaded clips if any, else 8 held-out test clips (4 harmful, 4 safe, small files first)
    demo_dir = W / "data/raw/demo"
    user_demo = sorted(p for p in demo_dir.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi")) if demo_dir.exists() else []
    queue = []
    if not user_demo:
        for lab in (1, 0):
            cand = sorted([it for it in items if it["split"] == "test" and it["label"] == lab], key=lambda x: x["size"])
            cand = [c for c in cand if c["size"] > 300_000][: N_DEMO // 2]
            for c in cand:
                c["demo"] = True
            queue += cand
    rest = [it for it in items if not it.get("demo")]
    rng.shuffle(rest)
    # interleave labels so any prefix of the queue is balanced
    pos = [x for x in rest if x["label"] == 1]
    neg = [x for x in rest if x["label"] == 0]
    inter = [x for pair in zip(pos, neg) for x in pair]
    queue += inter[: MAX_VIDEOS]

    out_dir = CLIPS / "tikharm"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = set()
    if MANIFEST.exists():
        import pandas as pd
        done = set(pd.read_csv(MANIFEST).clip_id)
    stats = dict(done=len(done), total=len(queue) + len(user_demo), failed=0, last_error=None)

    prio = 0
    for p in user_demo:  # user demo clips first
        cid = "demo_" + p.stem.replace(" ", "_")[:40]
        if cid in done:
            continue
        d = CLIPS / "demo"
        d.mkdir(parents=True, exist_ok=True)
        try:
            dur = normalize(p, d / f"{cid}.mp4", d / f"{cid}.wav")
            append_row(dict(clip_id=cid, dataset="demo", source_group=cid, path=str(d / f"{cid}.mp4"), duration_s=dur,
                            valence="", arousal="", stress_label="", split="test", prio=prio, orig_split="",
                            orig_class="", src_file=str(p)))
        except Exception as e:
            print("demo fail", p, e)
        prio += 1

    def work(args):
        prio, it = args
        if it["cid"] in done:
            return
        dataset = "demo" if it.get("demo") else "tikharm"
        d = CLIPS / dataset
        d.mkdir(parents=True, exist_ok=True)
        src = RAW / (it["cid"] + ".mp4")
        try:
            download(it["name"], src)
            dur = normalize(src, d / f"{it['cid']}.mp4", d / f"{it['cid']}.wav")
            src.unlink(missing_ok=True)
            append_row(dict(clip_id=it["cid"], dataset=dataset, source_group=it["group"], path=str(d / f"{it['cid']}.mp4"),
                            duration_s=round(dur, 2), valence="", arousal="", stress_label=it["label"],
                            split="test" if dataset == "demo" else it["split"], prio=prio,
                            orig_split=it["orig_split"], orig_class=it["cls"], src_file=it["name"]))
            stats["done"] += 1
        except Exception as e:
            stats["failed"] += 1
            stats["last_error"] = str(e)[-300:]
        if (stats["done"] + stats["failed"]) % 10 == 0:
            progress("prep", **stats)

    # demo clips first and in order, then the rest in parallel (roughly in queue order)
    for i, it in enumerate(queue[: len([q for q in queue if q.get("demo")])]):
        work((prio + i, it))
    (W / "markers/demo_ready").touch()
    base = prio + len([q for q in queue if q.get("demo")])
    rest_q = [q for q in queue if not q.get("demo")]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(work, [(base + i, it) for i, it in enumerate(rest_q)]))
    progress("prep", **stats, finished=True)
    (W / "markers/prep_done").touch()
    print("prep done", stats)


if __name__ == "__main__":
    main()
