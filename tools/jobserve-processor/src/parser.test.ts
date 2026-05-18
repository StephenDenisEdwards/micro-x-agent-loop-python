import { describe, expect, it } from "vitest";

import { parseSnapshotToJobRecord } from "./task.js";

// Real JobServe page text (as returned by a browser snapshot / innerText pull).
// Inlined so the test is self-contained.
const JOBSERVE_PAGE = `Skip to content

Contact JobServe:
+44 (0)1621 817335
Home
Job Search
Job Seekers
Employers
Recruiters
Listings
Help
Sign In/Register

Engineering Manager - Agentic AI - LLM - RAG - SaaS Organisation
Midlands - Excellent
Contract/Permanent
Posted by: InterCity Partners
Posted: Wednesday, 13 May 2026
Apply


Applicants must be eligible to work in the specified location

Engineering Manager - Agentic AI - LLM - RAG - SaaS Organisation

An exciting opportunity has arisen for a very strong Software Engineering Manager to join one of the fastest growing AI SaaS organisations, best in what they do and a real AI first business.

Their engineering teams are shipping AI-powered features into production right now, not experimenting, not planning, BUILDING!

The Opportunity

You'll lead three engineering squads building AI-first features into our SaaS products. This means owning both the people and the projects: coaching engineers, running delivery, and making sure the technical direction is sound.

What Will You Do?

Lead three engineering squads delivering AI-powered features into our SaaS products.
Provide genuine technical guidance to your squads.
Champion AI-first development across development and QA workflows.
Coach, mentor, and grow engineers through structured 1:1s, career development, and honest feedback.

What We Need From You?

Must Haves

You've been a software engineer. Not a project manager who worked near engineers.
You've managed engineering teams and can point to teams you've built, grown, or turned around.
You understand AI beyond the surface. You can explain how an LLM works, distinguish RAG from fine-tuning.

Preferred

Experience with .NET, C#, JavaScript or Azure, our primary stack.
Hands-on experience building AI-powered features.

Interested? Please apply and one of the team will be in touch!

AI Artificial Intelligence Team Management Technical Decisions Leadership LLM RAG

Location
Midlands, UK
Industry
IT
Duration
Long Term
Start Date
ASAP
Rate
Excellent
Employment Agency
InterCity Partners
Contact
Harry Burns
Reference
JSICP-EM3
Posted Date
13/05/2026 14:38:06
Permalink
http://www.jobserve.com/gGISI
`;

describe("parseSnapshotToJobRecord", () => {
  it("extracts title and metadata from a JobServe page", () => {
    const result = parseSnapshotToJobRecord(JOBSERVE_PAGE, "http://www.jobserve.com/gGISI");

    expect(result.title).toMatch(/Engineering Manager/i);
    expect(result.title).not.toMatch(/^skip to content$/i);

    expect(result.location).toBe("Midlands, UK");
    expect(result.rate).toBe("Excellent");
    expect(result.duration).toBe("Long Term");
    expect(result.employmentBusiness).toBe("InterCity Partners");
    expect(result.contact).toBe("Harry Burns");
    expect(result.posted).toBe("13/05/2026 14:38:06");
  });

  it("produces spec markdown that contains body content", () => {
    const result = parseSnapshotToJobRecord(JOBSERVE_PAGE, "http://www.jobserve.com/gGISI");

    expect(result.specMarkdown ?? "").toMatch(/AI-?first/i);
    expect(result.specMarkdown ?? "").toMatch(/squads/i);
  });
});

// Playwright's browser_snapshot returns the page's ARIA tree as YAML.
// This is what jobserve-processor actually receives in production.
const JOBSERVE_YAML_SNAPSHOT = `- generic [ref=e1]:
  - navigation [ref=e2]:
    - text [ref=e3]: Skip to content
    - link "JobServe: +44 (0)1621 817335" [ref=e40] [cursor=pointer]:
    - link "Home" [ref=e5] [cursor=pointer]:
    - link "Job Search" [ref=e6] [cursor=pointer]:
    - link "Sign In/Register" [ref=e11] [cursor=pointer]:
  - heading "Python Senior Engineer - Hybrid - Inside IR35 - London - May-13-2026 (gFo50)" [level=1] [ref=e100]:
  - generic [ref=e102]: Midlands - Excellent
  - generic [ref=e103]: Contract/Permanent
  - paragraph [ref=e104]: An exciting opportunity has arisen for a Senior Python Engineer to join the Recommendations team supporting an AI Stylist platform.
  - paragraph [ref=e105]: The Opportunity
  - paragraph [ref=e106]: You'll lead three engineering squads building AI-first features.
  - generic [ref=e135]: Location
  - generic [ref=e136]: London, UK
  - generic [ref=e137]: Industry
  - link "IT" [ref=e139] [cursor=pointer]:
  - generic [ref=e140]: Duration
  - generic [ref=e141]: 12 months
  - generic [ref=e142]: Start Date
  - generic [ref=e143]: ASAP
  - generic [ref=e144]: Rate
  - generic [ref=e145]: Competitive Day Rate - Negotiable
  - generic [ref=e146]: Employment Business
  - link "Hamilton Barnes" [ref=e148] [cursor=pointer]:
  - generic [ref=e149]: Contact
  - generic [ref=e150]: Harry Burns
  - generic [ref=e151]: Reference
  - generic [ref=e152]: JSICP-EM3
  - generic [ref=e153]: Posted Date
  - generic [ref=e154]: 13/05/2026 14:38:06
  - generic [ref=e155]: Permalink
  - link "http://www.jobserve.com/gGISI" [ref=e156] [cursor=pointer]:`;

describe("parseSnapshotToJobRecord (Playwright YAML accessibility tree)", () => {
  it("extracts title, metadata, and spec from ARIA-tree YAML", () => {
    const result = parseSnapshotToJobRecord(JOBSERVE_YAML_SNAPSHOT, "http://www.jobserve.com/gGISI");

    expect(result.title).toMatch(/Python Senior Engineer/i);
    expect(result.title).not.toMatch(/jobserve/i);
    expect(result.title).not.toMatch(/skip to content/i);

    expect(result.location).toBe("London, UK");
    expect(result.rate).toBe("Competitive Day Rate - Negotiable");
    expect(result.duration).toBe("12 months");
    expect(result.employmentBusiness).toBe("Hamilton Barnes");
    expect(result.contact).toBe("Harry Burns");
    expect(result.posted).toBe("13/05/2026 14:38:06");

    // Spec body must keep the prose but not the YAML markers
    expect(result.specMarkdown ?? "").toMatch(/AI Stylist platform/i);
    expect(result.specMarkdown ?? "").not.toMatch(/\[ref=e\d+\]/);
    expect(result.specMarkdown ?? "").not.toMatch(/\[cursor=/);
  });
});
