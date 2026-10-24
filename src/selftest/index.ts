// Runs the browser pipeline (decode + log-mel + ONNX) on demo clips and compares against the exported student curves.
import { TribeEngine } from "../model/tribe/engine";

type Clip = { clip_id: string; label: string; final_stress_student: number };

const out = document.getElementById("out")!;
const log = (s: string) => (out.textContent += s + "\n");

const corr = (a: number[], b: number[]): number => {
  const n = Math.min(a.length, b.length);
  if (n < 2) return NaN;
  const ma = a.slice(0, n).reduce((x, y) => x + y, 0) / n;
  const mb = b.slice(0, n).reduce((x, y) => x + y, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) (num += (a[i]! - ma) * (b[i]! - mb)), (da += (a[i]! - ma) ** 2), (db += (b[i]! - mb) ** 2);
  return num / Math.sqrt(da * db);
};

const run = async () => {
  const base = chrome.runtime.getURL("/");
  const engine = new TribeEngine(base);
  const t0 = performance.now();
  await engine.init();
  log(`backend ${engine.backend} · load+warmup ${Math.round(performance.now() - t0)} ms${engine.fallbackReason ? ` · fallback: ${engine.fallbackReason}` : ""}`);
  if (new URLSearchParams(location.search).has("loadOnly")) return void (document.body.dataset.done = "loaded");
  const clips: Clip[] = await (await fetch("demo/index.json")).json();
  const rows: Record<string, unknown>[] = [];
  for (const c of clips) {
    const ref = await (await fetch(`demo/${c.clip_id}.json`)).json();
    const blob = await (await fetch(`demo/${c.clip_id}.mp4`)).blob();
    const r = await engine.run(blob, null, 10);
    const refRoi: number[][] = ref.student.roi;
    const roiR = [0, 1, 2, 3, 4, 5].map((k) => corr(r.roi.map((x) => x[k]!), refRoi.map((x) => x[k]!)));
    const row = {
      clip: c.clip_id,
      label: c.label,
      seconds: `${r.seconds}/${refRoi.length}`,
      stressOurs: +r.stress.at(-1)!.toFixed(3),
      stressRef: +c.final_stress_student.toFixed(3),
      absErr: +Math.abs(r.stress.at(-1)! - c.final_stress_student).toFixed(3),
      roiRmean: +(roiR.reduce((a, b) => a + b, 0) / 6).toFixed(3),
      audioOk: r.audioOk,
      ms: Math.round(r.totalMs),
      decodeMs: Math.round(r.decodeMs),
      visionMs: Math.round(r.ms.vision),
      audioMs: Math.round(r.ms.audio),
    };
    rows.push(row);
    log(JSON.stringify(row));
  }
  const err = rows.map((r) => r.absErr as number);
  log(`SUMMARY meanAbsErr ${(err.reduce((a, b) => a + b, 0) / err.length).toFixed(3)} maxAbsErr ${Math.max(...err).toFixed(3)}`);
  document.body.dataset.done = JSON.stringify({ backend: engine.backend, rows });
};

run().catch((e) => {
  log("FAILED " + String(e));
  document.body.dataset.done = JSON.stringify({ error: String(e) });
});
