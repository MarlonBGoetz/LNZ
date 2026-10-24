import type { FeedItem } from "../shared/feed-item";
import type { Classifier, ClassifyRequest, Verdict } from "./types";

export type HttpTransport = (url: string, items: Omit<FeedItem, "raw">[]) => Promise<Record<string, Verdict>>;

/** POSTs metadata to a configured endpoint. The transport is injected (background proxies the request). */
export class HttpClassifier implements Classifier {
  readonly name = "http";
  readonly needs = "metadata";
  readonly defaultTimeoutMs = 300;
  constructor(
    private readonly url: string,
    private readonly transport: HttpTransport,
  ) {}
  async classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>> {
    if (!this.url) return {};
    return this.transport(this.url, reqs.map(({ item: { raw: _raw, ...rest } }) => rest));
  }
}
