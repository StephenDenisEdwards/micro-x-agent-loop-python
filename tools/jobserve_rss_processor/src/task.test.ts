import { describe, it, expect } from "vitest";

import {
  parseRssItems,
  cleanDescription,
  pubDateToISO,
  bandFor,
  parseAssessment,
  renderEntry,
  parseSidecar,
  serializeSidecar,
  buildBandedReport,
  type StoredJob,
} from "./task.js";

const SAMPLE_RSS = `<rss version="2.0"><channel><title>Feed</title><link>http://www.jobserve.com</link>
<item><title>(IT) Python Developer</title><link>http://www.jobserve.com/gb/en/RAAA111.jsap</link><description>&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Rate:&lt;/span&gt; £500pd&amp;nbsp;&amp;nbsp;&amp;nbsp;&lt;span style="font-weight: bold;"&gt;Location:&lt;/span&gt; London&lt;br/&gt;&lt;br/&gt;Tier 1 bank seeks Python &amp;amp; Spark developers.</description><guid>http://www.jobserve.com/gb/en/RAAA111.jsap</guid><pubDate>Fri, 15 May 2026 13:26:50 GMT</pubDate></item>
<item><title>(IT) Data Engineer</title><link>http://www.jobserve.com/gb/en/RBBB222.jsap</link><description>&lt;span style="font-weight: bold;"&gt;Rate:&lt;/span&gt; £300 per day&lt;br/&gt;Build data pipelines.</description><guid>http://www.jobserve.com/gb/en/RBBB222.jsap</guid><pubDate>Thu, 14 May 2026 09:00:00 GMT</pubDate></item>
</channel></rss>`;

function makeStored(overrides: Partial<StoredJob>): StoredJob {
  return {
    guid: "http://www.jobserve.com/gb/en/R0.jsap",
    title: "Role",
    link: "http://www.jobserve.com/gb/en/R0.jsap",
    location: "London",
    rate: "£600/day",
    pubDate: "Fri, 15 May 2026 13:26:50 GMT",
    score: 5,
    reason: "A reason.",
    coverLetter: "Dear team, I apply.",
    description: "Full job description text.",
    ...overrides,
  };
}

describe("parseRssItems", () => {
  it("extracts one record per <item>", () => {
    const items = parseRssItems(SAMPLE_RSS);
    expect(items).toHaveLength(2);
    expect(items[0].title).toBe("(IT) Python Developer");
    expect(items[0].link).toBe("http://www.jobserve.com/gb/en/RAAA111.jsap");
    expect(items[0].guid).toBe("http://www.jobserve.com/gb/en/RAAA111.jsap");
    expect(items[0].pubDate).toBe("Fri, 15 May 2026 13:26:50 GMT");
  });

  it("does not pick up channel-level <title>/<link>", () => {
    expect(parseRssItems(SAMPLE_RSS).map((i) => i.title)).not.toContain("Feed");
  });

  it("returns nothing for a feed with no items", () => {
    expect(parseRssItems("<rss><channel><title>x</title></channel></rss>")).toHaveLength(0);
  });
});

describe("cleanDescription", () => {
  it("decodes the double-encoded HTML to plain text", () => {
    const text = cleanDescription(parseRssItems(SAMPLE_RSS)[0].description);
    expect(text).toContain("Rate: £500pd");
    expect(text).toContain("Location: London");
    expect(text).not.toContain("<br");
    expect(text).not.toContain("&lt;");
  });

  it("resolves doubly-escaped ampersands", () => {
    const text = cleanDescription(parseRssItems(SAMPLE_RSS)[0].description);
    expect(text).toContain("Python & Spark");
  });
});

describe("pubDateToISO", () => {
  it("converts an RFC-822 pubDate to YYYY-MM-DD", () => {
    expect(pubDateToISO("Fri, 15 May 2026 13:26:50 GMT")).toBe("2026-05-15");
    expect(pubDateToISO("Thu, 14 May 2026 09:00:00 GMT")).toBe("2026-05-14");
  });

  it("returns unknown-date for an unparseable value", () => {
    expect(pubDateToISO("not a date")).toBe("unknown-date");
    expect(pubDateToISO("")).toBe("unknown-date");
  });
});

describe("bandFor", () => {
  it("maps a 0-10 score to the example-report bands", () => {
    expect(bandFor(8)).toBe("Top Match");
    expect(bandFor(7)).toBe("Top Match");
    expect(bandFor(5)).toBe("Solid Prospect");
    expect(bandFor(4.5)).toBe("Solid Prospect");
    expect(bandFor(3)).toBe("Unlikely Match");
    expect(bandFor(1)).toBe("Poor Match");
    expect(bandFor(0)).toBe("Poor Match");
  });
});

describe("parseAssessment", () => {
  it("parses JSON and keeps one decimal", () => {
    const r = parseAssessment('{"ranking": 7.94, "reason": "Strong .NET overlap.", "coverLetter": "Dear team"}');
    expect(r.score).toBe(7.9);
    expect(r.reason).toContain(".NET");
    expect(r.coverLetter).toBe("Dear team");
  });

  it("tolerates code fences", () => {
    const r = parseAssessment('```json\n{"ranking": 4.5, "reason": "Partial.", "coverLetter": "Hi."}\n```');
    expect(r.score).toBe(4.5);
  });

  it("clamps scores to 0-10", () => {
    expect(parseAssessment('{"ranking": 50, "reason": "x", "coverLetter": "y"}').score).toBe(10);
    expect(parseAssessment('{"ranking": -3, "reason": "x", "coverLetter": "y"}').score).toBe(0);
  });

  it("degrades gracefully on unparseable input", () => {
    expect(parseAssessment("not json").score).toBe(0);
  });
});

describe("renderEntry", () => {
  it("renders rank, title, score, cover letter and link — with no hidden data", () => {
    const entry = renderEntry(3, makeStored({ title: "Senior AI Architect", score: 8.2 }));
    expect(entry).toContain("### 3. Senior AI Architect");
    expect(entry).toContain("**Job description:**");
    expect(entry).toContain("Full job description text.");
    expect(entry).toContain("**Score: 8.2/10**");
    expect(entry).toContain("**Cover letter:**");
    expect(entry).toContain("[View on JobServe](http://www.jobserve.com/gb/en/R0.jsap)");
    expect(entry).not.toContain("<!--");
  });
});

describe("sidecar round-trip", () => {
  it("serialize -> parse recovers job records exactly", () => {
    const jobs = [
      makeStored({ guid: "g1", title: "Alpha", score: 8.1, reason: "good", coverLetter: "Dear A" }),
      makeStored({ guid: "g2", title: "Beta", score: 3.4, reason: "weak", coverLetter: "Dear B" }),
    ];
    const back = parseSidecar(serializeSidecar(jobs));
    expect(back).toEqual(jobs);
  });

  it("preserves tricky text and score precision (no encoding needed)", () => {
    const job = makeStored({
      guid: "g3",
      reason: 'uses --> arrows, <tags>, "quotes" and emoji 💰',
      score: 6.7,
    });
    const back = parseSidecar(serializeSidecar([job]));
    expect(back).toHaveLength(1);
    expect(back[0].reason).toBe('uses --> arrows, <tags>, "quotes" and emoji 💰');
    expect(back[0].score).toBe(6.7);
  });

  it("coerces missing/odd fields and drops records with no guid", () => {
    const raw = JSON.stringify([
      { guid: "g4", title: "Has guid" }, // missing fields -> defaulted
      { title: "No guid or link" }, // dropped
      { link: "g5-link", score: 99 }, // guid falls back to link, score clamped
    ]);
    const back = parseSidecar(raw);
    expect(back).toHaveLength(2);
    expect(back[0].guid).toBe("g4");
    expect(back[0].reason).toBe("");
    expect(back[0].description).toBe("");
    expect(back[1].guid).toBe("g5-link");
    expect(back[1].score).toBe(10);
  });

  it("returns [] for malformed or non-array JSON", () => {
    expect(parseSidecar("not json")).toEqual([]);
    expect(parseSidecar('{"not":"an array"}')).toEqual([]);
    expect(parseSidecar("")).toEqual([]);
  });
});

describe("buildBandedReport", () => {
  it("groups jobs into score-banded sections, Top before Poor, with a summary", () => {
    const jobs = [
      makeStored({ guid: "a", title: "Weak role", score: 1.5 }),
      makeStored({ guid: "b", title: "Great role", score: 8.5 }),
      makeStored({ guid: "c", title: "Okay role", score: 5.0 }),
    ];
    const report = buildBandedReport("2026-05-15", jobs);
    expect(report).toContain("# JobServe RSS Jobs — 15 May 2026");
    expect(report).toContain("## Summary");
    expect(report).toContain("## Top Matches (7–10)");
    expect(report).toContain("## Poor Matches (0–1.9)");
    expect(report.indexOf("Top Matches")).toBeLessThan(report.indexOf("Poor Matches"));
    expect(report).toContain("### 1. Great role");
    expect(report).toContain("Average score:");
  });

  it("sorts strictly by score regardless of input order", () => {
    const jobs = [
      makeStored({ guid: "a", title: "Mid", score: 5 }),
      makeStored({ guid: "b", title: "High", score: 9 }),
      makeStored({ guid: "c", title: "Low", score: 2 }),
    ];
    const report = buildBandedReport("2026-05-15", jobs);
    expect(report.indexOf("High")).toBeLessThan(report.indexOf("Mid"));
    expect(report.indexOf("Mid")).toBeLessThan(report.indexOf("Low"));
  });
});
