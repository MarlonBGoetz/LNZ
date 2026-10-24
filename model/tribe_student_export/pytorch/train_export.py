"""Train the student head on cached features vs TRIBE teacher labels, fit the stress
readout, evaluate, and export ONNX + demo JSON + README contract into /workspace/export."""
import json
import os
import shutil
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from common import EXPORT, FEATS, LLAMA, RUNS, TEACHER, TRIBE_COMMIT, W, load_atlas, read_manifest
from encoders import ENC_INFO, AudioEnc, VisionEnc, window_features

torch.manual_seed(0)
np.random.seed(0)
dev = "cuda" if torch.cuda.is_available() else "cpu"
RUN = RUNS / time.strftime("run_%H%M", time.gmtime())
RUN.mkdir(parents=True, exist_ok=True)
EXPORT.mkdir(parents=True, exist_ok=True)
(EXPORT / "demo").mkdir(exist_ok=True)
HIST_W = 3  # windows of history the head sees (t-2, t-1, t)
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


atlas = load_atlas()
P, K = len(atlas["parcel_names"]), len(atlas["roi_names"])
man = read_manifest()

# ---------------- assemble data ----------------
clips = []
for r in man.itertuples():
    tf, ff = TEACHER / r.dataset / f"{r.clip_id}.npz", FEATS / r.dataset / f"{r.clip_id}.npz"
    if not (tf.exists() and ff.exists()):
        continue
    try:
        t, f = np.load(tf), np.load(ff)
        vis, aud = torch.from_numpy(f["vis"].astype(np.float32)), torch.from_numpy(f["aud"].astype(np.float32))
        Tf = int(np.ceil(len(vis) / 4))
        X = window_features(vis, aud, Tf).numpy()
        keep = slice(0, -1) if len(t["t_start"]) > 3 else slice(None)  # drop TRIBE's end-of-clip edge spike
        ti = np.round(t["t_start"][keep]).astype(int)
        clips.append(dict(id=r.clip_id, dataset=r.dataset, split=r.split, label=r.stress_label, X=X, ti=ti,
                          path=r.path, uploader=r.source_group, orig_class=r.orig_class,
                          Yp=t["parcels"][keep].astype(np.float32), Yr=t["roi"][keep].astype(np.float32),
                          text=bool(t["text_pathway"])))
    except Exception as e:
        log("skip", r.clip_id, e)
log(f"clips with teacher+features: {len(clips)}")
counts = pd.DataFrame([(c["dataset"], c["split"], c["label"]) for c in clips], columns=["dataset", "split", "label"])
count_table = counts.groupby(["dataset", "split", "label"], dropna=False).size().reset_index(name="n")
log(count_table.to_string())
Dv = ENC_INFO_V = None
enc_info = json.loads((FEATS / "encoders.json").read_text())
Dv, Da = enc_info["vision"]["dim"], enc_info["audio"]["dim"]
F = clips[0]["X"].shape[1]
assert F == 3 * Dv + Da, (F, Dv, Da)
VIS_COLS, AUD_COLS = np.arange(0, 3 * Dv), np.arange(3 * Dv, F)

train = [c for c in clips if c["split"] == "train"]
val = [c for c in clips if c["split"] == "val"] or train[-max(1, len(train) // 8):]
test = [c for c in clips if c["split"] == "test" and c["dataset"] != "demo"]
demo = [c for c in clips if c["dataset"] == "demo"]
if not test:
    test = val
log(f"train {len(train)} val {len(val)} test {len(test)} demo {len(demo)}")


def pairs(cs, L):
    X, Yp, Yr = [], [], []
    for c in cs:
        T = len(c["X"])
        for j, tt in enumerate(c["ti"]):
            s = tt - L
            if 0 <= s < T:
                X.append(c["X"][s]); Yp.append(c["Yp"][j]); Yr.append(c["Yr"][j])
    return np.array(X), np.array(Yp), np.array(Yr)


def colr(a, b):
    a = a - a.mean(0); b = b - b.mean(0)
    return (a * b).sum(0) / (np.sqrt((a * a).sum(0) * (b * b).sum(0)) + 1e-8)


# ---------------- lag estimate (ridge, train -> val) ----------------
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

lag_scores = {}
for L in range(0, 6):
    Xtr, Ytr, _ = pairs(train, L)
    Xva, Yva, _ = pairs(val, L)
    if len(Xtr) < 20 or len(Xva) < 5:
        continue
    sc = StandardScaler().fit(Xtr)
    rg = Ridge(alpha=1000.0).fit(sc.transform(Xtr), Ytr)
    lag_scores[L] = float(np.nanmean(colr(rg.predict(sc.transform(Xva)), Yva)))
LAG = max(lag_scores, key=lag_scores.get) if lag_scores else 0
log("lag scores (val mean parcel r):", lag_scores, "-> lag", LAG)


# ---------------- student head ----------------
class Head(nn.Module):
    def __init__(self, F, out, hid=512, mask=None):
        super().__init__()
        self.register_buffer("xm", torch.zeros(F)); self.register_buffer("xs", torch.ones(F))
        self.register_buffer("ym", torch.zeros(out)); self.register_buffer("ys", torch.ones(out))
        self.register_buffer("mask", torch.ones(F) if mask is None else mask)
        self.fc1 = nn.Sequential(nn.Linear(F, hid), nn.GELU(), nn.Dropout(0.2))
        self.conv = nn.Conv1d(hid, hid, kernel_size=HIST_W)
        self.fc2 = nn.Sequential(nn.GELU(), nn.Dropout(0.1), nn.Linear(hid, hid), nn.GELU(), nn.Linear(hid, out))

    def forward(self, x, denorm=True):  # x (B,T,F) -> (B,T,out); causal over T
        h = self.fc1((x - self.xm) / self.xs * self.mask)
        h = h.transpose(1, 2)
        h = torch.cat([h[:, :, :1].expand(-1, -1, HIST_W - 1), h], 2)  # replicate-pad the past
        h = self.conv(h).transpose(1, 2)
        y = self.fc2(h)
        return y * self.ys + self.ym if denorm else y


def seq_batch(cs, L):
    T = max(len(c["X"]) for c in cs)
    X = np.zeros((len(cs), T, F), np.float32)
    Y = np.zeros((len(cs), T, P + K), np.float32)
    M = np.zeros((len(cs), T), np.float32)
    for i, c in enumerate(cs):
        X[i, :len(c["X"])] = c["X"]
        X[i, len(c["X"]):] = c["X"][-1]
        for j, tt in enumerate(c["ti"]):
            s = tt - L
            if 0 <= s < len(c["X"]):
                Y[i, s] = np.concatenate([c["Yp"][j], c["Yr"][j]]); M[i, s] = 1
    return [torch.from_numpy(a).to(dev) for a in (X, Y, M)]


def train_head(mask_cols=None, steps=600, tag="both"):
    Xtr, Ytr, Mtr = seq_batch(train, LAG)
    Xva, Yva, Mva = seq_batch(val, LAG)
    flat = Xtr[Mtr > 0]
    yflat = Ytr[Mtr > 0]
    mask = torch.ones(F, device=dev)
    if mask_cols is not None:
        mask[torch.as_tensor(mask_cols, device=dev)] = 0
    net = Head(F, P + K, mask=mask).to(dev)
    net.xm.copy_(flat.mean(0)); net.xs.copy_(flat.std(0) + 1e-4)
    net.ym.copy_(yflat.mean(0)); net.ys.copy_(yflat.std(0) + 1e-6)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=0.05)
    wts = torch.ones(P + K, device=dev); wts[P:] = 0.5 * P / K  # ROI aux weight
    best, best_state = -9, None

    def loss_fn(pred, Y, M):
        Yz = (Y - net.ym) / net.ys
        m = M.unsqueeze(-1)
        mse = (((pred - Yz) ** 2) * m).sum((0, 1)) / m.sum()
        pv, yv = pred[M > 0], Yz[M > 0]
        pv = pv - pv.mean(0); yv = yv - yv.mean(0)
        r = (pv * yv).sum(0) / (pv.norm(dim=0) * yv.norm(dim=0) + 1e-6)
        return ((mse + (1 - r)) * wts).sum() / wts.sum()

    for step in range(steps):
        net.train()
        idx = torch.randperm(len(Xtr), device=dev)[:256]
        loss = loss_fn(net(Xtr[idx], denorm=False), Ytr[idx], Mtr[idx])
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 25 == 0 or step == steps - 1:
            net.eval()
            with torch.no_grad():
                pv = net(Xva)[Mva > 0].cpu().numpy()
            r = float(np.nanmean(colr(pv[:, :P], Yva[Mva > 0][:, :P].cpu().numpy())))
            if r > best:
                best, best_state = r, {k: v.clone() for k, v in net.state_dict().items()}
    if best_state is not None:  # NaN val r every time -> keep the final weights
        net.load_state_dict(best_state)
    net.eval()
    log(f"[{tag}] best val parcel r = {best:.3f}")
    return net, best


def predict(net, c):
    with torch.no_grad():
        y = net(torch.from_numpy(c["X"]).unsqueeze(0).to(dev))[0].cpu().numpy()
    return y[:, :P], y[:, P:]


def eval_corr(net, cs):
    ps, ts, rs, trs = [], [], [], []
    for c in cs:
        pp, pr = predict(net, c)
        for j, tt in enumerate(c["ti"]):
            s = tt - LAG
            if 0 <= s < len(pp):
                ps.append(pp[s]); ts.append(c["Yp"][j]); rs.append(pr[s]); trs.append(c["Yr"][j])
    rp, rr = colr(np.array(ps), np.array(ts)), colr(np.array(rs), np.array(trs))
    return dict(parcel_r_mean=float(np.nanmean(rp)), parcel_r_median=float(np.nanmedian(rp)),
                roi_r={n: float(v) for n, v in zip(atlas["roi_names"], rr)}, n_timepoints=len(ps)), rp


metrics = dict(lag_s=LAG, lag_scores=lag_scores, counts=count_table.to_dict("records"),
               tribe_commit=TRIBE_COMMIT, encoders=enc_info,
               text_pathway_fraction=float(np.mean([c["text"] for c in clips])))
net, best_val = train_head(tag="both")
metrics["val_parcel_r"] = best_val
metrics["test"], rp_test = eval_corr(net, test)
log("test:", json.dumps(metrics["test"]))
torch.save(net.state_dict(), RUN / "head.pt")

# ---------------- stress readout ----------------
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score


def clip_feats(roi_seq):
    return np.concatenate([roi_seq.mean(0), roi_seq.max(0)])


def readout_data(cs, use_teacher=False):
    X, y = [], []
    for c in cs:
        if pd.isna(c["label"]) or c["label"] == "":
            continue
        roi = c["Yr"] if use_teacher else predict(net, c)[1]
        X.append(clip_feats(roi)); y.append(int(float(c["label"])))
    return np.array(X), np.array(y)


feat_names = [f"mean_{n}" for n in atlas["roi_names"]] + [f"max_{n}" for n in atlas["roi_names"]]
readout = None
try:
    Xs, ys = readout_data(train + val)
    sc = StandardScaler().fit(Xs)
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(Xs), ys)
    w = lr.coef_[0] / sc.scale_
    b = float(lr.intercept_[0] - (lr.coef_[0] * sc.mean_ / sc.scale_).sum())
    readout = dict(roi_names=atlas["roi_names"], feature_names=feat_names, weights=w.tolist(), bias=b,
                   feature_definition="x = concat(mean over time of each ROI, max over time of each ROI) using the "
                                      "student's predicted roi (teacher units); stress = sigmoid(w.x + b). For a live "
                                      "curve at second t use mean/max over windows 0..t.",
                   trained_on=f"TikHarm Harmful(1) vs Safe(0), train+val splits, n={len(ys)}")
    Xt, yt = readout_data(test)
    metrics["stress_auroc_test_student"] = float(roc_auc_score(yt, 1 / (1 + np.exp(-(Xt @ w + b))))) if len(set(yt)) > 1 else None
    Xtt, ytt = readout_data(train + val, use_teacher=True)
    sct = StandardScaler().fit(Xtt)
    lrt = LogisticRegression(C=1.0, max_iter=2000).fit(sct.transform(Xtt), ytt)
    Xte, yte = readout_data(test, use_teacher=True)
    metrics["stress_auroc_test_teacher_roi"] = float(roc_auc_score(yte, lrt.predict_proba(sct.transform(Xte))[:, 1])) if len(set(yte)) > 1 else None
    metrics["stress_n_test"] = int(len(yt))
    log("stress AUROC student", metrics["stress_auroc_test_student"], "teacher", metrics["stress_auroc_test_teacher_roi"])
    # shortcut check: how separable are the labels from raw encoder features alone (no brain model)?
    def raw(cs):
        X, y = [], []
        for c in cs:
            if pd.isna(c["label"]) or c["label"] == "":
                continue
            X.append(c["X"].mean(0)); y.append(int(float(c["label"])))
        return np.array(X), np.array(y)
    Xr, yr = raw(train + val); Xrt, yrt = raw(test)
    scr = StandardScaler().fit(Xr)
    lrr = LogisticRegression(C=0.05, max_iter=3000).fit(scr.transform(Xr), yr)
    metrics["stress_auroc_test_raw_features_baseline"] = float(roc_auc_score(yrt, lrr.predict_proba(scr.transform(Xrt))[:, 1])) if len(set(yrt)) > 1 else None
    log("shortcut baseline AUROC (raw features, no brain model):", metrics["stress_auroc_test_raw_features_baseline"])
except Exception:
    log("stress readout failed", traceback.format_exc()[-600:])
if readout:
    (EXPORT / "stress_readout.json").write_text(json.dumps(readout, indent=1))


def stress_curve(roi):
    if not readout:
        return []
    w, b = np.array(readout["weights"]), readout["bias"]
    return [float(1 / (1 + np.exp(-(clip_feats(roi[: t + 1]) @ w + b)))) for t in range(len(roi))]


# ---------------- demo JSON (stimulus-aligned, 1 Hz play-by-play) ----------------
# Every demo clip AND every held-out test clip gets a trace + its video + timed transcript,
# so the web team can pick examples (index.json flags English speech).
def transcript(c):
    p = Path(c["path"]).with_suffix(".tsv")
    try:
        if p.stat().st_size == 0:
            return []
        t = pd.read_csv(p, sep="\t")
        return [dict(t=round(float(a), 2), word=str(w)) for a, w in zip(t["start"], t["text"])]
    except Exception:
        return []


demo_index = []
demo_ids = {c["id"] for c in demo}
for c in demo + [x for x in test if x["id"] not in demo_ids]:
    try:
        _, pr = predict(net, c)
        T = len(pr)
        troi = np.full((T, K), np.nan, np.float32)
        for j, tt in enumerate(c["ti"]):
            s = tt - LAG
            if 0 <= s < T:
                troi[s] = c["Yr"][j]
        ok = ~np.isnan(troi).any(1)
        n = int(ok.sum())
        tr, sr = troi[ok], pr[ok]
        words = transcript(c)
        english = len(words) >= 8 and all(w["word"].isascii() for w in words)
        lab = None if pd.isna(c["label"]) or c["label"] == "" else int(float(c["label"]))
        js = dict(clip_id=c["id"], video=f"{c['id']}.mp4", hz=1, lag_s=LAG, roi_names=atlas["roi_names"],
                  label=lab, label_name={1: "Harmful", 0: "Safe"}.get(lab), uploader=c["uploader"],
                  t=[int(x) for x in np.where(ok)[0]], transcript=words,
                  teacher=dict(roi=tr.round(5).tolist(), stress=stress_curve(tr)),
                  student=dict(roi=sr.round(5).tolist(), stress=stress_curve(sr)))
        (EXPORT / "demo" / f"{c['id']}.json").write_text(json.dumps(js))
        shutil.copy(c["path"], EXPORT / "demo" / f"{c['id']}.mp4")
        st = js["student"]["stress"]
        demo_index.append(dict(clip_id=c["id"], is_demo=c["id"] in demo_ids, label=js["label_name"], uploader=c["uploader"],
                               english_speech=english, n_words=len(words), seconds=n,
                               final_stress_student=st[-1] if st else None,
                               final_stress_teacher=js["teacher"]["stress"][-1] if js["teacher"]["stress"] else None))
    except Exception as e:
        log("demo json fail", c["id"], e)
(EXPORT / "demo" / "index.json").write_text(json.dumps(demo_index, indent=1))
log(f"demo traces: {len(demo_index)} clips, {sum(d['english_speech'] for d in demo_index)} with English speech")
metrics["demo_r_roi"] = {}
for c in demo:
    _, pr = predict(net, c)
    a, b_ = [], []
    for j, tt in enumerate(c["ti"]):
        s = tt - LAG
        if 0 <= s < len(pr):
            a.append(pr[s]); b_.append(c["Yr"][j])
    if len(a) > 2:
        metrics["demo_r_roi"][c["id"]] = {n: float(v) for n, v in zip(atlas["roi_names"], colr(np.array(a), np.array(b_)))}

json.dump(metrics, open(RUN / "metrics.json", "w"), indent=1, default=str)
shutil.copy(RUN / "metrics.json", EXPORT / "metrics.json")


# ---------------- ONNX export (fp16 + int8, parity-checked) ----------------
import onnx
import onnxruntime as ort
from onnxconverter_common import float16
from onnxruntime.quantization import QuantType, quantize_dynamic

export_info = {}


class HeadExport(nn.Module):
    def __init__(self, net):
        super().__init__(); self.net = net

    def forward(self, feats):  # (1, W, F) -> last window
        y = self.net(feats)[:, -1]
        return y[:, :P], y[:, P:]


def export(module, dummy, name, in_names, out_names, dyn=None):
    module = module.float().cpu().eval()
    fp32 = EXPORT / f"{name}.fp32.onnx"
    torch.onnx.export(module, dummy, str(fp32), input_names=in_names, output_names=out_names, opset_version=17,
                      dynamic_axes=dyn, do_constant_folding=True)
    with torch.no_grad():
        ref = module(*dummy) if isinstance(dummy, tuple) else module(dummy)
    ref = [r.numpy() for r in (ref if isinstance(ref, (tuple, list)) else [ref])]
    feeds = {in_names[0]: (dummy[0] if isinstance(dummy, tuple) else dummy).numpy()}
    info = {}
    m16 = float16.convert_float_to_float16(onnx.load(str(fp32)), keep_io_types=True)
    onnx.save(m16, str(EXPORT / f"{name}.fp16.onnx"))
    quantize_dynamic(str(fp32), str(EXPORT / f"{name}.int8.onnx"), weight_type=QuantType.QInt8)
    for prec in ["fp32", "fp16", "int8"]:
        p = EXPORT / f"{name}.{prec}.onnx"
        try:
            s = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"])
            outs = s.run(None, feeds)
            err = max(float(np.abs(o - r).max() / (np.abs(r).max() + 1e-8)) for o, r in zip(outs, ref))
            info[prec] = dict(file=p.name, mb=round(p.stat().st_size / 1e6, 2), max_rel_err_vs_torch=round(err, 5))
        except Exception as e:
            info[prec] = dict(file=p.name, error=str(e)[:300])
    (EXPORT / f"{name}.fp32.onnx").unlink(missing_ok=True)  # ship fp16 + int8 only
    info.pop("fp32", None) if False else None
    info["inputs"] = {n: list(d.shape) for n, d in zip(in_names, [dummy] if not isinstance(dummy, tuple) else dummy)}
    info["outputs"] = out_names
    export_info[name] = info
    log("exported", name, json.dumps(info))


try:
    export(HeadExport(net), torch.randn(1, HIST_W, F) * 0.1, "student_head", ["feats"], ["parcels", "roi"],
           {"feats": {1: "W"}})
except Exception:
    log("head export failed", traceback.format_exc()[-800:])
try:
    venc = VisionEnc()
    export(venc, torch.rand(1, 3, 224, 224), "vision_encoder", ["image"], ["embedding"],
           {"image": {0: "N"}, "embedding": {0: "N"}})
except Exception:
    log("vision export failed", traceback.format_exc()[-800:])
try:
    aenc = AudioEnc()

    class AE(nn.Module):
        def __init__(s, a):
            super().__init__(); s.a = a

        def forward(s, mel):
            return s.a(mel)

    export(AE(aenc), torch.randn(1, 1, 128, 101) * 0.3, "audio_encoder", ["logmel"], ["embedding"],
           {"logmel": {0: "N"}, "embedding": {0: "N"}})
except Exception:
    log("audio export failed", traceback.format_exc()[-800:])

# ---------------- latency (GPU reference) ----------------
lat = {}
try:
    venc_g, aenc_g, net_g = VisionEnc().to(dev).eval().half(), AudioEnc().to(dev).eval(), net.to(dev).eval()
    fr = torch.rand(4, 3, 224, 224, device=dev).half(); mel = torch.randn(4, 1, 128, 101, device=dev)
    xs = torch.randn(1, HIST_W, F, device=dev)
    ts = []
    with torch.no_grad():
        for i in range(60):
            torch.cuda.synchronize(); t0 = time.perf_counter()
            venc_g(fr); aenc_g(mel); net_g(xs)
            torch.cuda.synchronize(); ts.append((time.perf_counter() - t0) * 1000)
    ts = ts[10:]
    lat = dict(p50_ms=round(float(np.percentile(ts, 50)), 2), p95_ms=round(float(np.percentile(ts, 95)), 2),
               note="H100, PyTorch, per 1 s window = 4 frames + 4 audio hops + head; reference only")
except Exception as e:
    lat = dict(error=str(e))
metrics["latency_gpu"] = lat
metrics["onnx"] = export_info

# ---------------- ablations (cheap: cached features) ----------------
if os.environ.get("SKIP_ABLATIONS") != "1":
    for tag, cols in [("vision_only", AUD_COLS), ("audio_only", VIS_COLS)]:
        try:
            n2, _ = train_head(mask_cols=cols, steps=300, tag=tag)
            metrics[f"ablation_{tag}"], _ = eval_corr(n2, test)
        except Exception as e:
            log("ablation fail", tag, e)
json.dump(metrics, open(RUN / "metrics.json", "w"), indent=1, default=str)
shutil.copy(RUN / "metrics.json", EXPORT / "metrics.json")

# ---------------- README contract + REPORT ----------------
v, a = enc_info["vision"], enc_info["audio"]
readme = f"""# Student brain-response model: web contract

Distilled from Meta TRIBE v2 (commit {TRIBE_COMMIT}, full trimodal: V-JEPA2 + Wav2Vec-BERT + Llama-3.2-3B text via WhisperX).
Predicts TRIBE's per-parcel cortical response (Destrieux atlas on fsaverage5, {P} parcels) and {K} stress ROIs,
**stimulus-aligned** at 1 Hz (target shifted by lag_s = {LAG} s, chosen on validation; TRIBE's own output is already
offset 5 s for hemodynamic lag).

## Pipeline per 1-second window t (t = 0, 1, 2, ... seconds from clip start)

1. **Vision** (`vision_encoder.*.onnx`, {v['name']} / {v.get('pretrained')}, {v['params']/1e6:.1f}M params)
   - Sample frames at **{v['fps']} fps** (frames at t, t+0.25, t+0.5, t+0.75 s).
   - Resize short side to 224 (bilinear), center-crop 224x224, RGB, float32 in [0,1], NCHW.
   - Input `image` float32 [N,3,224,224] (normalization mean={v['mean']} std={v['std']} is applied **inside** the model).
   - Output `embedding` float32 [N,{Dv}], L2-normalized.
2. **Audio** (`audio_encoder.*.onnx`, {a['name']}, {a['params']/1e6:.2f}M params)
   - Mono, **32000 Hz** waveform (float32 in [-1,1]).
   - Windows of **1.0 s** every **0.25 s** starting at 0 (zero-pad the tail).
   - Log-mel per window: n_fft=1024, win_length=800 (hann), hop=320, center=True (reflect pad), power=2,
     128 mel bands, HTK mel scale, f_min=0, f_max=16000, no filter norm; `logmel = (log(mel + 1e-5) + 4.5) / 5`.
     Shape [1,128,101] per window.
   - Input `logmel` float32 [N,1,128,101]. Output `embedding` float32 [N,{Da}].
3. **Window feature** (length {F}) = concat(
   mean of the 4 frame embeddings, elementwise max of the 4, mean |e[i+1]-e[i]| over the 3 consecutive pairs,
   mean of the 4 audio embeddings whose windows start at t, t+.25, t+.5, t+.75).
4. **Head** (`student_head.*.onnx`): input `feats` float32 [1,W,{F}] = the last **W = {HIST_W}** window features,
   oldest first (at clip start, repeat the first window to fill). Feature standardization is inside the model.
   Outputs `parcels` float32 [1,{P}] and `roi` float32 [1,{K}] for the newest window, in TRIBE units.
5. **Stress** (`stress_readout.json`): x = concat(mean over windows 0..t of each ROI, max over 0..t of each ROI);
   stress = sigmoid(w . x + bias).

ROI names (order of `roi`): {atlas['roi_names']}
ROI parcel membership: {json.dumps(atlas['roi_members'])}
Parcel names (order of `parcels`): see `parcel_names.json`.

## Files
{json.dumps(export_info, indent=1)}
fp16 models keep float32 inputs/outputs. int8 = dynamic weight quantization.

## Demo traces
`demo/<clip_id>.json`: 1 Hz, stimulus-aligned, teacher and student ROI curves and stress curves
(`t` lists the seconds that have a teacher value).

## Reference latency
{json.dumps(lat)}

## Licenses
- TRIBE v2 code and weights: **CC BY-NC 4.0 (non-commercial)**. These student models are distilled from its outputs; treat them as non-commercial.
- Llama 3.2 (TRIBE's text encoder, used only for teacher labels): Llama 3.2 Community License (copy kept on the volume with the weights).
- {v['name']}: see open_clip / Apple MobileCLIP license. {a['name']}: see its repository license.
- TikHarm videos (training data): Kaggle dataset `anhoangvo/tikharm-dataset`; follow its terms.
"""
(EXPORT / "README.md").write_text(readme)
(EXPORT / "parcel_names.json").write_text(json.dumps(atlas["parcel_names"]))
(EXPORT / "encoders.json").write_text(json.dumps(enc_info, indent=1, default=str))

rep = f"""# REPORT ({RUN.name})

**No LIRIS-ACCEDE on the volume**: distillation and the stress readout were trained on TikHarm (Harmful vs Safe),
split by uploader. There is **no out-of-domain test**; the stress AUROC below is in-domain (held-out uploaders).

## Data counts (clips with teacher labels and student features)
{count_table.to_string(index=False)}

## Student vs teacher (test split)
{json.dumps(metrics.get('test'), indent=1)}

Lag: {LAG} s (val ridge scores {lag_scores}). Text pathway active for {metrics['text_pathway_fraction']*100:.0f}% of clips.

## Stress
AUROC student readout: {metrics.get('stress_auroc_test_student')}; teacher-ROI readout: {metrics.get('stress_auroc_test_teacher_roi')}; n_test={metrics.get('stress_n_test')}
Shortcut baseline (logistic regression on raw encoder features, no brain model): {metrics.get('stress_auroc_test_raw_features_baseline')}

**Label caveats.** TikHarm "Harmful" is a per-video moderation label (broad: dangerous acts, scams, bullying...),
not a stress rating, and only one 10 s window per video is used. In this data, Safe clips skew toward Vietnamese
creators and Harmful toward English-language creators, so a readout can partly learn language/region instead of harm;
the raw-feature baseline above shows how much is separable from surface cues alone. TRIBE's transcription is
hard-coded to English, so Vietnamese speech yields noisy text-pathway input.

## Ablations
vision only: {json.dumps(metrics.get('ablation_vision_only'))}
audio only: {json.dumps(metrics.get('ablation_audio_only'))}

## Demo clips ROI r (student vs teacher)
{json.dumps(metrics.get('demo_r_roi'), indent=1)}

## Log
""" + "\n".join(LOG)
(RUN / "REPORT.md").write_text(rep)
shutil.copy(RUN / "REPORT.md", EXPORT / "REPORT.md")
(W / "markers/export_done").touch()
log("EXPORT DONE")
