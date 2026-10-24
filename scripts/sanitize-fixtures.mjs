// Redacts personal data in fixtures while preserving JSON shape. Usage: node scripts/sanitize-fixtures.mjs <file...>
import fs from "node:fs";

const PSEUDONYM_KEYS = new Set(["uniqueId", "nickname", "userUniqueId", "secUid", "userId", "signature"]);
const SCRUB_KEYS = new Set(["log_extra", "raw_ad_data", "impr_id", "logid", "vast", "about_this_ad_info"]);
const KEEP_SCOPES = new Set(["webapp.updated-items"]);
const URL_RE = /^https?:\/\//;

const pseudo = new Map();
const alias = (v) => {
  if (!pseudo.has(v)) pseudo.set(v, `user_${pseudo.size + 1}`);
  return pseudo.get(v);
};

const walk = (node, parentKey) => {
  if (Array.isArray(node)) return node.map((v) => walk(v, parentKey));
  if (node && typeof node === "object") {
    const out = {};
    for (const [k, v] of Object.entries(node)) {
      if (SCRUB_KEYS.has(k)) out[k] = typeof v === "string" ? "redacted" : Array.isArray(v) ? [] : v && typeof v === "object" ? {} : v;
      else if (PSEUDONYM_KEYS.has(k) && typeof v === "string" && v) out[k] = alias(v);
      else if (k === "id" && parentKey === "author" && typeof v === "string") out[k] = alias(v);
      else if (k === "authorName" && knownHandles.has(v)) out[k] = alias(v);
      else out[k] = walk(v, k);
    }
    return out;
  }
  if (typeof node === "string" && URL_RE.test(node)) return "https://redacted.invalid/";
  return node;
};

const redactMentions = (node) => {
  if (Array.isArray(node)) return node.map(redactMentions);
  if (node && typeof node === "object") return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, k === "desc" && typeof v === "string" ? v.replace(/@([\w.]+)/g, (m, h) => (pseudo.has(h) ? `@${pseudo.get(h)}` : m)) : redactMentions(v)]));
  return node;
};

// Caption URLs are content, not personal data; they are left as-is (only full-string URLs are redacted).
const files = process.argv.slice(2);
const knownHandles = new Set();
for (const file of files) for (const m of fs.readFileSync(file, "utf8").matchAll(/"(?:uniqueId|userUniqueId|nickname)":\s*"([^"]+)"/g)) knownHandles.add(m[1]);

for (const file of files) {
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  const scope = data.__DEFAULT_SCOPE__;
  if (scope) for (const k of Object.keys(scope)) if (!KEEP_SCOPES.has(k)) scope[k] = {};
  fs.writeFileSync(file, JSON.stringify(redactMentions(walk(data)), null, 2) + "\n");
  console.log(`sanitized ${file}`);
}
