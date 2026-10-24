"""Shared paths, deadlines, progress and claim helpers for all pod jobs."""
import json
import os
import time
from pathlib import Path

W = Path("/workspace")
CLIPS = W / "data/clips"
MANIFEST = W / "data/manifest.csv"
TEACHER = W / "teacher"
FEATS = W / "student/features"
LOGS = W / "logs"
EXPORT = W / "export"
RUNS = W / "runs"
LLAMA = W / "models/Llama-3.2-3B"
ATLAS = W / "atlas/destrieux_fs5.npz"
MARK = W / "markers"
for p in [CLIPS, TEACHER, FEATS, LOGS, EXPORT, RUNS, MARK]:
    p.mkdir(parents=True, exist_ok=True)

TEACH_END = int(os.environ.get("TEACH_END_EPOCH", "0"))  # teacher stops here
TRIBE_COMMIT = "af58661"


def now():
    return time.time()


def teacher_time_left():
    return TEACH_END - now() if TEACH_END else 1e9


def progress(job, **kw):
    kw["updated"] = time.strftime("%H:%M:%S", time.gmtime())
    p = LOGS / f"{job}.progress.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(kw, indent=1, default=str))
    os.replace(tmp, p)


def claim(dirpath: Path, key: str) -> bool:
    """Atomic claim so two pods never work on the same clip."""
    dirpath.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(dirpath / key), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, os.environ.get("ROLE", "?").encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def read_manifest():
    import pandas as pd

    if not MANIFEST.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(MANIFEST).sort_values("prio")
    except Exception:
        return pd.DataFrame()


def wait_for(path: Path, what: str, timeout=3600):
    t0 = now()
    while not path.exists():
        if now() - t0 > timeout:
            raise TimeoutError(what)
        print(f"waiting for {what} ...", flush=True)
        time.sleep(15)


# Destrieux (nilearn) names on fsaverage5. Stress ROIs use exact parcel membership below.
ROI_DEFS = {
    "L_anterior_insula": ("L", ["G_insular_short", "S_circular_insula_ant"]),
    "R_anterior_insula": ("R", ["G_insular_short", "S_circular_insula_ant"]),
    "dACC": ("LR", ["G_and_S_cingul-Mid-Ant"]),
    "mPFC": ("LR", ["G_and_S_cingul-Ant", "G_rectus", "S_suborbital"]),
    "early_auditory": ("LR", ["G_temp_sup-G_T_transv", "S_temporal_transverse"]),
    "early_visual": ("LR", ["S_calcarine", "G_cuneus", "Pole_occipital"]),
}


def build_atlas():
    """Parcel and ROI vertex masks for the 20484-vertex fsaverage5 (left then right)."""
    import numpy as np
    from nilearn import datasets

    d = datasets.fetch_atlas_surf_destrieux()
    labels = [l.decode() if isinstance(l, bytes) else str(l) for l in d["labels"]]
    lh, rh = np.asarray(d["map_left"]), np.asarray(d["map_right"])
    assert lh.shape[0] == 10242 and rh.shape[0] == 10242
    full = np.concatenate([lh, rh])
    hemi = np.array(["L"] * 10242 + ["R"] * 10242)
    names, masks = [], []
    for i, lab in enumerate(labels):
        if lab in ("Unknown", "Medial_wall"):
            continue
        for h in "LR":
            m = (full == i) & (hemi == h)
            if m.sum() > 0:
                names.append(f"{h}_{lab}")
                masks.append(m)
    roi_names, roi_masks, roi_members = [], [], {}
    for rname, (hs, labs) in ROI_DEFS.items():
        m = np.zeros(20484, bool)
        members = []
        for lab in labs:
            if lab not in labels:
                print("WARNING atlas label missing:", lab)
                continue
            for h in hs:
                mm = (full == labels.index(lab)) & (hemi == h)
                if mm.any():
                    m |= mm
                    members.append(f"{h}_{lab}")
        roi_names.append(rname)
        roi_masks.append(m)
        roi_members[rname] = members
    ATLAS.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        ATLAS,
        parcel_names=np.array(names),
        parcel_masks=np.stack(masks),
        roi_names=np.array(roi_names),
        roi_masks=np.stack(roi_masks),
        roi_members=json.dumps(roi_members),
    )
    print(f"atlas: {len(names)} parcels, ROIs {roi_members}")


def load_atlas():
    import numpy as np

    a = np.load(ATLAS, allow_pickle=False)
    return dict(
        parcel_names=[str(x) for x in a["parcel_names"]],
        parcel_masks=a["parcel_masks"],
        roi_names=[str(x) for x in a["roi_names"]],
        roi_masks=a["roi_masks"],
        roi_members=json.loads(str(a["roi_members"])),
    )
