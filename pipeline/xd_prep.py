"""XD-Violence (test set: 800 videos with frame-level violence annotations) -> 10 s windows.

Three kinds of windows, all appended to the shared manifest ahead of everything else:
  onset   : starts 3 s before the first annotated violent event (stress_label 1)
  calm    : a stretch of the SAME violent video with no annotated violence (stress_label 0)
  normal  : a window from a fully non-violent (label_A) video (stress_label 0)
Same-video calm windows control for style/language, so the stress readout can't just learn
"what kind of video is this". Splits are grouped by source video (name before "__#").
"""
import csv
import hashlib
import json
import os
import random
import subprocess
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from common import CLIPS, MANIFEST, W, progress

SHARE = ("https://stuxidianeducn-my.sharepoint.com/:u:/g/personal/pengwu_stu_xidian_edu_cn/"
         "EdewYQSko-BHpew03RBfGLQBIAOUdF7jt1rC71rK5iBGag?e=v4Enay")
ANNOT = "https://roc-ng.github.io/XD-Violence/images/annotations.txt"
RAW = Path("/root/xd"); RAW.mkdir(parents=True, exist_ok=True)
ZIP = RAW / "videos.zip"
N_EACH = int(os.environ.get("XD_N_EACH", "130"))  # windows per kind
N_DEMO = 8
WIN, PRE = 10.0, 3.0
COLS = ["clip_id", "dataset", "source_group", "path", "duration_s", "valence", "arousal",
        "stress_label", "split", "prio", "orig_split", "orig_class", "src_file", "violent_secs", "onset_s", "kind"]
lock = threading.Lock()


def download_zip():
    if ZIP.exists() and ZIP.stat().st_size > 10_000_000_000:
        return
    s = requests.Session()
    s.get(SHARE, timeout=60)  # sets the OneDrive session cookie
    url = SHARE + "&download=1"
    total = int(s.get(url, headers={"Range": "bytes=0-0"}, timeout=60).headers["Content-Range"].split("/")[1])
    n = 16
    parts = [(i * total // n, (i + 1) * total // n - 1) for i in range(n)]
    with open(ZIP, "wb") as f:
        f.truncate(total)
    got = [0] * n

    def part(i):
        a, b = parts[i]
        for attempt in range(6):
            try:
                pos = a + got[i]
                r = s.get(url, headers={"Range": f"bytes={pos}-{b}"}, stream=True, timeout=120)
                with open(ZIP, "r+b") as f:
                    f.seek(pos)
                    for chunk in r.iter_content(1 << 22):
                        f.write(chunk); got[i] += len(chunk)
                if a + got[i] > b:
                    return
            except Exception as e:
                print("part", i, "retry", e, flush=True); time.sleep(3)
        raise RuntimeError(f"zip part {i} failed")

    t0 = time.time()
    with ThreadPoolExecutor(n) as ex:
        futs = [ex.submit(part, i) for i in range(n)]
        while not all(f.done() for f in futs):
            time.sleep(10)
            progress("xd_prep", stage="download", gb=round(sum(got) / 1e9, 2), total_gb=round(total / 1e9, 2),
                     mb_s=round(sum(got) / 1e6 / (time.time() - t0), 1))
        for f in futs:
            f.result()


def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate:format=duration", "-of", "json", str(p)], capture_output=True, text=True).stdout
    d = json.loads(out or "{}")
    num, den = (d.get("streams", [{}])[0].get("r_frame_rate", "24/1")).split("/")
    return float(d.get("format", {}).get("duration", 0)), float(num) / float(den or 1)


def cut(src, start, mp4, wav):
    vf = "scale='if(gt(iw,ih),-2,256)':'if(gt(iw,ih),256,-2)',fps=24,format=yuv420p"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{WIN}", "-i", str(src),
                        "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-c:a", "aac", "-ac", "1", "-ar", "16000", "-movflags", "+faststart", str(mp4)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not wav.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", f"{WIN}", str(wav)], check=True)
    return probe(mp4)[0]


def widen_manifest():
    """Add the XD columns to the existing TikHarm manifest once, atomically."""
    if MANIFEST.exists():
        with open(MANIFEST) as f:
            head = f.readline().strip().split(",")
        if head != COLS:
            import pandas as pd
            tmp = MANIFEST.with_suffix(".tmp")
            pd.read_csv(MANIFEST).reindex(columns=COLS).to_csv(tmp, index=False)
            os.replace(tmp, MANIFEST)


def append(row):
    with lock:
        new = not MANIFEST.exists()
        with open(MANIFEST, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerow(row)


def main():
    ann = {}
    for line in urllib.request.urlopen(ANNOT, timeout=60).read().decode().splitlines():
        p = line.split()
        if len(p) >= 3:
            fr = list(map(int, p[1:]))
            ann[p[0]] = list(zip(fr[0::2], fr[1::2]))
    print("annotated violent test videos:", len(ann), flush=True)
    widen_manifest()
    download_zip()
    z = zipfile.ZipFile(ZIP)
    names = [n for n in z.namelist() if n.lower().endswith(".mp4")]
    stem = lambda n: Path(n).stem
    violent = [n for n in names if stem(n) in ann]
    normal = [n for n in names if "label_A" in stem(n)]
    print(f"zip videos {len(names)}: violent(annotated) {len(violent)}, normal {len(normal)}", flush=True)
    rng = random.Random(0)
    group = lambda n: stem(n).split("__#")[0]
    groups = sorted({group(n) for n in violent + normal}); rng.shuffle(groups)
    gsplit = {g: ("train" if i / len(groups) < 0.70 else "val" if i / len(groups) < 0.85 else "test") for i, g in enumerate(groups)}
    rng.shuffle(violent); rng.shuffle(normal)

    jobs = []
    for n in violent[:N_EACH + N_DEMO]:
        jobs.append(("onset", n)); jobs.append(("calm", n))
    for n in normal[:N_EACH]:
        jobs.append(("normal", n))
    out = CLIPS / "xdv"; out.mkdir(parents=True, exist_ok=True)
    (CLIPS / "demo").mkdir(parents=True, exist_ok=True)
    done = set()
    if MANIFEST.exists():
        import pandas as pd
        done = set(pd.read_csv(MANIFEST).clip_id)
    stats = dict(stage="cut", done=0, skipped=0, failed=0, last_error=None)
    demo_left = [N_DEMO]

    def work(job):
        prio, (kind, n) = job
        cid = f"xd_{kind}_{hashlib.md5(n.encode()).hexdigest()[:10]}"
        if cid in done:
            return
        try:
            src = RAW / "v" / Path(n).name  # extracted up front, single-threaded
            dur, fps = probe(src)
            ev = [(a / fps, b / fps) for a, b in ann.get(stem(n), [])]
            if kind == "onset":
                start = max(0.0, min(ev[0][0] - PRE, dur - WIN))
            elif kind == "calm":
                gaps, prev = [], 0.0
                for a, b in sorted(ev) + [(dur, dur)]:
                    if a - prev >= WIN + 4:
                        gaps.append((prev + 2, a - 2))
                    prev = max(prev, b)
                if not gaps:
                    stats["skipped"] += 1
                    return
                g0, g1 = max(gaps, key=lambda g: g[1] - g[0])
                start = g0 + (g1 - g0 - WIN) / 2
            else:
                start = max(0.0, (dur - WIN) / 2)
            secs = [int(any(a < start + s + 1 and b > start + s for a, b in ev)) for s in range(int(WIN))]
            with lock:
                is_demo = kind == "onset" and demo_left[0] > 0 and gsplit[group(n)] == "test"
                if is_demo:
                    demo_left[0] -= 1
            ds = "demo" if is_demo else "xdv"
            d = CLIPS / ds
            dur_w = cut(src, start, d / f"{cid}.mp4", d / f"{cid}.wav")
            onset = round(ev[0][0] - start, 2) if kind == "onset" else ""
            append(dict(clip_id=cid, dataset=ds, source_group="xd:" + group(n), path=str(d / f"{cid}.mp4"),
                        duration_s=round(dur_w, 2), valence="", arousal="", stress_label=0 if kind != "onset" else 1,
                        split="test" if is_demo else gsplit[group(n)], prio=prio, orig_split="xd_test",
                        orig_class=stem(n).split("label_")[-1], src_file=n, violent_secs=json.dumps(secs),
                        onset_s=onset, kind=kind))
            stats["done"] += 1
        except Exception as e:
            stats["failed"] += 1; stats["last_error"] = str(e)[-300:]
        if (stats["done"] + stats["failed"]) % 10 == 0:
            progress("xd_prep", **stats)

    # XD goes to the very front of the teacher queue (TikHarm prios are >= 0); onset/calm/normal interleaved
    ordered = []
    on = [j for j in jobs if j[0] == "onset"]; ca = [j for j in jobs if j[0] == "calm"]; no = [j for j in jobs if j[0] == "normal"]
    for i in range(max(len(on), len(ca), len(no))):
        for lst in (on, ca, no):
            if i < len(lst):
                ordered.append(lst[i])
    # extract the chosen videos once (one zip handle, one thread), then cut windows in parallel
    (RAW / "v").mkdir(exist_ok=True)
    for i, n in enumerate(dict.fromkeys(n for _, n in ordered)):
        dst = RAW / "v" / Path(n).name
        if not dst.exists():
            with z.open(n) as a, open(dst, "wb") as b:
                while True:
                    buf = a.read(1 << 24)
                    if not buf:
                        break
                    b.write(buf)
        if i % 25 == 0:
            progress("xd_prep", stage="extract", n=i)
    with ThreadPoolExecutor(10) as ex:
        list(ex.map(work, [(-100000 + i, j) for i, j in enumerate(ordered)]))
    progress("xd_prep", **stats, finished=True)
    (W / "markers/xd_prep_done").touch()
    print("xd prep done", stats, flush=True)


if __name__ == "__main__":
    main()
