import { describe, it, expect } from "vitest";
import {
  parseDate,
  parseAmount,
  parseRoute,
  extractReceiptsFromPdf,
  buildMarkdownReport,
  mergeReceipts,
  parseExistingReport,
  type ReceiptEntry,
} from "./processor.js";

describe("parseDate", () => {
  it("extracts a full date string", () => {
    expect(parseDate("Travel on 3 Feb 2026 from London")).toBe("3 Feb 2026");
  });

  it("returns empty string when no date found", () => {
    expect(parseDate("No date here")).toBe("");
  });

  it("handles two-digit day", () => {
    expect(parseDate("Issued 15 Dec 2025")).toBe("15 Dec 2025");
  });
});

describe("parseAmount", () => {
  it("extracts a simple pound amount", () => {
    const result = parseAmount("Total: £45.50");
    expect(result).not.toBeNull();
    expect(result!.display).toBe("£45.50");
    expect(result!.pence).toBe(4550);
  });

  it("handles comma-separated thousands", () => {
    const result = parseAmount("Fare: £1,234.00");
    expect(result).not.toBeNull();
    expect(result!.pence).toBe(123400);
  });

  it("returns null when no amount", () => {
    expect(parseAmount("No price here")).toBeNull();
  });
});

describe("parseRoute", () => {
  it("extracts a train route", () => {
    expect(parseRoute("London to Manchester £45.50")).toBe("London to Manchester");
  });

  it("returns empty string when no route", () => {
    expect(parseRoute("Just some random text")).toBe("");
  });
});

describe("extractReceiptsFromPdf", () => {
  it("returns receipt from well-formed PDF text", () => {
    const text = `Trainline Receipt\n3 Feb 2026\nLondon to Manchester\n£45.50\nThank you`;
    const results = extractReceiptsFromPdf(text, "test.pdf", "msg1", "att1");
    expect(results).toHaveLength(1);
    expect(results[0].amountPence).toBe(4550);
    expect(results[0].date).toBe("3 Feb 2026");
    expect(results[0].emailId).toBe("msg1");
    expect(results[0].attachmentId).toBe("att1");
  });

  it("picks the largest amount when multiple present", () => {
    const text = `Receipt\nVAT: £7.58\nTotal: £45.50\n1 Mar 2026`;
    const results = extractReceiptsFromPdf(text, "test.pdf", "msg1", "att1");
    expect(results[0].amountPence).toBe(4550);
  });

  it("returns empty array when no amounts found", () => {
    const results = extractReceiptsFromPdf("No price information", "test.pdf", "msg1", "att1");
    expect(results).toHaveLength(0);
  });
});

function entry(over: Partial<ReceiptEntry>): ReceiptEntry {
  return {
    date: "3 Feb 2026", description: "London to Manchester", amount: "£45.50",
    amountPence: 4550, source: "a.pdf", emailId: "msg1", attachmentId: "att1", ...over,
  };
}

describe("buildMarkdownReport", () => {
  it("produces a table with id columns and total", () => {
    const receipts = [
      entry({ amount: "£45.50", amountPence: 4550, emailId: "m1", attachmentId: "a1" }),
      entry({ description: "Manchester to London", amount: "£38.00", amountPence: 3800, emailId: "m2", attachmentId: "a2" }),
    ];
    const md = buildMarkdownReport(receipts, "2026-02-03", "Trainline receipt");
    expect(md).toContain("| Date | Description | Amount | Email ID | Attachment ID |");
    expect(md).toContain("£83.50");
    expect(md).toContain("**Total**");
    expect(md).toContain("m1");
    expect(md).toContain("a2");
  });

  it("renders no-receipts message when list is empty", () => {
    const md = buildMarkdownReport([], "2026-02-03", "Trainline receipt");
    expect(md).toContain("No receipts found");
  });
});

describe("mergeReceipts / parseExistingReport", () => {
  it("does not re-add an existing (email, attachment)", () => {
    const existing = [entry({ emailId: "m1", attachmentId: "a1" })];
    const fresh = [
      entry({ emailId: "m1", attachmentId: "a1" }),                 // duplicate
      entry({ emailId: "m2", attachmentId: "a2", amount: "£10.00", amountPence: 1000 }),
    ];
    const { merged, added } = mergeReceipts(existing, fresh);
    expect(added).toBe(1);
    expect(merged).toHaveLength(2);
  });

  it("round-trips through the markdown report", () => {
    const receipts = [entry({ emailId: "m1", attachmentId: "a1" })];
    const md = buildMarkdownReport(receipts, "2026-02-03", "Trainline receipt");
    const parsed = parseExistingReport(md);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].emailId).toBe("m1");
    expect(parsed[0].attachmentId).toBe("a1");
    expect(parsed[0].amountPence).toBe(4550);
    // re-merging the parsed-back rows adds nothing
    expect(mergeReceipts(parsed, receipts).added).toBe(0);
  });
});