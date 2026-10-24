/** Owns delayed navigation, including cancellation and one request per video. */
export class DelayedAutoSkip {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly requested = new Set<string>();

  schedule(videoId: string, stillEligible: () => boolean, requestNext: () => void, delay = 650): void {
    this.cancel();
    if (this.requested.has(videoId)) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      if (!stillEligible() || this.requested.has(videoId)) return;
      this.requested.add(videoId);
      requestNext();
    }, delay);
  }

  cancel(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
  }
}
