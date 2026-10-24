"""Frozen, browser-sized student encoders + their exact preprocessing.
Vision: MobileCLIP-S1 (open_clip), fallback ViT-B-32 (OpenAI CLIP).
Audio: EfficientAT mn10_as (AudioSet), fallback = log-mel statistics (no network).
Every choice is recorded in ENC_INFO and copied into export/README.md."""
import subprocess
import sys
import numpy as np
import torch
import torch.nn as nn

VIS_FPS = 4
VIS_SIZE = 224
AUD_SR = 32000  # EfficientAT is trained at 32 kHz
AUD_WIN_S = 1.0
AUD_HOP_S = 0.25
ENC_INFO = {}


class VisionEnc(nn.Module):
    """Input: float32 (N,3,224,224) RGB in [0,1]. Normalization is inside the model."""

    def __init__(self):
        super().__init__()
        import open_clip
        last = None
        for name, tag in [("MobileCLIP-S1", "datacompdr"), ("ViT-B-32", "openai")]:
            try:
                m, _, pre = open_clip.create_model_and_transforms(name, pretrained=tag)
                self.visual = m.visual.eval()
                mean = getattr(m.visual, "image_mean", None) or (0.48145466, 0.4578275, 0.40821073)
                std = getattr(m.visual, "image_std", None) or (0.26862954, 0.26130258, 0.27577711)
                if name.startswith("MobileCLIP"):
                    mean, std = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)  # MobileCLIP uses no mean/std normalization
                    try:  # reparameterize for inference/export
                        from timm.utils.model import reparameterize_model
                        self.visual = reparameterize_model(self.visual)
                    except Exception as e:
                        print("reparam skipped", e)
                self.register_buffer("mean", torch.tensor(mean).view(1, 3, 1, 1))
                self.register_buffer("std", torch.tensor(std).view(1, 3, 1, 1))
                with torch.no_grad():
                    self.dim = int(self.visual(torch.zeros(1, 3, 224, 224)).shape[-1])
                ENC_INFO["vision"] = dict(name=name, pretrained=tag, open_clip=open_clip.__version__,
                                          params=sum(p.numel() for p in self.visual.parameters()), dim=self.dim,
                                          mean=list(mean), std=list(std), input="float32 [N,3,224,224] RGB in [0,1]",
                                          resize="resize short side to 224 (bilinear), center crop 224x224",
                                          fps=VIS_FPS)
                return
            except Exception as e:
                last = e
                print("vision encoder failed", name, e)
        raise last

    def forward(self, x):
        f = self.visual((x - self.mean) / self.std)
        return f / f.norm(dim=-1, keepdim=True)


class MelFrontend(nn.Module):
    """log-mel used by both audio paths; kept outside the ONNX so the browser can compute it."""

    def __init__(self, sr=AUD_SR, n_mels=128, win=800, hop=320, n_fft=1024):
        super().__init__()
        import torchaudio
        self.cfg = dict(sample_rate=sr, n_mels=n_mels, win_length=win, hop_length=hop, n_fft=n_fft,
                        f_min=0.0, f_max=sr / 2, window="hann", center=True, power=2.0, log="log(mel + 1e-5)",
                        mel_scale="htk", norm=None, post="(logmel + 4.5) / 5.0")
        self.mel = torchaudio.transforms.MelSpectrogram(sample_rate=sr, n_fft=n_fft, win_length=win, hop_length=hop,
                                                        n_mels=n_mels, f_min=0.0, f_max=sr / 2, power=2.0,
                                                        center=True, mel_scale="htk")

    def forward(self, wav):  # (N, samples) -> (N, 1, n_mels, frames)
        m = torch.log(self.mel(wav) + 1e-5)
        return ((m + 4.5) / 5.0).unsqueeze(1)


class AudioEnc(nn.Module):
    """Input: log-mel float32 (N,1,128,101) for a 1 s window at 32 kHz (see MelFrontend)."""

    def __init__(self):
        super().__init__()
        self.front = MelFrontend()
        self.kind = None
        try:
            import os
            sys.path.insert(0, "/root/EfficientAT")
            cwd = os.getcwd()
            os.chdir("/root/EfficientAT")  # it loads metadata/*.csv by relative path
            try:
                from models.mn.model import get_model as get_mn
                self.net = get_mn(width_mult=1.0, pretrained_name="mn10_as").eval()
            finally:
                os.chdir(cwd)
            with torch.no_grad():
                out = self.net(torch.zeros(1, 1, 128, 101))
            emb = out[1] if isinstance(out, (tuple, list)) else out
            self.dim = int(emb.shape[-1])
            self.kind = "efficientat_mn10_as"
            ENC_INFO["audio"] = dict(name="EfficientAT mn10_as (AudioSet)", repo="https://github.com/fschmid56/EfficientAT",
                                     params=sum(p.numel() for p in self.net.parameters()), dim=self.dim,
                                     output="penultimate embedding", mel=self.front.cfg, window_s=AUD_WIN_S,
                                     hop_s=AUD_HOP_S, input="float32 [N,1,128,101] log-mel")
        except Exception as e:
            print("EfficientAT unavailable, using log-mel stats fallback:", e)
            self.net = None
            self.dim = 256
            self.kind = "logmel_stats"
            ENC_INFO["audio"] = dict(name="log-mel mean+std (fallback, no learned encoder)", params=0, dim=self.dim,
                                     mel=self.front.cfg, window_s=AUD_WIN_S, hop_s=AUD_HOP_S,
                                     input="float32 [N,1,128,101] log-mel")

    def forward(self, mel):
        if self.net is None:
            return torch.cat([mel.mean(-1), mel.std(-1)], -1).flatten(1)
        out = self.net(mel)
        return out[1] if isinstance(out, (tuple, list)) else out


def read_frames(path, fps=VIS_FPS, size=VIS_SIZE):
    vf = (f"fps={fps},scale='if(gt(iw,ih),-2,{size})':'if(gt(iw,ih),{size},-2)':flags=bilinear,"
          f"crop={size}:{size}")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, size, size, 3)
    return torch.from_numpy(a.copy()).permute(0, 3, 1, 2).float() / 255.0


def read_audio(path, sr=AUD_SR):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return torch.from_numpy(np.frombuffer(raw, np.float32).copy())


def audio_windows(wav, sr=AUD_SR):
    """1 s windows every 250 ms, starting at 0; zero-padded at the end."""
    win, hop = int(sr * AUD_WIN_S), int(sr * AUD_HOP_S)
    n = max(1, int(np.ceil(len(wav) / hop)))
    wav = torch.nn.functional.pad(wav, (0, n * hop + win - len(wav)))
    return torch.stack([wav[i * hop: i * hop + win] for i in range(n)])


def window_features(vis, aud, T):
    """Per 1 s window t: [mean(vis 4t..4t+3), max(...), mean|diff|(...), mean(aud hops 4t..4t+3)]."""
    rows = []
    for t in range(T):
        v = vis[4 * t: 4 * t + 4]
        if len(v) == 0:
            v = vis[-1:]
        d = (v[1:] - v[:-1]).abs().mean(0) if len(v) > 1 else torch.zeros(v.shape[1])
        a = aud[4 * t: 4 * t + 4]
        if len(a) == 0:
            a = aud[-1:]
        rows.append(torch.cat([v.mean(0), v.max(0).values, d, a.mean(0)]))
    return torch.stack(rows)
