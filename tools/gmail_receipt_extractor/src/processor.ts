export type ReceiptEntry = {
  date: string;
  description: string;
  amount: string;
  amountPence: number;
  source: string;
  emailId: string;
  attachmentId: string;
};

const MONTH_ABBR =
  "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";

const DATE_RE = new RegExp(
  `\\b(\\d{1,2}\\s+(?:${MONTH_ABBR})\\s+\\d{4})\\b`,
  "i",
);

const AMOUNT_RE = /£([\d,]+\.\d{2})/g;

const ROUTE_RE =
  /([A-Z][a-zA-Z\s\-']+?)\s+to\s+([A-Z][a-zA-Z\s\-']+?)(?:\s+£|\s*\n|\s*$)/;

export function parseDate(text: string): string {
  const m = text.match(DATE_RE);
  return m ? m[1] : "";
}

export function parseAmount(text: string): { display: string; pence: number } | null {
  const re = /£([\d,]+\.\d{2})/;
  const m = text.match(re);
  if (!m) return null;
  const num = parseFloat(m[1].replace(/,/g, ""));
  return { display: `£${m[1]}`, pence: Math.round(num * 100) };
}

export function parseRoute(text: string): string {
  const m = text.match(ROUTE_RE);
  if (!m) return "";
  return `${m[1].trim()} to ${m[2].trim()}`;
}

export function extractReceiptsFromPdf(
  pdfText: string,
  source: string,
  emailId: string,
  attachmentId: string,
): ReceiptEntry[] {
  const receipts: ReceiptEntry[] = [];
  const lines = pdfText.split("\n").map((l) => l.trim()).filter(Boolean);
  const fullText = pdfText;

  const date = parseDate(fullText);

  const allAmounts: number[] = [];
  let amountMatch: RegExpExecArray | null;
  const amtRe = /£([\d,]+\.\d{2})/g;
  while ((amountMatch = amtRe.exec(fullText)) !== null) {
    allAmounts.push(Math.round(parseFloat(amountMatch[1].replace(/,/g, "")) * 100));
  }

  if (allAmounts.length === 0) return receipts;

  const maxAmount = Math.max(...allAmounts);
  const amountPence = maxAmount;
  const display = `£${(amountPence / 100).toFixed(2)}`;

  const route = parseRoute(fullText) || extractFallbackDescription(lines, source);

  receipts.push({
    date: date || source,
    description: route,
    amount: display,
    amountPence,
    source,
    emailId,
    attachmentId,
  });

  return receipts;
}

function extractFallbackDescription(lines: string[], source: string): string {
  for (const line of lines) {
    if (
      line.length > 5 &&
      line.length < 100 &&
      /[A-Za-z]/.test(line) &&
      !/^(total|vat|tax|date|ref|booking|order|receipt|thank|dear|from|to|subtotal)/i.test(line)
    ) {
      return line;
    }
  }
  return source;
}

export function buildMarkdownReport(
  receipts: ReceiptEntry[],
  searchDate: string,
  subjectPattern: string,
): string {
  const lines: string[] = [];
  lines.push(`# Expense Report`);
  lines.push(``);
  lines.push(`**Date:** ${searchDate}`);
  lines.push(`**Source:** Gmail receipts matching "${subjectPattern}"`);
  lines.push(`**Generated:** ${new Intl.DateTimeFormat("en-GB", { dateStyle: "long", timeStyle: "short" }).format(new Date())}`);
  lines.push(``);

  if (receipts.length === 0) {
    lines.push(`_No receipts found._`);
    return lines.join("\n");
  }

  lines.push(`| Date | Description | Amount | Email ID | Attachment ID |`);
  lines.push(`|------|-------------|--------|----------|---------------|`);

  let totalPence = 0;
  for (const r of receipts) {
    const safeDate = r.date.replace(/\|/g, "/");
    const safeDesc = r.description.replace(/\|/g, " ").replace(/\n/g, " ");
    const safeAmt = r.amount.replace(/\|/g, " ");
    const safeEmail = r.emailId.replace(/\|/g, "");
    const safeAtt = r.attachmentId.replace(/\|/g, "");
    lines.push(`| ${safeDate} | ${safeDesc} | ${safeAmt} | ${safeEmail} | ${safeAtt} |`);
    totalPence += r.amountPence;
  }

  const totalDisplay = `£${(totalPence / 100).toFixed(2)}`;
  lines.push(`| | **Total** | **${totalDisplay}** | | |`);
  lines.push(``);
  lines.push(`_${receipts.length} receipt(s) processed._`);

  return lines.join("\n");
}

/** Stable identity of a receipt — one row per (email, attachment). */
function receiptKey(r: ReceiptEntry): string {
  return `${r.emailId}|${r.attachmentId}`;
}

/**
 * Merge freshly-extracted receipts into the existing set, skipping any whose
 * (emailId, attachmentId) is already present. Existing rows are preserved and
 * kept first; returns the combined list and how many were newly added.
 */
export function mergeReceipts(
  existing: ReceiptEntry[],
  fresh: ReceiptEntry[],
): { merged: ReceiptEntry[]; added: number } {
  const seen = new Set(existing.map(receiptKey));
  const merged = [...existing];
  let added = 0;
  for (const r of fresh) {
    const key = receiptKey(r);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(r);
    added++;
  }
  return { merged, added };
}

/**
 * Recover prior receipts from a previously-written report so a re-run updates
 * (rather than overwrites) it and avoids re-adding duplicates. Parses the
 * markdown table this module emits; rows from an older format (no ID columns)
 * are ignored, so the first run after a format change simply starts fresh.
 */
export function parseExistingReport(md: string): ReceiptEntry[] {
  const out: ReceiptEntry[] = [];
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    if (!line.startsWith("|")) continue;
    const cells = line.split("|").map((c) => c.trim());
    if (cells.length && cells[0] === "") cells.shift();
    if (cells.length && cells[cells.length - 1] === "") cells.pop();
    if (cells.length < 5) continue;
    const [date, description, amount, emailId, attachmentId] = cells;
    if (!date || /^-+$/.test(date) || date.toLowerCase() === "date") continue;
    if (description.replace(/\*/g, "").trim().toLowerCase() === "total") continue;
    const amtNum = parseFloat(amount.replace(/[£,*\s]/g, ""));
    if (Number.isNaN(amtNum)) continue;
    out.push({
      date,
      description,
      amount: amount.replace(/\*/g, "").trim(),
      amountPence: Math.round(amtNum * 100),
      source: "",
      emailId,
      attachmentId,
    });
  }
  return out;
}