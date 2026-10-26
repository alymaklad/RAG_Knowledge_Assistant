import { describe, expect, it } from "vitest";
import { bestExcerpt, citedNumbers, linkCitations, textCiting } from "./citations";
import { parseSseBlock, readSse } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

describe("sse", () => {
  it("parses event and JSON data", () => {
    expect(parseSseBlock('event: token\ndata: {"t":"Hi"}')).toEqual({
      event: "token",
      data: { t: "Hi" },
    });
  });

  it("reassembles events split across network chunks", async () => {
    const events = [];
    for await (const ev of readSse(
      streamOf(['event: sources\ndata: [{"ind', 'ex":1}]\n\nevent: tok', 'en\ndata: {"t":"a"}\n\n']),
    )) {
      events.push(ev);
    }
    expect(events).toEqual([
      { event: "sources", data: [{ index: 1 }] },
      { event: "token", data: { t: "a" } },
    ]);
  });
});

describe("citations", () => {
  it("links single, listed and plural citations", () => {
    expect(linkCitations("A [Source 1]. B [Source 2, Source 3]. C [Sources 4 and 5].")).toBe(
      "A [1](#cite-1). B [2](#cite-2)[3](#cite-3). C [4](#cite-4)[5](#cite-5).",
    );
  });

  it("collects cited numbers", () => {
    expect([...citedNumbers("x [Source 2] y [Source 2, Source 4]")].sort()).toEqual([2, 4]);
  });

  it("finds the answer sentence that cites a source", () => {
    const answer = "Cats purr [Source 1]. Dogs bark loudly [Source 2].";
    expect(textCiting(answer, 2)).toBe("Dogs bark loudly [Source 2].");
  });

  it("highlights the best-matching sentence of a chunk", () => {
    const chunk =
      "Bayesian networks are graphs. The Markov blanket contains parents, children and co-parents. Inference is hard.";
    const ex = bestExcerpt(chunk, "The Markov blanket is parents, children, co-parents");
    expect(ex.marked).toBe("The Markov blanket contains parents, children and co-parents.");
    expect(ex.before).toBe("Bayesian networks are graphs. ");
    expect(ex.after).toBe(" Inference is hard.");
  });
});

describe("excerpt context", () => {
  it("never cuts words at the context edges", () => {
    const words = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron";
    const filler = `${words}. `;
    const chunk = filler.repeat(4) + "The target sentence is here. " + filler.repeat(4);
    const ex = bestExcerpt(chunk, "target sentence", 50);
    const vocab = new Set(words.split(" "));
    expect(ex.marked).toBe("The target sentence is here.");
    expect(ex.before.startsWith("…")).toBe(true);
    expect(vocab.has(ex.before.slice(1).split(" ")[0].replace(".", ""))).toBe(true);
    expect(ex.after.endsWith("…")).toBe(true);
    const lastWord = ex.after.slice(0, -1).trim().split(" ").pop()!.replace(".", "");
    expect(vocab.has(lastWord)).toBe(true);
  });
});
