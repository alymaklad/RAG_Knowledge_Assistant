/**
 * Citation helpers. The model cites with "[Source N]" (sometimes "[Source 1, Source 3]" or
 * "[Sources 1 and 2]"); these become numbered markers linked to sidenotes.
 */

const CITATION_RE = /\[(?:Sources?\s*\d+(?:\s*(?:,|;|and|&)\s*(?:Source\s*)?\d+)*)\]/gi;

/** Rewrite citations into markdown links `[N](#cite-N)` that the renderer turns into markers. */
export function linkCitations(markdown: string): string {
  return markdown.replace(CITATION_RE, (match) => {
    const nums = [...match.matchAll(/\d+/g)].map((m) => m[0]);
    return nums.map((n) => `[${n}](#cite-${n})`).join("");
  });
}

export function citedNumbers(markdown: string): Set<number> {
  const out = new Set<number>();
  for (const match of markdown.matchAll(CITATION_RE)) {
    for (const n of match[0].matchAll(/\d+/g)) out.add(Number(n[0]));
  }
  return out;
}

const STOP = new Set(
  "a an the of to in on for and or is are was were be by with as at from that this it its into than then which who what how why when can will not".split(
    " ",
  ),
);

function words(text: string): Set<string> {
  return new Set(
    (text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).filter((w) => w.length > 2 && !STOP.has(w)),
  );
}

export interface Excerpt {
  before: string;
  marked: string;
  after: string;
}

/**
 * Pick the sentence of a source chunk that best matches the answer text that cites it,
 * and return it with a little surrounding context, for the highlighter treatment.
 */
export function bestExcerpt(chunk: string, against: string, contextChars = 140): Excerpt {
  const text = chunk.replace(/\s+/g, " ").trim();
  const sentences = text.match(/[^.!?]+[.!?]+(?=\s|$)|[^.!?]+$/g) ?? [text];
  const target = words(against);
  let best = 0;
  let bestScore = -1;
  sentences.forEach((s, i) => {
    const w = words(s);
    let overlap = 0;
    for (const t of w) if (target.has(t)) overlap++;
    const score = overlap / Math.sqrt(w.size + 1);
    if (score > bestScore) {
      bestScore = score;
      best = i;
    }
  });
  const start = sentences.slice(0, best).join("").length;
  const marked = sentences[best].trim();
  const markedStart = text.indexOf(marked, Math.max(0, start - 2));
  const beforeFull = text.slice(0, markedStart);
  const afterFull = text.slice(markedStart + marked.length);
  // Trim context to whole words so excerpts never start or end mid-word.
  const before =
    beforeFull.length > contextChars
      ? "…" + beforeFull.slice(-contextChars).replace(/^\S*\s+/, "")
      : beforeFull;
  const after =
    afterFull.length > contextChars
      ? afterFull.slice(0, contextChars).replace(/\s+\S*$/, "") + "…"
      : afterFull;
  return { before, marked, after };
}

/** The answer text around each citation marker, used to pick what to highlight. */
export function textCiting(markdown: string, n: number): string {
  const parts = markdown.split(/(?<=[.!?])\s+/);
  const needle = new RegExp(`\\[(?:Sources?[^\\]]*?)\\b${n}\\b[^\\]]*\\]`, "i");
  const hits = parts.filter((p) => needle.test(p));
  return (hits.length ? hits : [markdown]).join(" ");
}
