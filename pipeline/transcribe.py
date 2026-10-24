"""Persistent WhisperX worker. Produces <clip>.tsv next to <clip>.wav in exactly the
format tribev2.eventstransforms.ExtractWordsFromAudio writes, so TRIBE reads the cached
transcript instead of launching `uvx whisperx` (and reloading large-v3) per clip.
Same settings as TRIBE's CLI call: large-v3, language en, float16, batch 16,
align model WAV2VEC2_ASR_LARGE_LV60K_960H."""
import os
import time
import traceback
from pathlib import Path

import pandas as pd

from common import LOGS, MARK, claim, progress, read_manifest, teacher_time_left

import whisperx

dev = "cuda"
model = whisperx.load_model("large-v3", dev, compute_type="float16", language="en")
align_model, meta = whisperx.load_align_model(language_code="en", device=dev,
                                              model_name="WAV2VEC2_ASR_LARGE_LV60K_960H")
print("whisperx loaded", flush=True)
CLAIMS = MARK / "tsv_claims"
n_done = n_fail = 0
last_err = None
while teacher_time_left() > 0:
    m = read_manifest()
    todo = []
    for r in m.itertuples():
        wav = Path(r.path).with_suffix(".wav")
        tsv = wav.with_suffix(".tsv")
        if wav.exists() and not tsv.exists():
            todo.append((r.clip_id, wav, tsv))
    if not todo:
        if (MARK / "prep_done").exists():
            break
        time.sleep(10)
        continue
    for cid, wav, tsv in todo[:50]:
        if teacher_time_left() <= 0:
            break
        if not claim(CLAIMS, cid):
            continue
        t0 = time.time()
        try:
            audio = whisperx.load_audio(str(wav))
            res = model.transcribe(audio, batch_size=16, language="en")
            words = []
            if res["segments"]:
                res = whisperx.align(res["segments"], align_model, meta, audio, dev, return_char_alignments=False)
                for i, seg in enumerate(res["segments"]):
                    sentence = seg["text"].replace('"', "")
                    for w in seg.get("words", []):
                        if "start" not in w:
                            continue
                        words.append(dict(text=w["word"].replace('"', ""), start=w["start"],
                                          duration=w["end"] - w["start"], sequence_id=i, sentence=sentence))
            tmp = tsv.with_suffix(".tsv.tmp")
            if words:
                pd.DataFrame(words).to_csv(tmp, sep="\t", index=False)
            else:
                tmp.write_text("")  # TRIBE treats an empty file as "no words"
            os.replace(tmp, tsv)
            n_done += 1
        except Exception:
            n_fail += 1
            last_err = traceback.format_exc()[-400:]
            tsv.write_text("")
        progress(f"transcribe_{os.environ.get('ROLE')}", done=n_done, failed=n_fail,
                 last_s=round(time.time() - t0, 2), last_error=last_err)
print("transcribe worker exit", n_done, n_fail)
