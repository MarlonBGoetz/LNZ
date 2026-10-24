import type { EngineResult } from "../model/tribe/engine";

/** content script ↔ model-host frame, over a private MessageChannel port. */
export type HostRequest = { reqId: number; video: ArrayBuffer; videoType: string; audio: ArrayBuffer | null; maxSec: number };
export type HostResponse = { reqId: number; ok: true; result: EngineResult } | { reqId: number; ok: false; error: string };
export type HostStatus = {
  status: "loading" | "ready" | "failed";
  backend: string | null;
  error?: string;
  /** Debug: queue depth, current stage and the last outcome. */
  queued?: number;
  stage?: string | null;
  stageMs?: number | null;
  done?: number;
  failed?: number;
  lastMs?: number | null;
  lastError?: string | null;
};

export const HOST_HELLO = "LNZ_MODEL_HOST_HELLO";
export const HOST_READY = "LNZ_MODEL_HOST_READY";
