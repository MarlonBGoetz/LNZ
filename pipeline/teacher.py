"""TRIBE v2 teacher worker (full trimodal). Resumable, shares the queue across pods via
atomic claim files. Writes teacher/<dataset>/<clip_id>.npz."""
import os
import shutil
import time
import traceback
from pathlib import Path

import numpy as np
import torch

from common import LLAMA, MARK, TEACHER, TRIBE_COMMIT, claim, load_atlas, progress, read_manifest, teacher_time_left

import subprocess
import sys

from common import LOGS

ROLE = os.environ.get("ROLE", "?")
# Each TRIBE worker peaks at ~11 GB, so several fit on one 80 GB H100.
NW = int(os.environ.get("TEACHER_WORKERS", "3"))
WID = os.environ.get("WID")
if WID is None:
    running = subprocess.run(["pgrep", "-fc", "teacher.py"], capture_output=True, text=True).stdout.strip()
    n_running = int(running or 1)  # includes this process
    for i in range(1, NW):
        if n_running - 1 >= NW - 1:
            break  # children from an earlier launch are still alive
        subprocess.Popen([sys.executable, __file__], env={**os.environ, "WID": str(i)},
                         stdout=open(LOGS / f"teacher_{ROLE}_w{i}.log", "a"), stderr=subprocess.STDOUT)
        n_running += 1
    WID = "0"
CACHE = Path(f"/root/tribe_cache_{WID}")
# neuralset only accepts model names on its HF whitelist; register the verified local Llama copy.
import neuralset.extractors.base as _nb
_wl = Path(_nb.__file__).with_name("data") / "huggingface-repos.txt"
_txt = _wl.read_text("utf8")
if str(LLAMA) not in _txt.splitlines():
    _wl.write_text(_txt.rstrip("\n") + "\n" + str(LLAMA) + "\n", "utf8")
from tribev2 import TribeModel

t0 = time.time()
model = TribeModel.from_pretrained(
    "facebook/tribev2", cache_folder=str(CACHE),
    config_update={"data.text_feature.model_name": str(LLAMA)},
)
print(f"TRIBE loaded in {time.time()-t0:.0f}s", flush=True)
atlas = load_atlas()
PM = atlas["parcel_masks"].astype(np.float32)
PM /= PM.sum(1, keepdims=True)
RM = atlas["roi_masks"].astype(np.float32)
RM /= RM.sum(1, keepdims=True)
CLAIMS = MARK / "teacher_claims"
stats = dict(role=ROLE, done=0, failed=0, skipped_existing=0, times=[], last_error=None)


def whisper_alive():
    return not (MARK / f"whisper_dead_{ROLE}").exists()


while teacher_time_left() > 0:
    m = read_manifest()
    picked = None
    for r in m.itertuples():
        out = TEACHER / r.dataset / f"{r.clip_id}.npz"
        if out.exists():
            continue
        tsv = Path(r.path).with_suffix(".tsv")
        if not tsv.exists():
            if whisper_alive():
                continue  # wait for the transcript; take the next ready clip
            tsv.write_text("")  # whisper is down: run without words, record it
        if claim(CLAIMS, r.clip_id):
            picked = r
            break
    if picked is None:
        if (MARK / "prep_done").exists() and all(
                (TEACHER / r.dataset / f"{r.clip_id}.npz").exists() or (CLAIMS / r.clip_id).exists() for r in m.itertuples()):
            break
        time.sleep(5)
        continue
    r = picked
    out = TEACHER / r.dataset / f"{r.clip_id}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    try:
        tsv = Path(r.path).with_suffix(".tsv")
        text_on = tsv.exists() and tsv.stat().st_size > 0
        df = model.get_events_dataframe(video_path=r.path)
        preds, segs = model.predict(events=df, verbose=False)
        preds = np.asarray(preds, dtype=np.float32)
        t_start = np.array([float(s.start) for s in segs], dtype=np.float32)
        order = np.argsort(t_start)
        preds, t_start = preds[order], t_start[order]
        np.savez(out.with_suffix(".tmp.npz"),
                 vertices=preds.astype(np.float16), parcels=preds @ PM.T, roi=preds @ RM.T, t_start=t_start,
                 parcel_names=np.array(atlas["parcel_names"]), roi_names=np.array(atlas["roi_names"]),
                 tribe_commit=TRIBE_COMMIT, text_pathway=bool(text_on), n_words=int(sum(df.type == "Word")),
                 runtime_s=time.time() - ts)
        os.replace(out.with_suffix(".tmp.npz"), out)
        stats["done"] += 1
        stats["times"] = (stats["times"] + [round(time.time() - ts, 1)])[-50:]
        stats["shape"] = list(preds.shape)
    except Exception:
        stats["failed"] += 1
        stats["last_error"] = traceback.format_exc()[-1500:]
        print(stats["last_error"], flush=True)
    stats["peak_mem_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 1)
    tt = stats["times"]
    stats["sec_per_clip"] = round(float(np.median(tt)), 1) if tt else None
    stats["clips_per_hour"] = round(3600 / np.median(tt)) if tt else None
    progress(f"teacher_{ROLE}{WID}", **stats, time_left_s=int(teacher_time_left()))
    stats["cache_disk_free_gb"] = round(shutil.disk_usage("/root").free / 1e9, 1)
print("teacher exit", stats)
