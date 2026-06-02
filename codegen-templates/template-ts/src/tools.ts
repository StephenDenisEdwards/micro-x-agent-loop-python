/**
 * Typed wrappers for MCP tools. Each function knows its server, handles errors, and returns parsed data.
 *
 * Hand-written; references strict input/output types from ./tool-types.ts (which IS generated).
 * When you change a wrapper's signature, prefer using the generated `<Tool>Args` / `<Tool>Result`
 * types so it can't drift from the upstream MCP schema. See documentation/docs/guides/codegen-tool-types.md.
 */

import type { IMcpClient } from "../../_runtime/src/mcp-client.js";
import type {
  // google
  GmailSearchArgs, GmailReadArgs, GmailSendArgs,
  CalendarListEventsArgs, CalendarCreateEventArgs, CalendarGetEventArgs,
  ContactsSearchArgs, ContactsListArgs, ContactsGetArgs,
  ContactsCreateArgs, ContactsUpdateArgs, ContactsDeleteArgs,
  // linkedin
  LinkedinJobsArgs, LinkedinJobsResult,
  LinkedinJobDetailArgs, LinkedinJobDetailResult,
  LinkedinDraftPostArgs, LinkedinDraftPostResult,
  LinkedinDraftArticleArgs, LinkedinDraftArticleResult,
  LinkedinPublishDraftArgs, LinkedinPublishDraftResult,
  // web
  WebSearchArgs, WebSearchResult,
  WebFetchArgs, WebFetchResult,
  // filesystem
  BashArgs, BashResult,
  ReadFileArgs, ReadFileResult,
  WriteFileArgs,
  GrepArgs, GrepResult,
  GlobArgs, GlobResult,
  // github
  ListReposArgs, GetFileArgs, SearchCodeArgs,
  ListPrsArgs, GetPrArgs, CreatePrArgs,
  ListIssuesArgs, CreateIssueArgs,
  // anthropic-admin
  AnthropicUsageArgs,
  // interview-assist
  IaHealthcheckArgs, IaListRecordingsArgs, IaAnalyzeSessionArgs,
  IaEvaluateSessionArgs, IaCompareStrategiesArgs, IaTuneThresholdArgs,
  IaRegressionTestArgs, IaCreateBaselineArgs, IaTranscribeOnceArgs,
  SttListDevicesArgs, SttStartSessionArgs, SttGetUpdatesArgs,
  SttGetSessionArgs, SttStopSessionArgs,
  // playwright
  BrowserNavigateArgs, BrowserSnapshotArgs, BrowserClickArgs,
  BrowserTypeArgs, BrowserSelectOptionArgs, BrowserFileUploadArgs,
  BrowserPressKeyArgs, BrowserEvaluateArgs, BrowserWaitForArgs,
} from "./tool-types.js";

export type Clients = Record<string, IMcpClient>;

function get(clients: Clients, server: string): IMcpClient {
  const client = clients[server];
  if (!client) throw new Error(`MCP server '${server}' not connected`);
  return client;
}

// ---------------------------------------------------------------------------
// Google — Gmail
// ---------------------------------------------------------------------------

export async function gmailSearch(
  clients: Clients, query: GmailSearchArgs["query"], maxResults: GmailSearchArgs["maxResults"] = 10,
): Promise<Array<Record<string, string>>> {
  const args: GmailSearchArgs = { query, maxResults };
  const result = await get(clients, "google").callTool("gmail_search", args);
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return ((result as Record<string, unknown>)["messages"] as Array<Record<string, string>>) ?? [];
  }
  if (typeof result === "string") return parseGmailSearchText(result);
  return [];
}

export async function gmailRead(
  clients: Clients, messageId: GmailReadArgs["messageId"],
): Promise<Record<string, string> | null> {
  const args: GmailReadArgs = { messageId };
  const result = await get(clients, "google").callTool("gmail_read", args);
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return result as Record<string, string>;
  }
  if (typeof result === "string" && result.trim()) {
    return parseGmailReadText(messageId, result);
  }
  return null;
}

function parseGmailSearchText(text: string): Array<Record<string, string>> {
  if (!text.trim() || text.includes("No emails found")) return [];
  const messages: Array<Record<string, string>> = [];
  let current: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const stripped = line.trim();
    if (line.startsWith("ID: ")) {
      if (Object.keys(current).length > 0) messages.push(current);
      current = { id: line.slice(4).trim() };
    } else if (stripped.startsWith("Date: ") && current["id"]) {
      current["date"] = stripped.slice(6);
    } else if (stripped.startsWith("From: ") && current["id"]) {
      current["from"] = stripped.slice(6);
    } else if (stripped.startsWith("Subject: ") && current["id"]) {
      current["subject"] = stripped.slice(9);
    } else if (stripped.startsWith("Snippet: ") && current["id"]) {
      current["snippet"] = stripped.slice(9);
    }
  }
  if (Object.keys(current).length > 0) messages.push(current);
  return messages;
}

function parseGmailReadText(messageId: string, text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  const lines = text.split("\n");
  let bodyStart = 0;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === "") { bodyStart = i + 1; break; }
    for (const key of ["From", "To", "Date", "Subject"]) {
      if (lines[i].startsWith(`${key}: `)) {
        headers[key.toLowerCase()] = lines[i].slice(key.length + 2);
        break;
      }
    }
  }
  const body = lines.slice(bodyStart).join("\n").trim();
  return {
    messageId,
    from: headers["from"] ?? "",
    to: headers["to"] ?? "",
    date: headers["date"] ?? "",
    subject: headers["subject"] ?? "",
    body,
  };
}

export async function gmailSend(
  clients: Clients,
  to: GmailSendArgs["to"], subject: GmailSendArgs["subject"], body: GmailSendArgs["body"],
): Promise<string> {
  const args: GmailSendArgs = { to, subject, body };
  const result = await get(clients, "google").callTool("gmail_send", args);
  return typeof result === "string" ? result : String(result);
}

// ---------------------------------------------------------------------------
// Google — Calendar
// ---------------------------------------------------------------------------

export async function calendarList(
  clients: Clients, options?: CalendarListEventsArgs,
): Promise<string> {
  const args: CalendarListEventsArgs = { maxResults: 10, ...options };
  const result = await get(clients, "google").callTool("calendar_list_events", args);
  return typeof result === "string" ? result : String(result);
}

export async function calendarCreate(
  clients: Clients,
  summary: CalendarCreateEventArgs["summary"],
  start: CalendarCreateEventArgs["start"],
  end: CalendarCreateEventArgs["end"],
  options?: Omit<CalendarCreateEventArgs, "summary" | "start" | "end">,
): Promise<string> {
  const args: CalendarCreateEventArgs = { summary, start, end, ...options };
  const result = await get(clients, "google").callTool("calendar_create_event", args);
  return typeof result === "string" ? result : String(result);
}

export async function calendarGet(
  clients: Clients, eventId: CalendarGetEventArgs["eventId"], calendarId: CalendarGetEventArgs["calendarId"] = "primary",
): Promise<string> {
  const args: CalendarGetEventArgs = { eventId, calendarId };
  const result = await get(clients, "google").callTool("calendar_get_event", args);
  return typeof result === "string" ? result : String(result);
}

// ---------------------------------------------------------------------------
// Google — Contacts
// ---------------------------------------------------------------------------

export async function contactsSearch(
  clients: Clients,
  query: ContactsSearchArgs["query"],
  maxResults: ContactsSearchArgs["pageSize"] = 10,
): Promise<string> {
  const args: ContactsSearchArgs = { query, pageSize: maxResults };
  const result = await get(clients, "google").callTool("contacts_search", args);
  return typeof result === "string" ? result : String(result);
}

export async function contactsList(
  clients: Clients, options?: ContactsListArgs,
): Promise<string> {
  const args: ContactsListArgs = { pageSize: 10, ...options };
  const result = await get(clients, "google").callTool("contacts_list", args);
  return typeof result === "string" ? result : String(result);
}

export async function contactsGet(
  clients: Clients, resourceName: ContactsGetArgs["resourceName"],
): Promise<string> {
  const args: ContactsGetArgs = { resourceName };
  const result = await get(clients, "google").callTool("contacts_get", args);
  return typeof result === "string" ? result : String(result);
}

export async function contactsCreate(
  clients: Clients,
  givenName: ContactsCreateArgs["givenName"],
  options?: Omit<ContactsCreateArgs, "givenName">,
): Promise<string> {
  const args: ContactsCreateArgs = {
    givenName,
    emailType: "other",
    phoneType: "other",
    ...options,
  };
  const result = await get(clients, "google").callTool("contacts_create", args);
  return typeof result === "string" ? result : String(result);
}

export async function contactsUpdate(
  clients: Clients,
  resourceName: ContactsUpdateArgs["resourceName"],
  etag: ContactsUpdateArgs["etag"],
  options?: Omit<ContactsUpdateArgs, "resourceName" | "etag">,
): Promise<string> {
  const args: ContactsUpdateArgs = {
    resourceName, etag,
    emailType: "other",
    phoneType: "other",
    ...options,
  };
  const result = await get(clients, "google").callTool("contacts_update", args);
  return typeof result === "string" ? result : String(result);
}

export async function contactsDelete(
  clients: Clients, resourceName: ContactsDeleteArgs["resourceName"],
): Promise<string> {
  const args: ContactsDeleteArgs = { resourceName };
  const result = await get(clients, "google").callTool("contacts_delete", args);
  return typeof result === "string" ? result : String(result);
}

// ---------------------------------------------------------------------------
// LinkedIn
// ---------------------------------------------------------------------------

export async function linkedinSearch(
  clients: Clients,
  keyword: string,
  options?: Omit<LinkedinJobsArgs, "keyword">,
): Promise<LinkedinJobsResult["jobs"]> {
  const args: LinkedinJobsArgs = {
    keyword,
    location: options?.location ?? "United Kingdom",
    dateSincePosted: options?.dateSincePosted ?? "past week",
    experienceLevel: options?.experienceLevel ?? "senior",
    limit: options?.limit ?? 10,
    sortBy: options?.sortBy ?? "recent",
    ...(options?.jobType ? { jobType: options.jobType } : {}),
    ...(options?.remoteFilter ? { remoteFilter: options.remoteFilter } : {}),
  };
  const result = await get(clients, "linkedin").callTool("linkedin_jobs", args);
  if (typeof result === "string") return [];
  return ((result as LinkedinJobsResult)["jobs"]) ?? [];
}

export async function linkedinDetail(
  clients: Clients, url: LinkedinJobDetailArgs["url"],
): Promise<LinkedinJobDetailResult | null> {
  const result = await get(clients, "linkedin").callTool("linkedin_job_detail", { url });
  if (typeof result === "string") return null;
  return result as LinkedinJobDetailResult;
}

export async function linkedinSearchWithDetails(
  clients: Clients,
  keyword: string,
  options?: Omit<LinkedinJobsArgs, "keyword"> & {
    batchSize?: number;
    delay?: number;
  },
): Promise<Array<LinkedinJobsResult["jobs"][number] & { detail: LinkedinJobDetailResult | Record<string, never> }>> {
  const { batchSize = 2, delay = 2000, ...searchOpts } = options ?? {};
  const jobs = await linkedinSearch(clients, keyword, searchOpts);
  if (jobs.length === 0) return [];

  const enriched: Array<LinkedinJobsResult["jobs"][number] & { detail: LinkedinJobDetailResult | Record<string, never> }> = [];
  for (let i = 0; i < jobs.length; i += batchSize) {
    if (i > 0) await new Promise((r) => setTimeout(r, delay));
    const batch = jobs.slice(i, i + batchSize);
    const results = await Promise.all(
      batch.map(async (job) => {
        const url = job["url"] as string | undefined;
        if (!url) return { ...job, detail: {} as Record<string, never> };
        const detail = await linkedinDetail(clients, url);
        return { ...job, detail: detail ?? ({} as Record<string, never>) };
      }),
    );
    enriched.push(...results);
  }
  return enriched;
}

export async function linkedinDraftPost(
  clients: Clients, args: LinkedinDraftPostArgs,
): Promise<LinkedinDraftPostResult | null> {
  const result = await get(clients, "linkedin").callTool("linkedin_draft_post", args);
  if (typeof result === "string") return null;
  return result as LinkedinDraftPostResult;
}

export async function linkedinDraftArticle(
  clients: Clients, args: LinkedinDraftArticleArgs,
): Promise<LinkedinDraftArticleResult | null> {
  const result = await get(clients, "linkedin").callTool("linkedin_draft_article", args);
  if (typeof result === "string") return null;
  return result as LinkedinDraftArticleResult;
}

export async function linkedinPublishDraft(
  clients: Clients, args: LinkedinPublishDraftArgs,
): Promise<LinkedinPublishDraftResult | null> {
  const result = await get(clients, "linkedin").callTool("linkedin_publish_draft", args);
  if (typeof result === "string") return null;
  return result as LinkedinPublishDraftResult;
}

// ---------------------------------------------------------------------------
// Web
// ---------------------------------------------------------------------------

export async function webSearch(
  clients: Clients, query: WebSearchArgs["query"], count: WebSearchArgs["count"] = 5,
): Promise<WebSearchResult["results"]> {
  const args: WebSearchArgs = { query, count };
  const result = await get(clients, "web").callTool("web_search", args);
  if (typeof result === "string") return [];
  return ((result as WebSearchResult)["results"]) ?? [];
}

export async function webFetch(
  clients: Clients, url: WebFetchArgs["url"], maxChars?: WebFetchArgs["maxChars"],
): Promise<WebFetchResult | null> {
  // No default cap — the agent's ToolResultOverrides is the authoritative
  // truncation/summarisation layer. Pass `maxChars` only when the task
  // genuinely wants to limit at the source (e.g. a fast probe).
  const args: WebFetchArgs = { url, ...(maxChars !== undefined ? { maxChars } : {}) };
  const result = await get(clients, "web").callTool("web_fetch", args);
  if (typeof result === "string") return null;
  return result as WebFetchResult;
}

// ---------------------------------------------------------------------------
// Filesystem
// ---------------------------------------------------------------------------

export async function fsRead(
  clients: Clients, path: ReadFileArgs["path"],
): Promise<string | null> {
  const args: ReadFileArgs = { path };
  const result = await get(clients, "filesystem").callTool("read_file", args);
  if (typeof result === "string") return result;
  return ((result as ReadFileResult)["content"]) ?? null;
}

export async function fsWrite(
  clients: Clients, path: WriteFileArgs["path"], content: WriteFileArgs["content"],
): Promise<boolean> {
  const args: WriteFileArgs = { path, content };
  const result = await get(clients, "filesystem").callTool("write_file", args);
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["success"] as boolean) ?? false;
  }
  return false;
}

export async function fsBash(
  clients: Clients, command: BashArgs["command"],
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  const args: BashArgs = { command };
  const result = await get(clients, "filesystem").callTool("bash", args);
  if (typeof result === "string") {
    return { stdout: result, stderr: "", exitCode: 0 };
  }
  const r = result as BashResult;
  return {
    stdout: r.stdout ?? "",
    stderr: r.stderr ?? "",
    exitCode: r.exit_code ?? 0,
  };
}

export async function fsGrep(
  clients: Clients,
  pattern: GrepArgs["pattern"],
  options?: Omit<GrepArgs, "pattern">,
): Promise<GrepResult> {
  const args: GrepArgs = { pattern, ...options };
  const result = await get(clients, "filesystem").callTool("grep", args);
  if (typeof result === "string") {
    return { mode: args.output_mode ?? "files_with_matches", results: result, match_count: 0, truncated: false };
  }
  return result as GrepResult;
}

export async function fsGlob(
  clients: Clients,
  pattern: GlobArgs["pattern"],
  options?: Omit<GlobArgs, "pattern">,
): Promise<GlobResult> {
  const args: GlobArgs = { pattern, ...options };
  const result = await get(clients, "filesystem").callTool("glob", args);
  if (typeof result === "string") {
    return { paths: result.split("\n").filter(Boolean), total: 0, truncated: false };
  }
  return result as GlobResult;
}

/** Append content to the end of an existing file. */
export async function fsAppend(
  clients: Clients, path: string, content: string,
): Promise<boolean> {
  const result = await get(clients, "filesystem").callTool("append_file", { path, content });
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["success"] as boolean) ?? false;
  }
  return false;
}

/** Delete a single file (refuses directories — use fsBash with rm -r for those). */
export async function fsDelete(
  clients: Clients, path: string,
): Promise<boolean> {
  const result = await get(clients, "filesystem").callTool("delete_file", { path });
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["deleted"] as boolean) ?? false;
  }
  return false;
}

/** Surgical exact-string edit. Returns the number of replacements made. */
export async function fsEdit(
  clients: Clients,
  path: string,
  oldString: string,
  newString: string,
  replaceAll = false,
): Promise<number> {
  const result = await get(clients, "filesystem").callTool("edit_file", {
    path, old_string: oldString, new_string: newString, replace_all: replaceAll,
  });
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["replacements"] as number) ?? 0;
  }
  return 0;
}

/** Save a persistent memory markdown file to the configured memory dir. */
export async function fsSaveMemory(
  clients: Clients, file: string, content: string,
): Promise<boolean> {
  const result = await get(clients, "filesystem").callTool("save_memory", { file, content });
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["success"] as boolean) ?? false;
  }
  return false;
}

// ---------------------------------------------------------------------------
// System info (server: "system-info")
// ---------------------------------------------------------------------------

/** OS / CPU / memory / runtime summary for this machine (human-readable text). */
export async function systemInfo(clients: Clients): Promise<string> {
  const result = await get(clients, "system-info").callTool("system_info", {});
  return typeof result === "string" ? result : JSON.stringify(result);
}

/** Disk usage for fixed drives (human-readable text). */
export async function diskInfo(clients: Clients): Promise<string> {
  const result = await get(clients, "system-info").callTool("disk_info", {});
  return typeof result === "string" ? result : JSON.stringify(result);
}

/** Network interface / IP-address summary (human-readable text). */
export async function networkInfo(clients: Clients): Promise<string> {
  const result = await get(clients, "system-info").callTool("network_info", {});
  return typeof result === "string" ? result : JSON.stringify(result);
}

// ---------------------------------------------------------------------------
// GitHub
// ---------------------------------------------------------------------------

export async function githubListRepos(
  clients: Clients, options?: ListReposArgs,
): Promise<Array<Record<string, unknown>>> {
  const args: ListReposArgs = {
    type: "all",
    sort: "updated",
    maxResults: 10,
    ...options,
  };
  const result = await get(clients, "github").callTool("list_repos", args);
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["repos"] as Array<Record<string, unknown>>) ?? [];
  }
  return [];
}

export async function githubGetFile(
  clients: Clients,
  repo: GetFileArgs["repo"], path: GetFileArgs["path"], ref?: GetFileArgs["ref"],
): Promise<Record<string, unknown>> {
  const args: GetFileArgs = { repo, path, ...(ref ? { ref } : {}) };
  const result = await get(clients, "github").callTool("get_file", args);
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return result as Record<string, unknown>;
  }
  return { type: "file", repo, path, content: typeof result === "string" ? result : "" };
}

export async function githubSearchCode(
  clients: Clients, query: SearchCodeArgs["query"],
  options?: Omit<SearchCodeArgs, "query">,
): Promise<Array<Record<string, unknown>>> {
  const args: SearchCodeArgs = { query, maxResults: 10, ...options };
  const result = await get(clients, "github").callTool("search_code", args);
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["results"] as Array<Record<string, unknown>>) ?? [];
  }
  return [];
}

export async function githubListPrs(
  clients: Clients, options?: ListPrsArgs,
): Promise<Array<Record<string, unknown>>> {
  const args: ListPrsArgs = { state: "open", maxResults: 10, ...options };
  const result = await get(clients, "github").callTool("list_prs", args);
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["prs"] as Array<Record<string, unknown>>) ?? [];
  }
  return [];
}

export async function githubGetPr(
  clients: Clients, repo: GetPrArgs["repo"], number: GetPrArgs["number"],
): Promise<Record<string, unknown>> {
  const args: GetPrArgs = { repo, number };
  const result = await get(clients, "github").callTool("get_pr", args);
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return result as Record<string, unknown>;
  }
  return { number, title: "", state: "", url: "" };
}

export async function githubCreatePr(
  clients: Clients,
  repo: CreatePrArgs["repo"],
  title: CreatePrArgs["title"],
  head: CreatePrArgs["head"],
  options?: Omit<CreatePrArgs, "repo" | "title" | "head">,
): Promise<Record<string, unknown>> {
  const args: CreatePrArgs = {
    repo, title, head,
    base: "main",
    draft: false,
    ...options,
  };
  const result = await get(clients, "github").callTool("create_pr", args);
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return result as Record<string, unknown>;
  }
  return { number: 0, title, head, base: args.base ?? "main", url: "" };
}

export async function githubListIssues(
  clients: Clients, options?: ListIssuesArgs,
): Promise<Array<Record<string, unknown>>> {
  const args: ListIssuesArgs = { state: "open", maxResults: 10, ...options };
  const result = await get(clients, "github").callTool("list_issues", args);
  if (result && typeof result === "object") {
    return ((result as Record<string, unknown>)["issues"] as Array<Record<string, unknown>>) ?? [];
  }
  return [];
}

export async function githubCreateIssue(
  clients: Clients,
  repo: CreateIssueArgs["repo"],
  title: CreateIssueArgs["title"],
  options?: Omit<CreateIssueArgs, "repo" | "title">,
): Promise<Record<string, unknown>> {
  const args: CreateIssueArgs = { repo, title, ...options };
  const result = await get(clients, "github").callTool("create_issue", args);
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return result as Record<string, unknown>;
  }
  return { number: 0, title, url: "", labels: options?.labels ?? [] };
}

// ---------------------------------------------------------------------------
// Anthropic Admin
// ---------------------------------------------------------------------------

export async function anthropicUsage(
  clients: Clients,
  action: AnthropicUsageArgs["action"],
  startingAt: AnthropicUsageArgs["starting_at"],
  options?: {
    endingAt?: AnthropicUsageArgs["ending_at"];
    bucketWidth?: AnthropicUsageArgs["bucket_width"];
    groupBy?: AnthropicUsageArgs["group_by"];
    limit?: AnthropicUsageArgs["limit"];
  },
): Promise<string> {
  const args: AnthropicUsageArgs = {
    action,
    starting_at: startingAt,
    ...(options?.endingAt ? { ending_at: options.endingAt } : {}),
    ...(options?.bucketWidth ? { bucket_width: options.bucketWidth } : {}),
    ...(options?.groupBy ? { group_by: options.groupBy } : {}),
    ...(options?.limit != null ? { limit: options.limit } : {}),
  };
  const result = await get(clients, "anthropic-admin").callTool("anthropic_usage", args);
  return typeof result === "string" ? result : String(result);
}

// ---------------------------------------------------------------------------
// Interview Assist — Analysis
// ---------------------------------------------------------------------------

export async function iaHealthcheck(
  clients: Clients, repoPath?: IaHealthcheckArgs["repo_path"],
): Promise<string> {
  const args: IaHealthcheckArgs = repoPath ? { repo_path: repoPath } : {};
  const result = await get(clients, "interview-assist").callTool("ia_healthcheck", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaListRecordings(
  clients: Clients,
  limit: IaListRecordingsArgs["limit"] = 30,
  repoPath?: IaListRecordingsArgs["repo_path"],
): Promise<string> {
  const args: IaListRecordingsArgs = { limit, ...(repoPath ? { repo_path: repoPath } : {}) };
  const result = await get(clients, "interview-assist").callTool("ia_list_recordings", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaAnalyzeSession(
  clients: Clients, sessionFile: IaAnalyzeSessionArgs["session_file"],
  options?: { repoPath?: IaAnalyzeSessionArgs["repo_path"]; timeoutSeconds?: IaAnalyzeSessionArgs["timeout_seconds"] },
): Promise<string> {
  const args: IaAnalyzeSessionArgs = {
    session_file: sessionFile,
    timeout_seconds: options?.timeoutSeconds ?? 900,
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_analyze_session", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaEvaluateSession(
  clients: Clients, sessionFile: IaEvaluateSessionArgs["session_file"],
  options?: {
    outputFile?: IaEvaluateSessionArgs["output_file"];
    model?: IaEvaluateSessionArgs["model"];
    groundTruthFile?: IaEvaluateSessionArgs["ground_truth_file"];
    repoPath?: IaEvaluateSessionArgs["repo_path"];
    timeoutSeconds?: IaEvaluateSessionArgs["timeout_seconds"];
  },
): Promise<string> {
  const args: IaEvaluateSessionArgs = {
    session_file: sessionFile,
    timeout_seconds: options?.timeoutSeconds ?? 1800,
    ...(options?.outputFile ? { output_file: options.outputFile } : {}),
    ...(options?.model ? { model: options.model } : {}),
    ...(options?.groundTruthFile ? { ground_truth_file: options.groundTruthFile } : {}),
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_evaluate_session", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaCompareStrategies(
  clients: Clients, sessionFile: IaCompareStrategiesArgs["session_file"],
  options?: {
    outputFile?: IaCompareStrategiesArgs["output_file"];
    repoPath?: IaCompareStrategiesArgs["repo_path"];
    timeoutSeconds?: IaCompareStrategiesArgs["timeout_seconds"];
  },
): Promise<string> {
  const args: IaCompareStrategiesArgs = {
    session_file: sessionFile,
    timeout_seconds: options?.timeoutSeconds ?? 1800,
    ...(options?.outputFile ? { output_file: options.outputFile } : {}),
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_compare_strategies", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaTuneThreshold(
  clients: Clients, sessionFile: IaTuneThresholdArgs["session_file"],
  options?: {
    optimize?: IaTuneThresholdArgs["optimize"];
    repoPath?: IaTuneThresholdArgs["repo_path"];
    timeoutSeconds?: IaTuneThresholdArgs["timeout_seconds"];
  },
): Promise<string> {
  const args: IaTuneThresholdArgs = {
    session_file: sessionFile,
    optimize: options?.optimize ?? "f1",
    timeout_seconds: options?.timeoutSeconds ?? 1800,
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_tune_threshold", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaRegressionTest(
  clients: Clients,
  baselineFile: IaRegressionTestArgs["baseline_file"],
  dataFile: IaRegressionTestArgs["data_file"],
  options?: {
    repoPath?: IaRegressionTestArgs["repo_path"];
    timeoutSeconds?: IaRegressionTestArgs["timeout_seconds"];
  },
): Promise<string> {
  const args: IaRegressionTestArgs = {
    baseline_file: baselineFile,
    data_file: dataFile,
    timeout_seconds: options?.timeoutSeconds ?? 1800,
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_regression_test", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaCreateBaseline(
  clients: Clients,
  dataFile: IaCreateBaselineArgs["data_file"],
  outputFile: IaCreateBaselineArgs["output_file"],
  options?: {
    version?: IaCreateBaselineArgs["version"];
    repoPath?: IaCreateBaselineArgs["repo_path"];
    timeoutSeconds?: IaCreateBaselineArgs["timeout_seconds"];
  },
): Promise<string> {
  const args: IaCreateBaselineArgs = {
    data_file: dataFile,
    output_file: outputFile,
    version: options?.version ?? "1.0",
    timeout_seconds: options?.timeoutSeconds ?? 1800,
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_create_baseline", args);
  return typeof result === "string" ? result : String(result);
}

export async function iaTranscribeOnce(
  clients: Clients,
  options?: {
    durationSeconds?: IaTranscribeOnceArgs["duration_seconds"];
    source?: IaTranscribeOnceArgs["source"];
    micDeviceId?: IaTranscribeOnceArgs["mic_device_id"];
    micDeviceName?: IaTranscribeOnceArgs["mic_device_name"];
    sampleRate?: IaTranscribeOnceArgs["sample_rate"];
    model?: IaTranscribeOnceArgs["model"];
    language?: IaTranscribeOnceArgs["language"];
    endpointingMs?: IaTranscribeOnceArgs["endpointing_ms"];
    utteranceEndMs?: IaTranscribeOnceArgs["utterance_end_ms"];
    diarize?: IaTranscribeOnceArgs["diarize"];
    outputFile?: IaTranscribeOnceArgs["output_file"];
    repoPath?: IaTranscribeOnceArgs["repo_path"];
    timeoutSeconds?: IaTranscribeOnceArgs["timeout_seconds"];
  },
): Promise<string> {
  const args: IaTranscribeOnceArgs = {
    duration_seconds: options?.durationSeconds ?? 8,
    source: options?.source ?? "microphone",
    sample_rate: options?.sampleRate ?? 16000,
    model: options?.model ?? "nova-2",
    language: options?.language ?? "en",
    endpointing_ms: options?.endpointingMs ?? 300,
    utterance_end_ms: options?.utteranceEndMs ?? 1000,
    diarize: options?.diarize ?? false,
    timeout_seconds: options?.timeoutSeconds ?? 180,
    ...(options?.micDeviceId ? { mic_device_id: options.micDeviceId } : {}),
    ...(options?.micDeviceName ? { mic_device_name: options.micDeviceName } : {}),
    ...(options?.outputFile ? { output_file: options.outputFile } : {}),
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("ia_transcribe_once", args);
  return typeof result === "string" ? result : String(result);
}

// ---------------------------------------------------------------------------
// Interview Assist — STT Sessions
// ---------------------------------------------------------------------------

export async function sttListDevices(
  clients: Clients, repoPath?: SttListDevicesArgs["repo_path"],
): Promise<string> {
  const args: SttListDevicesArgs = repoPath ? { repo_path: repoPath } : {};
  const result = await get(clients, "interview-assist").callTool("stt_list_devices", args);
  return typeof result === "string" ? result : String(result);
}

export async function sttStartSession(
  clients: Clients,
  options?: {
    source?: SttStartSessionArgs["source"];
    micDeviceId?: SttStartSessionArgs["mic_device_id"];
    micDeviceName?: SttStartSessionArgs["mic_device_name"];
    model?: SttStartSessionArgs["model"];
    language?: SttStartSessionArgs["language"];
    sampleRate?: SttStartSessionArgs["sample_rate"];
    endpointingMs?: SttStartSessionArgs["endpointing_ms"];
    utteranceEndMs?: SttStartSessionArgs["utterance_end_ms"];
    diarize?: SttStartSessionArgs["diarize"];
    chunkSeconds?: SttStartSessionArgs["chunk_seconds"];
    repoPath?: SttStartSessionArgs["repo_path"];
  },
): Promise<string> {
  const args: SttStartSessionArgs = {
    source: options?.source ?? "microphone",
    model: options?.model ?? "nova-2",
    language: options?.language ?? "en",
    sample_rate: options?.sampleRate ?? 16000,
    endpointing_ms: options?.endpointingMs ?? 300,
    utterance_end_ms: options?.utteranceEndMs ?? 1000,
    diarize: options?.diarize ?? false,
    chunk_seconds: options?.chunkSeconds ?? 4,
    ...(options?.micDeviceId ? { mic_device_id: options.micDeviceId } : {}),
    ...(options?.micDeviceName ? { mic_device_name: options.micDeviceName } : {}),
    ...(options?.repoPath ? { repo_path: options.repoPath } : {}),
  };
  const result = await get(clients, "interview-assist").callTool("stt_start_session", args);
  return typeof result === "string" ? result : String(result);
}

export async function sttGetUpdates(
  clients: Clients,
  sessionId: SttGetUpdatesArgs["session_id"],
  sinceSeq: SttGetUpdatesArgs["since_seq"] = 0,
  limit: SttGetUpdatesArgs["limit"] = 100,
): Promise<string> {
  const args: SttGetUpdatesArgs = { session_id: sessionId, since_seq: sinceSeq, limit };
  const result = await get(clients, "interview-assist").callTool("stt_get_updates", args);
  return typeof result === "string" ? result : String(result);
}

export async function sttGetSession(
  clients: Clients, sessionId: SttGetSessionArgs["session_id"],
): Promise<string> {
  const args: SttGetSessionArgs = { session_id: sessionId };
  const result = await get(clients, "interview-assist").callTool("stt_get_session", args);
  return typeof result === "string" ? result : String(result);
}

export async function sttStopSession(
  clients: Clients, sessionId: SttStopSessionArgs["session_id"],
): Promise<string> {
  const args: SttStopSessionArgs = { session_id: sessionId };
  const result = await get(clients, "interview-assist").callTool("stt_stop_session", args);
  return typeof result === "string" ? result : String(result);
}

// ---------------------------------------------------------------------------
// Playwright — Browser automation (via @playwright/mcp)
//
// IMPORTANT: the parameter for an element reference is `target` (a string from
// browser_snapshot's [ref=eN] markers, OR a CSS-style selector). It is NOT
// `ref` — that's just what the snapshot uses to label elements internally.
// All these wrappers enforce the correct shape via tool-types.ts.
// ---------------------------------------------------------------------------

export async function browserNavigate(
  clients: Clients, url: BrowserNavigateArgs["url"],
): Promise<unknown> {
  const args: BrowserNavigateArgs = { url };
  return get(clients, "playwright").callTool("browser_navigate", args);
}

export async function browserSnapshot(
  clients: Clients, options?: BrowserSnapshotArgs,
): Promise<unknown> {
  return get(clients, "playwright").callTool("browser_snapshot", options ?? {});
}

export async function browserClick(
  clients: Clients,
  target: BrowserClickArgs["target"],
  options?: Omit<BrowserClickArgs, "target">,
): Promise<unknown> {
  const args: BrowserClickArgs = { target, ...(options ?? {}) };
  return get(clients, "playwright").callTool("browser_click", args);
}

export async function browserType(
  clients: Clients,
  target: BrowserTypeArgs["target"],
  text: BrowserTypeArgs["text"],
  options?: Omit<BrowserTypeArgs, "target" | "text">,
): Promise<unknown> {
  const args: BrowserTypeArgs = { target, text, ...(options ?? {}) };
  return get(clients, "playwright").callTool("browser_type", args);
}

export async function browserSelectOption(
  clients: Clients,
  target: BrowserSelectOptionArgs["target"],
  values: BrowserSelectOptionArgs["values"],
  options?: Omit<BrowserSelectOptionArgs, "target" | "values">,
): Promise<unknown> {
  const args: BrowserSelectOptionArgs = { target, values, ...(options ?? {}) };
  return get(clients, "playwright").callTool("browser_select_option", args);
}

export async function browserFileUpload(
  clients: Clients,
  paths: NonNullable<BrowserFileUploadArgs["paths"]>,
): Promise<unknown> {
  const args: BrowserFileUploadArgs = { paths };
  return get(clients, "playwright").callTool("browser_file_upload", args);
}

export async function browserPressKey(
  clients: Clients, key: BrowserPressKeyArgs["key"],
): Promise<unknown> {
  const args: BrowserPressKeyArgs = { key };
  return get(clients, "playwright").callTool("browser_press_key", args);
}

export async function browserEvaluate(
  clients: Clients,
  fn: BrowserEvaluateArgs["function"],
  options?: Omit<BrowserEvaluateArgs, "function">,
): Promise<unknown> {
  const args: BrowserEvaluateArgs = { function: fn, ...(options ?? {}) };
  return get(clients, "playwright").callTool("browser_evaluate", args);
}

export async function browserClose(clients: Clients): Promise<unknown> {
  return get(clients, "playwright").callTool("browser_close", {});
}

export async function browserWaitFor(
  clients: Clients, options: BrowserWaitForArgs,
): Promise<unknown> {
  return get(clients, "playwright").callTool("browser_wait_for", options);
}
