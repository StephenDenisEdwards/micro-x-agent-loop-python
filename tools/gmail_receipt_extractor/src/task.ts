import { z } from "zod";
import type { Clients } from "./tools.js";
import { gmailSearch, gmailRead, gmailSaveAttachment } from "./tools.js";
import { writeFile } from "../../_runtime/src/utils.js";
import {
  extractReceiptsFromPdf,
  buildMarkdownReport,
  mergeReceipts,
  parseExistingReport,
  type ReceiptEntry,
} from "./processor.js";
import path from "node:path";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

export const SERVERS: string[] = ["google"];

export const TOOL_NAME = "gmail_receipt_extractor";
export const TOOL_DESCRIPTION =
  "Search Gmail for receipt emails on a given date, extract PDF attachment data, and produce a markdown expense report.";

export const TOOL_INPUT_SCHEMA = {
  email_date: z.string().describe("Date to search emails, format YYYY-MM-DD (required)"),
  subject_pattern: z
    .string()
    .default("Your Trainline receipt")
    .describe("Email subject pattern to search for"),
  output_file: z
    .string()
    .default("expense_report.md")
    .describe("Output markdown file path"),
  attachment_dir: z
    .string()
    .default("attachments")
    .describe("Directory for downloaded PDF attachments"),
};

export async function handleTool(
  input: {
    email_date: string;
    subject_pattern: string;
    output_file: string;
    attachment_dir: string;
  },
  clients: Clients,
  _profile: Record<string, unknown>,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const { email_date, subject_pattern, output_file, attachment_dir } = input;

  const dateParts = email_date.split("-");
  if (dateParts.length !== 3) {
    throw new Error(`Invalid email_date format. Expected YYYY-MM-DD, got: ${email_date}`);
  }
  const afterDate = email_date;
  const afterDt = new Date(email_date);
  afterDt.setDate(afterDt.getDate() + 1);
  const beforeDate = afterDt.toISOString().slice(0, 10);

  const query = `subject:"${subject_pattern}" after:${afterDate} before:${beforeDate}`;
  console.error(`[gmail_receipt_extractor] Searching Gmail with query: ${query}`);

  const messages = await gmailSearch(clients, query, 50);
  console.error(`[gmail_receipt_extractor] Found ${messages.length} matching email(s)`);

  const workDir = (config["workingDir"] as string | undefined) ?? process.cwd();
  const absAttachDir = path.isAbsolute(attachment_dir)
    ? attachment_dir
    : path.join(workDir, attachment_dir);

  mkdirSync(absAttachDir, { recursive: true });

  const receipts: ReceiptEntry[] = [];

  for (const msg of messages) {
    const messageId = msg["id"] as string | undefined;
    if (!messageId) continue;

    console.error(`[gmail_receipt_extractor] Reading message: ${messageId}`);
    const email = await gmailRead(clients, messageId);
    if (!email) continue;

    const body = (email["body"] as string) ?? "";
    const subject = (email["subject"] as string) ?? "";
    console.error(`[gmail_receipt_extractor] Email subject: ${subject}`);

    const pdfAttachments = extractPdfAttachmentInfo(body, email);

    if (pdfAttachments.length === 0) {
      console.error(
        `[gmail_receipt_extractor] No PDF attachments found in message ${messageId}, trying body extraction`,
      );
      const bodyReceipts = extractReceiptsFromEmailBody(body, subject, messageId);
      receipts.push(...bodyReceipts);
      continue;
    }

    for (const att of pdfAttachments) {
      const safeName = att.filename.replace(/[^a-zA-Z0-9._-]/g, "_");
      const localPath = path.join(absAttachDir, `${messageId}_${safeName}`);

      let pdfText: string | null = null;

      if (att.data) {
        const buf = Buffer.from(att.data, "base64");
        writeFileSync(localPath, buf);
        console.error(`[gmail_receipt_extractor] Saved attachment to ${localPath}`);
        pdfText = await extractTextFromPdf(localPath);
      } else if (att.attachmentId) {
        // Download via the gmail_save_attachment wrapper
        console.error(
          `[gmail_receipt_extractor] Downloading attachment ${att.filename} via gmail_save_attachment...`,
        );
        const saveResult = await gmailSaveAttachment(
          clients,
          messageId,
          att.attachmentId,
          att.filename,
          att.mimeType,
        );
        if (saveResult && existsSync(saveResult.path)) {
          console.error(`[gmail_receipt_extractor] Downloaded to ${saveResult.path}`);
          pdfText = await extractTextFromPdf(saveResult.path);
          // Copy to our target location
          const content = readFileSync(saveResult.path);
          writeFileSync(localPath, content);
        }
      } else {
        console.error(
          `[gmail_receipt_extractor] Attachment ${att.filename} has no inline data or attachmentId; skipping`,
        );
      }

      if (pdfText) {
        const parsed = extractReceiptsFromPdf(pdfText, att.filename, messageId, att.attachmentId ?? "");
        receipts.push(...parsed);
      }
    }
  }

  // Merge into any existing report so re-runs update (not overwrite) it and
  // never add the same (email, attachment) twice.
  const absOut = path.isAbsolute(output_file) ? output_file : path.join(workDir, output_file);
  let existing: ReceiptEntry[] = [];
  if (existsSync(absOut)) {
    try {
      existing = parseExistingReport(readFileSync(absOut, "utf-8"));
      console.error(`[gmail_receipt_extractor] Existing report has ${existing.length} receipt(s)`);
    } catch (err) {
      console.error(`[gmail_receipt_extractor] Could not parse existing report (starting fresh): ${err}`);
    }
  }

  const { merged, added } = mergeReceipts(existing, receipts);
  const report = buildMarkdownReport(merged, email_date, subject_pattern);
  const outPath = await writeFile(output_file, report, config);

  console.error(
    `[gmail_receipt_extractor] Wrote ${outPath} — ${added} new, ${merged.length} total (${receipts.length} extracted this run)`,
  );

  return {
    success: merged.length > 0,
    emails_found: messages.length,
    receipts_extracted: receipts.length,
    receipts_added: added,
    receipts_total: merged.length,
    output_file: outPath,
    report,
  };
}

function extractPdfAttachmentInfo(
  body: string,
  email: Record<string, unknown>,
): Array<{ filename: string; data?: string; attachmentId?: string; mimeType?: string }> {
  const attachments: Array<{ filename: string; data?: string; attachmentId?: string; mimeType?: string }> = [];

  const rawAttachments = email["attachments"] as Array<Record<string, unknown>> | undefined;
  if (rawAttachments && Array.isArray(rawAttachments)) {
    for (const att of rawAttachments) {
      const filename = String(att["filename"] ?? att["name"] ?? "attachment.pdf");
      if (filename.toLowerCase().endsWith(".pdf")) {
        attachments.push({
          filename,
          data: att["data"] as string | undefined,
          attachmentId: att["attachmentId"] as string | undefined,
          mimeType: att["mimeType"] as string | undefined,
        });
      }
    }
  }

  const pdfLinkRegex = /\[([^\]]*\.pdf[^\]]*)\]\s*\(([^)]+)\)/gi;
  let m: RegExpExecArray | null;
  while ((m = pdfLinkRegex.exec(body)) !== null) {
    attachments.push({ filename: m[1] });
  }

  return attachments;
}

async function extractTextFromPdf(pdfPath: string): Promise<string | null> {
  try {
    const { PDFParse } = await import("pdf-parse");
    const parser = new PDFParse({ data: new Uint8Array(readFileSync(pdfPath)) });
    try {
      const result = await parser.getText();
      return result.text.trim() ? result.text : null;
    } finally {
      await parser.destroy();
    }
  } catch (err) {
    console.error(`[gmail_receipt_extractor] PDF extraction failed for ${pdfPath}: ${err}`);
    return null;
  }
}

function extractReceiptsFromEmailBody(
  body: string,
  subject: string,
  messageId: string,
): ReceiptEntry[] {
  const dateMatch = body.match(/\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})\b/i);
  const amountMatch = body.match(/£([\d,]+\.\d{2})/);
  const routeMatch = body.match(/([A-Z][a-zA-Z\s]+)\s+to\s+([A-Z][a-zA-Z\s]+)/);

  if (!amountMatch) return [];

  const date = dateMatch ? dateMatch[1] : messageId.slice(0, 8);
  const description = routeMatch
    ? `${routeMatch[1].trim()} to ${routeMatch[2].trim()}`
    : subject;
  const amountStr = `£${amountMatch[1]}`;
  const amountPence = Math.round(parseFloat(amountMatch[1].replace(",", "")) * 100);

  return [{ date, description, amount: amountStr, amountPence, source: messageId, emailId: messageId, attachmentId: "" }];
}