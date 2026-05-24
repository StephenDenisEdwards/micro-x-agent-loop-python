import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, it, expect } from "vitest";

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
  filterAndRankJobs,
  TOOLS,
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
  it("converts the embedded HTML to clean markdown — no tags, no entities", () => {
    const text = cleanDescription(parseRssItems(SAMPLE_RSS)[0].description);
    expect(text).toContain("Tier 1 bank seeks Python & Spark developers");
    expect(text).not.toContain("<br");
    expect(text).not.toContain("<span");
    expect(text).not.toContain("&lt;");
    expect(text).not.toContain("&amp;");
  });

  it("strips the redundant leading Rate/Location header", () => {
    const text = cleanDescription(parseRssItems(SAMPLE_RSS)[0].description);
    // the metadata line above the description already shows these fields
    expect(text.startsWith("**Rate")).toBe(false);
    expect(text.startsWith("Rate:")).toBe(false);
    expect(text.startsWith("Location")).toBe(false);
  });

  it("resolves doubly-escaped ampersands", () => {
    const text = cleanDescription(parseRssItems(SAMPLE_RSS)[0].description);
    expect(text).toContain("Python & Spark");
  });

  it("injects bold + line breaks around known section headings (Hays-style)", () => {
    const raw =
      `&lt;br/&gt;I am working with a Tier 1 Bank seeking Python devs. ` +
      `What you'll need to succeed : Hands-on Python ` +
      `What you'll get in return : 12-month contract ` +
      `What you need to do now: Apply now.`;
    const text = cleanDescription(raw);
    expect(text).toContain("**What you'll need to succeed**");
    expect(text).toContain("**What you'll get in return**");
    expect(text).toContain("**What you need to do now**");
  });

  it("injects bold + line breaks around known section headings (no colon, title-case)", () => {
    const raw =
      `&lt;br/&gt;We are seeking a Senior Engineer. ` +
      `Key Responsibilities Translate requirements into actionable plans. ` +
      `What You Will Ideally Bring Strong expertise in .NET 8. ` +
      `Contract Details 6 months.`;
    const text = cleanDescription(raw);
    expect(text).toContain("**Key Responsibilities**");
    expect(text).toContain("**What You Will Ideally Bring**");
    expect(text).toContain("**Contract Details**");
  });

  it("trims the JobServe admin footer — drops noise, compacts kept fields onto one line", () => {
    // Synthetic description with a full admin footer block.
    const raw =
      `&lt;br/&gt;Senior Engineer&lt;br/&gt;&lt;br/&gt;Build great things.` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Type:&lt;/span&gt; Contract` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Contact:&lt;/span&gt; Sebastian` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Advertiser:&lt;/span&gt; Hamilton Barnes` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Email:&lt;/span&gt; foo@bar.com` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Country:&lt;/span&gt; UK` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Start Date:&lt;/span&gt; ASAP` +
      `&lt;br/&gt;&lt;span style="font-weight: bold;"&gt;Reference:&lt;/span&gt; JSSGM`;
    const text = cleanDescription(raw);
    expect(text).toContain("Build great things");
    expect(text).not.toContain("Reference:");
    expect(text).not.toContain("Email:");
    expect(text).not.toContain("Advertiser:");
    expect(text).not.toContain("Country:");
    expect(text).toContain("Contact: Sebastian");
    expect(text).toContain("Type: Contract");
    expect(text).toContain("Start Date: ASAP");
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

describe("filterAndRankJobs", () => {
  const jobs: StoredJob[] = [
    makeStored({ guid: "a", title: "Mid", score: 5, pubDate: "Fri, 15 May 2026 13:00:00 GMT" }),
    makeStored({ guid: "b", title: "Top", score: 9.2, pubDate: "Fri, 15 May 2026 11:00:00 GMT" }),
    makeStored({ guid: "c", title: "Low", score: 1, pubDate: "Fri, 15 May 2026 09:00:00 GMT" }),
    makeStored({ guid: "d", title: "TieEarlier", score: 5, pubDate: "Fri, 15 May 2026 08:00:00 GMT" }),
  ];

  it("sorts by score descending with no filtering by default", () => {
    const ranked = filterAndRankJobs(jobs, {});
    expect(ranked.map((j) => j.title)).toEqual(["Top", "Mid", "TieEarlier", "Low"]);
  });

  it("breaks score ties by newest pubDate first", () => {
    const ranked = filterAndRankJobs(jobs, {});
    const midIdx = ranked.findIndex((j) => j.title === "Mid");
    const tieIdx = ranked.findIndex((j) => j.title === "TieEarlier");
    expect(midIdx).toBeLessThan(tieIdx);
  });

  it("filters by minScore inclusive", () => {
    const ranked = filterAndRankJobs(jobs, { minScore: 5 });
    expect(ranked.map((j) => j.title)).toEqual(["Top", "Mid", "TieEarlier"]);
  });

  it("caps to maxItems after sorting", () => {
    const ranked = filterAndRankJobs(jobs, { maxItems: 2 });
    expect(ranked.map((j) => j.title)).toEqual(["Top", "Mid"]);
  });

  it("returns [] when nothing clears the minScore", () => {
    expect(filterAndRankJobs(jobs, { minScore: 10 })).toEqual([]);
  });
});

describe("search tool", () => {
  const tempDirs: string[] = [];

  afterEach(() => {
    for (const dir of tempDirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  const searchTool = TOOLS.find((t) => t.name === "search")!;

  function setupSidecar(date: string, jobs: StoredJob[]): { dir: string; profile: Record<string, unknown> } {
    const dir = mkdtempSync(join(tmpdir(), "jobserve-rss-search-"));
    tempDirs.push(dir);
    writeFileSync(join(dir, `${date}-js-rss-data.json`), serializeSidecar(jobs), "utf-8");
    return { dir, profile: { output_dir: dir } };
  }

  it("reads the sidecar for the given date and returns ranked jobs", async () => {
    const date = "2026-05-15";
    const jobs = [
      makeStored({ guid: "a", title: "Mid", score: 5 }),
      makeStored({ guid: "b", title: "Top", score: 9 }),
      makeStored({ guid: "c", title: "Low", score: 1 }),
    ];
    const { profile } = setupSidecar(date, jobs);

    const result = await searchTool.handler({ date }, {}, profile, {});

    expect(result.date).toBe(date);
    expect(result.total_in_file).toBe(3);
    expect(result.returned).toBe(3);
    const returned = result.jobs as StoredJob[];
    expect(returned.map((j) => j.title)).toEqual(["Top", "Mid", "Low"]);
  });

  it("applies minScore and maxItems", async () => {
    const date = "2026-05-15";
    const jobs = [
      makeStored({ guid: "a", title: "Mid", score: 5 }),
      makeStored({ guid: "b", title: "Top", score: 9 }),
      makeStored({ guid: "c", title: "Low", score: 1 }),
      makeStored({ guid: "d", title: "AlsoTop", score: 8 }),
    ];
    const { profile } = setupSidecar(date, jobs);

    const result = await searchTool.handler(
      { date, minScore: 5, maxItems: 2 },
      {},
      profile,
      {},
    );

    expect(result.returned).toBe(2);
    expect(result.total_in_file).toBe(4);
    expect((result.jobs as StoredJob[]).map((j) => j.title)).toEqual(["Top", "AlsoTop"]);
  });

  it("returns an empty result with a message when the sidecar is missing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "jobserve-rss-search-empty-"));
    tempDirs.push(dir);

    const result = await searchTool.handler(
      { date: "2026-05-15" },
      {},
      { output_dir: dir },
      {},
    );

    expect(result.total_in_file).toBe(0);
    expect(result.returned).toBe(0);
    expect(result.jobs).toEqual([]);
    expect(String(result.message)).toContain("No sidecar at");
  });

  it("rejects a non-ISO date", async () => {
    const result = await searchTool.handler({ date: "yesterday" }, {}, {}, {});
    expect(String(result.error)).toContain("YYYY-MM-DD");
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
