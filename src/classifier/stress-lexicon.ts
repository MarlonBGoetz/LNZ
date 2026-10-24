import type { FeedItem } from "../shared/feed-item";
import type { Classifier, ClassifyRequest, Verdict } from "./types";

/** Weighted stress lexicon: 3 = severe, 2 = moderate, 1 = mild. Test stand-in until the ONNX model lands. */
export const STRESS_LEXICON: Record<string, number> = {
  // violence / crime
  kill: 3, killed: 3, killing: 3, murder: 3, murdered: 3, shooting: 3, gunshot: 3, "shot dead": 3, stabbing: 3, stabbed: 3,
  massacre: 3, hostage: 3, terror: 3, terrorist: 3, bombing: 3, explosion: 3, "dead body": 3, corpse: 3, gore: 3,
  assault: 3, abuse: 3, kidnapped: 3, truecrime: 3, crime: 2, fight: 2, brawl: 2, arrested: 2, police: 1, blood: 2,
  // war / disaster / news
  war: 3, missile: 3, airstrike: 3, earthquake: 3, tsunami: 3, wildfire: 3, hurricane: 2, flood: 2,
  "breaking news": 3, emergency: 2, news: 1, crash: 2, "car crash": 3, accident: 2, tragedy: 3, tragic: 3,
  // death / grief
  died: 3, death: 3, dead: 2, rip: 3, "rest in peace": 3, "passed away": 3, funeral: 3, grief: 2, cancer: 2,
  // fear / horror
  horror: 3, jumpscare: 3, scary: 2, creepy: 2, haunted: 2, terrifying: 3, scream: 2, screaming: 2, nightmare: 2,
  // distress / mental health
  suicide: 3, overdose: 3, "panic attack": 3, anxiety: 2, depression: 2, breakdown: 2, crying: 2, sad: 1, trauma: 3,
  // pressure / conflict
  rage: 2, toxic: 1, scam: 2, layoff: 2, layoffs: 2, fired: 1, debt: 1, eviction: 2, injury: 2, injured: 2, hospital: 1,
};

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const compile = (lex: Record<string, number>) =>
  Object.entries(lex).map(([term, weight]) => ({
    term,
    weight,
    re: new RegExp(`(?<![\\p{L}\\p{N}])${escape(term).replace(/ /g, "\\s+")}(?![\\p{L}\\p{N}])`, "iu"),
  }));

export const textOf = (item: FeedItem): string =>
  [item.caption, ...item.hashtags, ...item.labels.diversification].join(" \n ");

/** Blocks when the summed weight of distinct matched terms reaches the threshold. Synchronous, ~0 ms. */
export class StressLexiconClassifier implements Classifier {
  readonly name = "stressText";
  readonly needs = "metadata";
  readonly defaultTimeoutMs = 300;
  private readonly terms: ReturnType<typeof compile>;

  constructor(
    private readonly threshold = 3,
    lexicon: Record<string, number> = STRESS_LEXICON,
  ) {
    this.terms = compile(lexicon);
  }

  score(item: FeedItem): { score: number; hits: string[] } {
    const text = textOf(item);
    const hits = this.terms.filter((t) => t.re.test(text));
    return { score: hits.reduce((a, t) => a + t.weight, 0), hits: hits.map((t) => t.term) };
  }

  explain(item: FeedItem): string | null {
    const { score, hits } = this.score(item);
    return hits.length ? `${hits.join(", ")} (${score})` : null;
  }

  async classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>> {
    return Object.fromEntries(reqs.map(({ item }) => [item.id, this.score(item).score >= this.threshold ? "block" : ("allow" as Verdict)]));
  }
}
