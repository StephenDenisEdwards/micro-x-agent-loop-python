import { describe, it, expect } from "vitest";

import { extractJobs, bandFor, parseAssessment, buildReport, type Job, type EmailRecord } from "./task.js";

const SAMPLE_EMAIL = `Your JobServe Daily Jobs By Email

--------------------------------------------------
Senior Solution Architect
London / Remote
£650 per day
A leading consultancy needs a senior architect for cloud migration.
https://www.jobserve.com/W1234ABCD.jsjob?src=alert&shid=99
--------------------------------------------------
AI Engineer
Manchester
£600 per day
Build LLM-powered agent products.
https://www.jobserve.com/W5678EFAB.jsjob?src=alert&shid=99
--------------------------------------------------
JobServe Ltd. Unsubscribe here.
`;

function makeJob(overrides: Partial<Job>): Job {
  return {
    title: "Role",
    url: "https://www.jobserve.com/W0.jsjob?src=x",
    blurb: "blurb",
    spec: "",
    retrieved: true,
    expired: false,
    errorReason: "",
    location: "",
    rate: "",
    duration: "",
    posted: "",
    score: 0,
    reason: "",
    coverLetter: "",
    emailDate: "2026-05-21",
    emailSubject: "AI roles",
    ...overrides,
  };
}

describe("extractJobs", () => {
  it("parses one job per dashed block that has a JobServe link", () => {
    const jobs = extractJobs(SAMPLE_EMAIL);
    expect(jobs).toHaveLength(2);
    expect(jobs[0].title).toBe("Senior Solution Architect");
    expect(jobs[0].url).toContain("W1234ABCD.jsjob");
    expect(jobs[1].title).toBe("AI Engineer");
  });

  it("keeps the full email block as the blurb (the expiry fallback)", () => {
    const jobs = extractJobs(SAMPLE_EMAIL);
    expect(jobs[0].blurb).toContain("£650 per day");
    expect(jobs[0].blurb).toContain("cloud migration");
  });

  it("deduplicates repeated links", () => {
    const dup =
      SAMPLE_EMAIL +
      "\n------------------\nDuplicate\nhttps://www.jobserve.com/W1234ABCD.jsjob?src=alert&shid=99\n";
    expect(extractJobs(dup)).toHaveLength(2);
  });

  it("recovers links from an HTML body with no dashed blocks", () => {
    const html = `<html><body><p>Roles</p><a href="https://www.jobserve.com/WAAAA1111.jsjob?src=x">View</a></body></html>`;
    const jobs = extractJobs(html);
    expect(jobs).toHaveLength(1);
    expect(jobs[0].url).toContain("WAAAA1111.jsjob");
  });

  it("returns nothing when there are no JobServe links", () => {
    expect(extractJobs("Just a normal email with no jobs in it.")).toHaveLength(0);
  });
});

describe("bandFor", () => {
  it("maps scores to bands", () => {
    expect(bandFor(90)).toContain("Top Matches");
    expect(bandFor(75)).toContain("Top Matches");
    expect(bandFor(60)).toContain("Strong");
    expect(bandFor(30)).toContain("Possible");
    expect(bandFor(10)).toContain("Weak");
    expect(bandFor(0)).toContain("Weak");
  });
});

describe("parseAssessment", () => {
  it("parses a plain JSON object", () => {
    const r = parseAssessment('{"ranking": 82, "reason": "Strong .NET overlap.", "coverLetter": "Dear team"}');
    expect(r.score).toBe(82);
    expect(r.reason).toContain(".NET");
    expect(r.coverLetter).toBe("Dear team");
  });

  it("tolerates code fences and surrounding prose", () => {
    const r = parseAssessment('Here you go:\n```json\n{"ranking": 47, "reason": "Partial fit.", "coverLetter": "Hi."}\n```');
    expect(r.score).toBe(47);
    expect(r.reason).toBe("Partial fit.");
  });

  it("clamps out-of-range scores", () => {
    expect(parseAssessment('{"ranking": 250, "reason": "x", "coverLetter": "y"}').score).toBe(100);
    expect(parseAssessment('{"ranking": -5, "reason": "x", "coverLetter": "y"}').score).toBe(0);
  });

  it("degrades gracefully on unparseable input", () => {
    expect(parseAssessment("not json at all").score).toBe(0);
  });
});

describe("buildReport", () => {
  it("renders banded sections, scores, reasons and cover letters", () => {
    const top = makeJob({
      title: "Senior Architect",
      url: "https://www.jobserve.com/W1.jsjob?src=x",
      spec: "Full specification for the architect role.",
      score: 88,
      reason: "Excellent architecture and cloud match.",
      coverLetter: "Dear Hiring Manager, I am keen to apply.",
    });
    const weak = makeJob({
      title: "Junior Developer",
      url: "https://www.jobserve.com/W2.jsjob?src=x",
      blurb: "Junior developer wanted, graduate level.",
      retrieved: false,
      errorReason: "HTTP 404",
      score: 18,
      reason: "Too junior for a senior candidate.",
      coverLetter: "",
    });
    const email: EmailRecord = { date: "2026-05-21", subject: "AI roles", jobs: [top, weak] };
    const report = buildReport("2026-05-21", [email], [top, weak]);

    expect(report).toContain("# JobServe Jobs — 21 May 2026");
    expect(report).toContain("## Top Matches");
    expect(report).toContain("## Weak Matches");
    expect(report).toContain("Senior Architect — 88/100");
    expect(report).toContain("Cover letter:");
    // An unretrieved job falls back to the email blurb, not an empty spec.
    expect(report).toContain("graduate level");
    expect(report).toContain("HTTP 404");
  });

  it("orders Top Matches before Weak Matches", () => {
    const top = makeJob({ title: "A", score: 90, url: "https://www.jobserve.com/W3.jsjob?src=x" });
    const weak = makeJob({ title: "B", score: 10, url: "https://www.jobserve.com/W4.jsjob?src=x" });
    const email: EmailRecord = { date: "2026-05-21", subject: "s", jobs: [weak, top] };
    const report = buildReport("2026-05-21", [email], [weak, top]);
    expect(report.indexOf("Top Matches")).toBeLessThan(report.indexOf("Weak Matches"));
  });
});
