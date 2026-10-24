"""Student feature worker: per-frame vision (4 fps) + per-hop audio (1 s / 250 ms) embeddings."""
import json
import os
import sys
import time
import traceback

import numpy as np
import torch

from common import FEATS, MARK, TEACHER, progress, read_manifest
from encoders import ENC_INFO, AudioEnc, VisionEnc, audio_windows, read_audio, read_frames

dev = "cuda"
venc = VisionEnc().to(dev).eval().half()
aenc = AudioEnc().to(dev).eval()
(FEATS / "encoders.json").write_text(json.dumps(ENC_INFO, indent=1, default=str))
print("encoders", ENC_INFO, flush=True)
labeled_only = "--labeled-only" in sys.argv
stats = dict(done=0, failed=0, last_error=None)
while True:
    m = read_manifest()
    todo = [r for r in m.itertuples() if not (FEATS / r.dataset / f"{r.clip_id}.npz").exists()]
    if labeled_only:
        todo = [r for r in todo if (TEACHER / r.dataset / f"{r.clip_id}.npz").exists()]
    if not todo:
        if labeled_only or (MARK / "prep_done").exists() or (MARK / "stop_features").exists():
            break
        time.sleep(10)
        continue
    for r in todo:
        if (MARK / "stop_features").exists() and not labeled_only:
            break
        out = FEATS / r.dataset / f"{r.clip_id}.npz"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with torch.no_grad():
                fr = read_frames(r.path)
                vis = torch.cat([venc(fr[i:i + 64].to(dev).half()).float().cpu() for i in range(0, len(fr), 64)])
                wav = read_audio(r.path)
                if len(wav) == 0:
                    wav = torch.zeros(int(32000 * max(1, len(fr) / 4)))
                mel = aenc.front(audio_windows(wav).to(dev))
                aud = torch.cat([aenc(mel[i:i + 128].to(dev)).float().cpu() for i in range(0, len(mel), 128)])
            np.savez(out.with_suffix(".tmp.npz"), vis=vis.numpy().astype(np.float16), aud=aud.numpy().astype(np.float16))
            os.replace(out.with_suffix(".tmp.npz"), out)
            stats["done"] += 1
        except Exception:
            stats["failed"] += 1
            stats["last_error"] = traceback.format_exc()[-800:]
            print(stats["last_error"], flush=True)
        if (stats["done"] + stats["failed"]) % 10 == 0:
            progress("student_features", **stats)
progress("student_features", **stats, finished=True)
