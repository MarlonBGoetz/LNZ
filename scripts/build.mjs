// Bundles each extension entry point into dist/ and copies static files, ORT wasm and the TRIBE models.
import * as esbuild from "esbuild";
import fs from "node:fs";
import path from "node:path";

const IIFE = {
  injected: "src/injected/index.ts",
  bridge: "src/bridge/index.ts",
  background: "src/background/index.ts",
  popup: "src/popup/index.ts",
};
const ESM = { "model-host": "src/model-host/index.ts", selftest: "src/selftest/index.ts", demo: "src/demo/index.ts" };
const MODEL_DIR = "model/tribe_student_export";
const MODEL_FILES = ["vision_encoder.fp16.onnx", "audio_encoder.fp16.onnx", "student_head.fp16.onnx", "stress_readout.json"];
const ORT_FILES = ["ort-wasm-simd-threaded.asyncify.wasm", "ort-wasm-simd-threaded.asyncify.mjs"];
const SELFTEST_CLIPS = 8;
const watch = process.argv.includes("--watch");

fs.rmSync("dist", { recursive: true, force: true });
fs.cpSync("static", "dist", { recursive: true });

fs.mkdirSync("dist/ort", { recursive: true });
for (const f of ORT_FILES) fs.copyFileSync(path.join("node_modules/onnxruntime-web/dist", f), path.join("dist/ort", f));

if (fs.existsSync(MODEL_DIR)) {
  fs.mkdirSync("dist/models", { recursive: true });
  for (const f of MODEL_FILES) fs.copyFileSync(path.join(MODEL_DIR, f), path.join("dist/models", f));
  // A few demo clips + expected curves for the in-browser self-test page (local only, not in git).
  const indexPath = path.join(MODEL_DIR, "demo/index.json");
  const index = fs.existsSync(indexPath) ? JSON.parse(fs.readFileSync(indexPath, "utf8")) : [];
  const hasVideo = (c) => fs.existsSync(path.join(MODEL_DIR, "demo", `${c.clip_id}.mp4`));
  const pick = [...index.filter((c) => c.label === "Harmful" && hasVideo(c)).slice(0, SELFTEST_CLIPS / 2), ...index.filter((c) => c.label === "Safe" && hasVideo(c)).slice(0, SELFTEST_CLIPS / 2)];
  if (pick.length === 0) console.warn("! no demo .mp4 files: selftest.html will have no clips (they are not in git; see README)");
  fs.mkdirSync("dist/demo", { recursive: true });
  for (const c of pick) for (const ext of ["mp4", "json"]) fs.copyFileSync(path.join(MODEL_DIR, "demo", `${c.clip_id}.${ext}`), path.join("dist/demo", `${c.clip_id}.${ext}`));
  fs.writeFileSync("dist/demo/index.json", JSON.stringify(pick));
} else console.warn(`! ${MODEL_DIR} missing: TRIBE classifier will report "model failed to load"`);

const common = { outdir: "dist", bundle: true, target: "chrome120", sourcemap: "linked", logLevel: "info" };
const ctxs = [
  await esbuild.context({ ...common, entryPoints: IIFE, format: "iife" }),
  await esbuild.context({ ...common, entryPoints: ESM, format: "esm" }),
];

if (watch) await Promise.all(ctxs.map((c) => c.watch()));
else {
  await Promise.all(ctxs.map((c) => c.rebuild()));
  await Promise.all(ctxs.map((c) => c.dispose()));
}
