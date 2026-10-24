"""Download every model once onto the volume (HF_HOME=/workspace/hf_cache), verify Llama
hashes (hard stop on mismatch), build the atlas, then mark models_ready."""
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor

from huggingface_hub import snapshot_download

from common import ATLAS, LLAMA, MARK, build_atlas

HASHES = {
    "model-00001-of-00002.safetensors": "584d8d3e3f82f7964955174dfe5e3b1cf117a9d859f022cfdf7fcb884856e002",
    "model-00002-of-00002.safetensors": "4719a04514ec2f060240711b7c33ab21187cac730ecaba3040b7a0fd95a9cefb",
}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def llama():
    if not (LLAMA / ".verified").exists():
        snapshot_download("unsloth/Llama-3.2-3B", revision="d4446454d87d51aa42e1fb174f25acc5f8762331",
                          local_dir=str(LLAMA), ignore_patterns=["original/*"])
        for f, want in HASHES.items():
            got = sha(LLAMA / f)
            print(f, got, "OK" if got == want else "MISMATCH", flush=True)
            if got != want:
                (MARK / "llama_hash_mismatch").write_text(f"{f} {got}")
                sys.exit(3)
        (LLAMA / ".verified").write_text("ok")
    print("llama verified", flush=True)


def other(repo):
    snapshot_download(repo)
    print("downloaded", repo, flush=True)


with ThreadPoolExecutor(6) as ex:
    futs = [ex.submit(llama)] + [ex.submit(other, r) for r in [
        "facebook/tribev2", "facebook/vjepa2-vitg-fpc64-256", "facebook/dinov2-large", "facebook/w2v-bert-2.0",
        "Systran/faster-whisper-large-v3"]]
    for f in futs:
        f.result()
if not ATLAS.exists():
    build_atlas()
(MARK / "models_ready").touch()
print("models ready", flush=True)
