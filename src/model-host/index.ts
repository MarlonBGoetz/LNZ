// Extension page loaded as a hidden iframe on tiktok.com. Runs the TRIBE models off the page's main thread.
import { TribeEngine } from "../model/tribe/engine";
import { HOST_HELLO, HOST_READY, type HostRequest, type HostResponse, type HostStatus } from "../shared/model-host";

/** A request that takes longer than this is abandoned so one bad clip can't wedge the queue. */
const WATCHDOG_MS = 15_000;
const STATUS_EVERY_MS = 500;

const engine = new TribeEngine(chrome.runtime.getURL("/"));
const ports: MessagePort[] = [];
const dbg = { queued: 0, stage: null as string | null, stageAt: 0, done: 0, failed: 0, lastMs: null as number | null, lastError: null as string | null };
let base: Pick<HostStatus, "status" | "backend" | "error"> = { status: "loading", backend: null };

const snapshot = (): HostStatus => ({
  ...base,
  queued: dbg.queued,
  stage: dbg.stage,
  stageMs: dbg.stage ? Math.round(performance.now() - dbg.stageAt) : null,
  done: dbg.done,
  failed: dbg.failed,
  lastMs: dbg.lastMs,
  lastError: dbg.lastError,
});
const broadcast = () => ports.forEach((p) => p.postMessage(snapshot()));
setInterval(broadcast, STATUS_EVERY_MS);

engine.onStage = (s) => ((dbg.stage = s), (dbg.stageAt = performance.now()));

const ready = engine.init().then(
  () => ((base = { status: "ready", backend: engine.backend }), broadcast()),
  (e) => ((base = { status: "failed", backend: null, error: String(e).slice(0, 300) }), broadcast()),
);

const withWatchdog = <T>(p: Promise<T>): Promise<T> =>
  Promise.race([p, new Promise<never>((_, rej) => setTimeout(() => rej(new Error(`watchdog: stuck in ${dbg.stage ?? "?"}`)), WATCHDOG_MS))]);

/** One clip at a time: the GPU/CPU is the bottleneck. The bridge decides the order. */
let chain: Promise<unknown> = ready;

const handle = (port: MessagePort, req: HostRequest) => {
  dbg.queued++;
  chain = chain.then(async () => {
    dbg.queued--;
    const t0 = performance.now();
    let res: HostResponse;
    try {
      const video = new Blob([req.video], { type: req.videoType });
      const audio = req.audio ? new Blob([req.audio], { type: "audio/mp4" }) : null;
      res = { reqId: req.reqId, ok: true, result: await withWatchdog(engine.run(video, audio, req.maxSec)) };
      dbg.done++;
      dbg.lastError = null;
    } catch (e) {
      res = { reqId: req.reqId, ok: false, error: String(e).slice(0, 300) };
      dbg.failed++;
      dbg.lastError = res.error;
    }
    dbg.lastMs = Math.round(performance.now() - t0);
    dbg.stage = null;
    port.postMessage(res);
    broadcast();
  });
};

window.addEventListener("message", (e) => {
  if (e.data !== HOST_HELLO || !e.ports[0]) return;
  const port = e.ports[0];
  ports.push(port);
  port.onmessage = (m) => handle(port, m.data as HostRequest);
  port.postMessage(HOST_READY);
  port.postMessage(snapshot());
});
