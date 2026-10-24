import type { Config } from "../shared/config";
import { KeywordClassifier, StubClassifier } from "./basic";
import { HttpClassifier, type HttpTransport } from "./http";
import { MockStressClassifier } from "./mock-stress";
import { StressLexiconClassifier } from "./stress-lexicon";
import { TribeStressClassifier, type StressModel } from "./tribe";
import type { Classifier } from "./types";

/** Single place to add a classifier (e.g. the ONNX one). */
export const createClassifier = (cfg: Config, deps: { http: HttpTransport; stressModel: () => StressModel }): Classifier => {
  switch (cfg.classifier) {
    case "tribe":
      return new TribeStressClassifier(deps.stressModel(), { threshold: cfg.tribeThreshold, maxSec: cfg.tribeSeconds, timeoutMs: 20_000 });
    case "stressText":
      return new StressLexiconClassifier();
    case "keyword":
      return new KeywordClassifier(cfg.keywordPattern);
    case "mockStress":
      return new MockStressClassifier();
    case "http":
      return new HttpClassifier(cfg.httpUrl, deps.http);
    default:
      return new StubClassifier();
  }
};

export const timeoutFor = (cfg: Config, c: Classifier): number => cfg.classifierTimeoutMs || c.defaultTimeoutMs;
