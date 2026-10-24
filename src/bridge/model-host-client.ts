import type { StressAnalysis, StressModel } from "../classifier/tribe";
import type { MediaClip } from "../classifier/types";
import { HOST_HELLO, HOST_READY, type HostRequest, type HostResponse, type HostStatus } from "../shared/model-host";

/** Hidden extension iframe that runs the models; talks over a private MessageChannel so the page can't listen in. */
export class ModelHostClient implements StressModel {
  status: HostStatus = { status: "loading", backend: null };
  private port: Promise<MessagePort> | null = null;
  private readonly pending = new Map<number, { resolve: (r: StressAnalysis) => void; reject: (e: Error) => void }>();
  private nextId = 1;

  private connect(): Promise<MessagePort> {
    return (this.port ??= new Promise((resolve) => {
      const frame = document.createElement("iframe");
      frame.src = chrome.runtime.getURL("model-host.html");
      frame.setAttribute("aria-hidden", "true");
      // Inside the viewport (offscreen cross-origin frames get throttled), invisible and click-through.
      frame.style.cssText = "position:fixed;width:2px;height:2px;right:0;bottom:0;opacity:0;pointer-events:none;border:0;z-index:-1";
      frame.addEventListener("load", () => {
        const ch = new MessageChannel();
        ch.port1.onmessage = (e) => {
          const d = e.data as HostResponse | HostStatus | string;
          if (d === HOST_READY) return resolve(ch.port1);
          if (typeof d === "object" && "status" in d) return void (this.status = d);
          if (typeof d === "object" && "reqId" in d) this.settle(d);
        };
        frame.contentWindow!.postMessage(HOST_HELLO, new URL(frame.src).origin, [ch.port2]);
      });
      document.documentElement.append(frame);
    }));
  }

  private settle(r: HostResponse): void {
    const p = this.pending.get(r.reqId);
    if (!p) return;
    this.pending.delete(r.reqId);
    if (r.ok) p.resolve({ stress: r.result.stress, backend: r.result.backend, totalMs: r.result.totalMs, frames: r.result.frames, audioOk: r.result.audioOk });
    else p.reject(new Error(r.error));
  }

  /** Starts loading the models early so the first verdict isn't slowed by warm-up. */
  warm(): void {
    void this.connect();
  }

  async analyze(clip: MediaClip, maxSec: number): Promise<StressAnalysis> {
    const port = await this.connect();
    if (this.status.status === "failed") throw new Error(this.status.error ?? "model failed to load");
    const [video, audio] = await Promise.all([clip.video.arrayBuffer(), clip.audio?.arrayBuffer() ?? null]);
    const reqId = this.nextId++;
    const req: HostRequest = { reqId, video, videoType: clip.video.type || "video/mp4", audio, maxSec };
    return new Promise((resolve, reject) => {
      this.pending.set(reqId, { resolve, reject });
      port.postMessage(req, [video, ...(audio ? [audio] : [])]);
    });
  }
}
