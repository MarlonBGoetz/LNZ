// Model demo page: runs the TRIBE student in the browser on a clip, then plays it with the live stress curve.
import { ROI_NAMES } from "../model/tribe/contract";
import { TribeEngine, type EngineResult } from "../model/tribe/engine";
import { DEFAULT_CONFIG, loadConfig } from "../shared/config";

type Clip = { clip_id: string; label: string; uploader?: string };
type Ref = { student: { stress: number[]; roi: number[][] }; teacher: { stress: number[] }; t: number[] };

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const video = $<HTMLVideoElement>("v");
const canvas = $<HTMLCanvasElement>("chart");
const ctx = canvas.getContext("2d")!;
const status = $("status");
const verdictEl = $("verdict");

const engine = new TribeEngine(chrome.runtime.getURL("/"));
let threshold = DEFAULT_CONFIG.tribeThreshold;
let current: { result: EngineResult; ref: Ref | null } | null = null;
let runToken = 0;

const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const draw = () => {
  const dpr = devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const pad = { l: 36, r: 12, t: 12, b: 22 };
  const n = Math.max(current?.result.stress.length ?? 10, current?.ref?.student.stress.length ?? 0, 2);
  const x = (i: number) => pad.l + (i / (n - 1)) * (w - pad.l - pad.r);
  const lo = 0.2;
  const hi = 1;
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (h - pad.t - pad.b);

  ctx.strokeStyle = "#ffffff12";
  ctx.fillStyle = css("--mut");
  ctx.font = "11px system-ui";
  for (const v of [0.2, 0.4, 0.6, 0.8, 1]) {
    ctx.beginPath();
    ctx.moveTo(pad.l, y(v));
    ctx.lineTo(w - pad.r, y(v));
    ctx.stroke();
    ctx.fillText(v.toFixed(1), 6, y(v) + 4);
  }
  for (let i = 0; i < n; i++) ctx.fillText(`${i}s`, x(i) - 6, h - 6);

  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = css("--stress");
  ctx.beginPath();
  ctx.moveTo(pad.l, y(threshold));
  ctx.lineTo(w - pad.r, y(threshold));
  ctx.stroke();
  ctx.setLineDash([]);
  if (!current) return;

  const line = (vals: number[], color: string, width: number, upTo = Infinity) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    vals.forEach((v, i) => {
      if (i > upTo) return;
      i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v));
    });
    ctx.stroke();
    ctx.lineWidth = 1;
  };
  const t = video.currentTime;
  if (current.ref) {
    line(current.ref.teacher.stress, css("--teach") + "88", 1.5);
    line(current.ref.student.stress, css("--acc") + "aa", 1.5);
  }
  line(current.result.stress, css("--calm"), 3, Math.floor(t));
  ctx.strokeStyle = "#ffffff55";
  ctx.beginPath();
  ctx.moveTo(x(Math.min(t, n - 1)), pad.t);
  ctx.lineTo(x(Math.min(t, n - 1)), h - pad.b);
  ctx.stroke();
};

const renderRois = () => {
  const box = $("rois");
  if (!current) return box.replaceChildren();
  const s = Math.min(Math.floor(video.currentTime), current.result.roi.length - 1);
  const row = current.result.roi[s] ?? [];
  const all = current.result.roi.flat();
  const min = Math.min(...all);
  const max = Math.max(...all);
  box.replaceChildren(
    ...ROI_NAMES.map((name, k) => {
      const d = document.createElement("div");
      d.className = "roi";
      const v = row[k] ?? 0;
      d.innerHTML = `${name.replace(/_/g, " ")}<b>${v.toFixed(2)}</b><div class="bar"><i style="width:${(((v - min) / (max - min || 1)) * 100).toFixed(0)}%"></i></div>`;
      return d;
    }),
  );
};

const showVerdict = () => {
  if (!current) return (verdictEl.textContent = "");
  const s = Math.min(Math.floor(video.currentTime), current.result.stress.length - 1);
  const live = current.result.stress[s] ?? 0;
  const final = current.result.stress.at(-1)!;
  const block = final >= threshold;
  verdictEl.className = `verdict ${block ? "block" : "allow"}`;
  verdictEl.textContent = `${block ? "Stressful → LNZ skips" : "Calm → plays"} · final ${final.toFixed(2)} · now ${live.toFixed(2)}`;
};

const frame = () => {
  draw();
  showVerdict();
  renderRois();
  requestAnimationFrame(frame);
};

const analyze = async (blob: Blob, ref: Ref | null, label: string) => {
  const token = ++runToken;
  current = null;
  video.src = URL.createObjectURL(blob);
  status.textContent = `analyzing ${label}…`;
  const result = await engine.run(blob, null, 10);
  if (token !== runToken) return;
  current = { result, ref };
  const err = ref ? Math.abs(result.stress.at(-1)! - ref.student.stress.at(-1)!) : null;
  status.textContent = `${engine.backend} · ${Math.round(result.totalMs)} ms for ${result.seconds}s of video`;
  $("info").textContent =
    `decode ${Math.round(result.decodeMs)} ms · vision ${Math.round(result.ms.vision)} ms · audio ${Math.round(result.ms.audio)} ms · head ${Math.round(result.ms.head)} ms · ${result.frames} frames · audio ${result.audioOk ? "ok" : "missing"}` +
    (err !== null ? ` · |in-browser − exported| = ${err.toFixed(3)}` : "");
  video.currentTime = 0;
  void video.play();
};

const loadClips = async () => {
  const box = $("clips");
  let clips: Clip[] = [];
  try {
    clips = await (await fetch("demo/index.json")).json();
  } catch {}
  if (!clips.length) box.innerHTML = `<p class="mut small">No demo clips in this build (they're not in git). Use "Analyze your own MP4".</p>`;
  for (const c of clips) {
    const b = document.createElement("button");
    b.className = "clip";
    b.innerHTML = `<span>${c.clip_id.slice(3, 15)}</span><span class="${c.label === "Harmful" ? "tagH" : "tagS"}">${c.label}</span>`;
    b.onclick = async () => {
      box.querySelectorAll(".clip").forEach((x) => x.classList.toggle("on", x === b));
      const [blob, ref] = await Promise.all([fetch(`demo/${c.clip_id}.mp4`).then((r) => r.blob()), fetch(`demo/${c.clip_id}.json`).then((r) => r.json() as Promise<Ref>)]);
      await analyze(blob, ref, c.label);
    };
    box.append(b);
  }
  return box.querySelector<HTMLButtonElement>(".clip");
};

$<HTMLInputElement>("file").addEventListener("change", (e) => {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) void analyze(f, null, f.name);
});

const boot = async () => {
  threshold = (await loadConfig()).tribeThreshold;
  const first = await loadClips();
  await engine.init();
  status.textContent = `model ready · ${engine.backend}${engine.fallbackReason ? ` (fallback: ${engine.fallbackReason})` : ""}`;
  requestAnimationFrame(frame);
  first?.click();
};

boot().catch((e) => (status.textContent = `failed: ${e}`));
