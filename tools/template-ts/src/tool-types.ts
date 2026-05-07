// ============================================================
// AUTO-GENERATED — do not edit by hand.
// Regenerate with:  npm run regen-tool-types  (in tools/template-ts/)
// Source of truth: upstream MCP server inputSchema / outputSchema.
// ============================================================

// ----------------------------------------------------------------------
// google
// ----------------------------------------------------------------------

/** Search Gmail using Gmail search syntax (e.g. 'is:unread', 'from:someone@example.com', 'subject:hello'). Returns a list of matching emails with ID, date, from, subject, and snippet. */
export type GmailSearchArgs = {
  query: string; /** Gmail search query (e.g. 'is:unread', 'from:boss@co.com newer_than:7d') */
  maxResults?: number; /** Max number of results (default 10) */
};

export type GmailSearchResult = Record<string, unknown>;

/** Read the full content of a Gmail email by its message ID (from gmail_search results). */
export type GmailReadArgs = {
  messageId: string; /** The Gmail message ID (from gmail_search results) */
};

export type GmailReadResult = Record<string, unknown>;

/** Send an email from your Gmail account. */
export type GmailSendArgs = {
  to: string; /** Recipient email address */
  subject: string; /** Email subject line */
  body: string; /** Email body (plain text) */
};

export type GmailSendResult = Record<string, unknown>;

/** List Google Calendar events by date range or search query. Returns event ID, summary, start/end times, location, status, and organizer. Defaults to today's events if no time range is specified. */
export type CalendarListEventsArgs = {
  timeMin?: string; /** Start of time range in ISO 8601 format (e.g. '2025-06-01T00:00:00Z'). Defaults to start of today. */
  timeMax?: string; /** End of time range in ISO 8601 format (e.g. '2025-06-01T23:59:59Z'). Defaults to end of today. */
  query?: string; /** Free-text search query to filter events (searches summary, description, location, attendees). */
  maxResults?: number; /** Max number of results (default 10). */
  calendarId?: string; /** Calendar ID (default 'primary'). */
};

export type CalendarListEventsResult = Record<string, unknown>;

/** Create a Google Calendar event. Supports timed events (ISO 8601 with time) and all-day events (YYYY-MM-DD date only). Can add attendees by email. */
export type CalendarCreateEventArgs = {
  summary: string; /** Event title. */
  start: string; /** Start time in ISO 8601 (e.g. '2025-06-15T14:00:00') or date only for all-day events (e.g. '2025-06-15'). */
  end: string; /** End time in ISO 8601 (e.g. '2025-06-15T15:00:00') or date only for all-day events (e.g. '2025-06-16'). */
  description?: string; /** Event description/notes. */
  location?: string; /** Event location. */
  attendees?: string; /** Comma-separated email addresses of attendees. */
  calendarId?: string; /** Calendar ID (default 'primary'). */
};

export type CalendarCreateEventResult = Record<string, unknown>;

/** Get full details of a Google Calendar event by its event ID. */
export type CalendarGetEventArgs = {
  eventId: string; /** The event ID (from calendar_list_events results). */
  calendarId?: string; /** Calendar ID (default 'primary'). */
};

export type CalendarGetEventResult = Record<string, unknown>;

/** Search Google Contacts by name, email, phone number, or other fields. Returns matching contacts with name, email, and phone number. */
export type ContactsSearchArgs = {
  query: string; /** Search query (name, email, phone number, etc.). */
  pageSize?: number; /** Max number of results (default 10, max 30). */
};

export type ContactsSearchResult = Record<string, unknown>;

/** List Google Contacts. Returns contacts with name, email, and phone number. Supports pagination via pageToken. */
export type ContactsListArgs = {
  pageSize?: number; /** Number of contacts to return (default 10, max 100). */
  pageToken?: string; /** Page token from a previous response for pagination. */
  sortOrder?: string; /** Sort order: 'LAST_MODIFIED_ASCENDING', 'LAST_MODIFIED_DESCENDING', 'FIRST_NAME_ASCENDING', or 'LAST_NAME_ASCENDING'. */
};

export type ContactsListResult = Record<string, unknown>;

/** Get full details of a Google Contact by resource name. Returns name, emails, phones, addresses, organization, biography, and etag (needed for updates). */
export type ContactsGetArgs = {
  resourceName: string; /** The contact's resource name (e.g. 'people/c1234567890'). */
};

export type ContactsGetResult = Record<string, unknown>;

/** Create a new Google Contact. At minimum requires a given name. Can also set family name, email, phone, organization, and job title. */
export type ContactsCreateArgs = {
  givenName: string; /** First/given name (required). */
  familyName?: string; /** Last/family name. */
  email?: string; /** Email address. */
  emailType?: string; /** Email type: 'home', 'work', or 'other' (default 'other'). */
  phone?: string; /** Phone number. */
  phoneType?: string; /** Phone type: 'home', 'work', 'mobile', or 'other' (default 'other'). */
  organization?: string; /** Company/organization name. */
  jobTitle?: string; /** Job title. */
};

export type ContactsCreateResult = Record<string, unknown>;

/** Update an existing Google Contact. Requires the resource name and etag (from contacts_get). Provide only the fields you want to change. */
export type ContactsUpdateArgs = {
  resourceName: string; /** The contact's resource name (e.g. 'people/c1234567890'). */
  etag: string; /** The contact's etag (from contacts_get, required for concurrency control). */
  givenName?: string; /** New first/given name. */
  familyName?: string; /** New last/family name. */
  email?: string; /** New email address (replaces existing emails). */
  emailType?: string; /** Email type: 'home', 'work', or 'other' (default 'other'). */
  phone?: string; /** New phone number (replaces existing phones). */
  phoneType?: string; /** Phone type: 'home', 'work', 'mobile', or 'other' (default 'other'). */
  organization?: string; /** New company/organization name. */
  jobTitle?: string; /** New job title. */
};

export type ContactsUpdateResult = Record<string, unknown>;

/** Delete a Google Contact by resource name. This action cannot be undone. */
export type ContactsDeleteArgs = {
  resourceName: string; /** The contact's resource name (e.g. 'people/c1234567890'). */
};

export type ContactsDeleteResult = Record<string, unknown>;

// ----------------------------------------------------------------------
// linkedin
// ----------------------------------------------------------------------

/** Search for job postings on LinkedIn. Returns job title, company, location, date, salary, and URL. */
export type LinkedinJobsArgs = {
  keyword: string; /** Job search keyword (e.g. 'software engineer') (min 1 chars) */
  location?: string; /** Job location (e.g. 'New York', 'Remote') */
  dateSincePosted?: "past month" | "past week" | "24hr"; /** Recency filter */
  jobType?: "full time" | "part time" | "contract" | "temporary" | "internship"; /** Employment type */
  remoteFilter?: "on site" | "remote" | "hybrid"; /** Work arrangement */
  experienceLevel?: "internship" | "entry level" | "associate" | "senior" | "director" | "executive"; /** Experience level */
  limit?: number; /** Max number of results to return (default 10) (integer, 1–50, default: 10) */
  sortBy?: "recent" | "relevant"; /** Sort order */
};

export type LinkedinJobsResult = {
  jobs: Array<{
  index: number; /**  (integer) */
  title: string;
  company: string;
  location: string;
  posted: string;
  salary: string;
  url: string;
}>;
  total_found: number; /**  (integer) */
};

/** Fetch the full job specification/description from a LinkedIn job URL. Use this after linkedin_jobs to get complete details for a specific posting. */
export type LinkedinJobDetailArgs = {
  url: string; /** The LinkedIn job URL (e.g. from a linkedin_jobs search result) (min 1 chars) */
};

export type LinkedinJobDetailResult = {
  title: string;
  company: string;
  location: string;
  description: string;
  url: string;
};

/** Create a draft LinkedIn text post for review before publishing. Returns a draft_id that can be passed to linkedin_publish_draft to publish. */
export type LinkedinDraftPostArgs = {
  text: string; /** Post text content (max 3000 characters) (1–3000 chars) */
  visibility?: "PUBLIC" | "CONNECTIONS"; /** Post visibility (default: "PUBLIC") */
};

export type LinkedinDraftPostResult = {
  draft_id: string;
  preview: string;
  visibility: string;
  char_count: number; /**  (integer) */
};

/** Create a draft LinkedIn article share (link post with preview card) for review before publishing. Returns a draft_id that can be passed to linkedin_publish_draft to publish. */
export type LinkedinDraftArticleArgs = {
  url: string; /** URL of the article to share (format: uri) */
  title: string; /** Article title for the share card (1–200 chars) */
  description: string; /** Article description for the share card (1–500 chars) */
  commentary?: string; /** Optional commentary text above the article card (max 3000 chars) */
  visibility?: "PUBLIC" | "CONNECTIONS"; /** Post visibility (default: "PUBLIC") */
};

export type LinkedinDraftArticleResult = {
  draft_id: string;
  preview: string;
  url: string;
  visibility: string;
};

/** Publish a previously created LinkedIn draft. Requires a draft_id from linkedin_draft_post or linkedin_draft_article. Drafts expire after 10 minutes. */
export type LinkedinPublishDraftArgs = {
  draft_id: string; /** Draft ID returned by linkedin_draft_post or linkedin_draft_article (format: uuid) */
};

export type LinkedinPublishDraftResult = {
  post_urn: string;
  post_url: string;
};

// ----------------------------------------------------------------------
// web
// ----------------------------------------------------------------------

/** Fetch a STATIC resource via HTTP GET and return it as text. Use only for plain HTML with no JavaScript, JSON/REST APIs, RSS feeds, robots.txt, or other text endpoints. Does NOT execute JavaScript, follow auth flows, or render single-page apps — for those, use the browser_* tools (Playwright) instead. If the response from this tool looks empty or JS-skeleton, switch to browser_navigate. */
export type WebFetchArgs = {
  url: string; /** The HTTP or HTTPS URL to fetch (min 1 chars) */
  maxChars?: number; /** Maximum characters of content to return (default 50000). Content beyond this limit is truncated with a notice. (integer, ≥ 1, default: 50000) */
};

export type WebFetchResult = {
  url: string;
  final_url: string;
  status_code: number; /**  (integer) */
  content_type: string;
  title: string;
  content: string;
  content_length: number; /**  (integer) */
  truncated: boolean;
};

/** Search the web and return a list of results with titles, URLs, and descriptions. Use this to discover URLs before fetching their full content with web_fetch. */
export type WebSearchArgs = {
  query: string; /** Search query (max 400 characters) (1–400 chars) */
  count?: number; /** Number of results to return (1–20, default 5) (integer, 1–20, default: 5) */
};

export type WebSearchResult = {
  query: string;
  results: Array<{
  title: string;
  url: string;
  description: string;
}>;
  total_results: number; /**  (integer) */
};

// ----------------------------------------------------------------------
// filesystem
// ----------------------------------------------------------------------

/** Execute a shell command and return its output (stdout + stderr). */
export type BashArgs = {
  command: string; /** The shell command to execute */
};

export type BashResult = {
  stdout: string;
  stderr: string;
  exit_code: number; /**  (integer) */
  timed_out: boolean;
};

/** Read the contents of a file and return it as text. Supports plain text files and .docx documents. */
export type ReadFileArgs = {
  path: string; /** Absolute or relative path to the file to read (min 1 chars) */
};

export type ReadFileResult = {
  content: string;
  path: string;
  size_bytes: number; /**  (integer) */
};

/** Write content to a file, creating it if it doesn't exist. Parent directories are created automatically. */
export type WriteFileArgs = {
  path: string; /** Absolute or relative path to the file to write (min 1 chars) */
  content: string; /** The content to write to the file */
};

export type WriteFileResult = {
  success: boolean;
  path: string;
  size_bytes: number; /**  (integer) */
};

// ----------------------------------------------------------------------
// github
// ----------------------------------------------------------------------

/** List pull requests for a GitHub repository. If repo is omitted, lists PRs authored by you across all repos. */
export type ListPrsArgs = {
  repo?: string; /** Repository in owner/repo format. If omitted, lists your PRs across all repos. */
  state?: "open" | "closed" | "all"; /** Filter by state (default: open) (default: "open") */
  author?: string; /** Filter by author username */
  maxResults?: number; /** Max results (default 10, max 100) (integer, 1–100, default: 10) */
};

export type ListPrsResult = Record<string, unknown>;

/** Get detailed information about a specific pull request, including diff stats, reviews, and CI status. */
export type GetPrArgs = {
  repo: string; /** Repository in owner/repo format (min 1 chars) */
  number: number; /** Pull request number (integer, ≥ 1) */
};

export type GetPrResult = Record<string, unknown>;

/** Create a pull request in a GitHub repository. */
export type CreatePrArgs = {
  repo: string; /** Repository in owner/repo format (min 1 chars) */
  title: string; /** PR title (min 1 chars) */
  head: string; /** Branch containing changes (min 1 chars) */
  body?: string; /** PR description (markdown) */
  base?: string; /** Branch to merge into (default: main) (default: "main") */
  draft?: boolean; /** Create as draft PR (default: false) (default: false) */
};

export type CreatePrResult = Record<string, unknown>;

/** List or search issues in a GitHub repository. If repo is omitted or a query is provided, uses GitHub search. */
export type ListIssuesArgs = {
  repo?: string; /** Repository in owner/repo format */
  state?: "open" | "closed" | "all"; /** Filter by state (default: open) (default: "open") */
  labels?: string; /** Comma-separated label names to filter by */
  query?: string; /** Search query (GitHub search syntax) */
  maxResults?: number; /** Max results (default 10, max 100) (integer, 1–100, default: 10) */
};

export type ListIssuesResult = Record<string, unknown>;

/** Create a new issue in a GitHub repository. */
export type CreateIssueArgs = {
  repo: string; /** Repository in owner/repo format (min 1 chars) */
  title: string; /** Issue title (min 1 chars) */
  body?: string; /** Issue body (markdown) */
  labels?: Array<string>; /** Label names to apply */
  assignees?: Array<string>; /** Usernames to assign */
};

export type CreateIssueResult = Record<string, unknown>;

/** Get a file or directory listing from a GitHub repository. Returns decoded file content or a directory listing. */
export type GetFileArgs = {
  repo: string; /** Repository in owner/repo format (min 1 chars) */
  path: string; /** Path to file or directory within the repository (min 1 chars) */
  ref?: string; /** Branch, tag, or commit SHA (default: repo default branch) */
};

export type GetFileResult = Record<string, unknown>;

/** Search for code across GitHub repositories. Returns matching files with context snippets. Note: limited to 10 requests/minute. */
export type SearchCodeArgs = {
  query: string; /** Search query (code keywords, symbols, etc.) (min 1 chars) */
  repo?: string; /** Limit search to a repository in owner/repo format */
  language?: string; /** Filter by programming language (e.g. python, javascript) */
  maxResults?: number; /** Max results (default 10, max 100) (integer, 1–100, default: 10) */
};

export type SearchCodeResult = Record<string, unknown>;

/** List GitHub repositories for the authenticated user or a specific owner. If owner is omitted, lists your own repositories. */
export type ListReposArgs = {
  owner?: string; /** Username or organization. If omitted, lists your repos. */
  type?: "all" | "owner" | "public" | "private" | "member"; /** Filter by type (default: all) (default: "all") */
  sort?: "created" | "updated" | "pushed" | "full_name"; /** Sort field (default: updated) (default: "updated") */
  maxResults?: number; /** Max results (default 10, max 100) (integer, 1–100, default: 10) */
};

export type ListReposResult = Record<string, unknown>;

// ----------------------------------------------------------------------
// anthropic-admin
// ----------------------------------------------------------------------

/** Query Anthropic Admin API for organization usage and cost reports. Supports three actions: 'usage' (token-level usage), 'cost' (spend in USD, converted from cents), 'claude_code' (Claude Code productivity metrics). */
export type AnthropicUsageArgs = {
  action: "usage" | "cost" | "claude_code"; /** Which report: 'usage' (token usage), 'cost' (spend in USD), 'claude_code' (productivity metrics) */
  starting_at: string; /** Start time — RFC 3339 for usage/cost (e.g. '2025-02-01T00:00:00Z'), YYYY-MM-DD for claude_code (min 1 chars) */
  ending_at?: string; /** Optional end time (same format as starting_at) */
  bucket_width?: "1m" | "1h" | "1d"; /** Time granularity: '1m', '1h', or '1d' */
  group_by?: Array<string>; /** Group results by fields (e.g. ['model', 'workspace_id']) */
  limit?: number; /** Max number of time buckets / records to return (integer, ≥ 1) */
};

export type AnthropicUsageResult = {
  report_type: string;
  data: Record<string, unknown>;
};

// ----------------------------------------------------------------------
// interview-assist
// ----------------------------------------------------------------------

/** Validate Interview Assist MCP prerequisites and return detected paths. */
export type IaHealthcheckArgs = {
  repo_path?: string; /** Path to interview-assist-2 repo */
};

export type IaHealthcheckResult = Record<string, unknown>;

/** List recording JSONL files in interview-assist-2 recordings folder. */
export type IaListRecordingsArgs = {
  repo_path?: string;
  limit?: number; /**  (integer, ≥ 1, default: 30) */
};

export type IaListRecordingsResult = Record<string, unknown>;

/** Generate markdown report for a session JSONL using interview-assist-2 analyze mode. */
export type IaAnalyzeSessionArgs = {
  session_file: string; /**  (min 1 chars) */
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 900) */
};

export type IaAnalyzeSessionResult = Record<string, unknown>;

/** Run evaluation on a session JSONL and return key precision/recall/F1 metrics. */
export type IaEvaluateSessionArgs = {
  session_file: string; /**  (min 1 chars) */
  output_file?: string;
  model?: string;
  ground_truth_file?: string;
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 1800) */
};

export type IaEvaluateSessionResult = Record<string, unknown>;

/** Compare heuristic/LLM/parallel detection strategies for a session JSONL. */
export type IaCompareStrategiesArgs = {
  session_file: string; /**  (min 1 chars) */
  output_file?: string;
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 1800) */
};

export type IaCompareStrategiesResult = Record<string, unknown>;

/** Tune detection confidence threshold using optimize target f1/precision/recall/balanced. */
export type IaTuneThresholdArgs = {
  session_file: string; /**  (min 1 chars) */
  optimize?: "f1" | "precision" | "recall" | "balanced"; /**  (default: "f1") */
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 1800) */
};

export type IaTuneThresholdResult = Record<string, unknown>;

/** Run regression test for a session against a baseline file. */
export type IaRegressionTestArgs = {
  baseline_file: string; /**  (min 1 chars) */
  data_file: string; /**  (min 1 chars) */
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 1800) */
};

export type IaRegressionTestResult = Record<string, unknown>;

/** Create baseline JSON from a session JSONL file. */
export type IaCreateBaselineArgs = {
  data_file: string; /**  (min 1 chars) */
  output_file: string; /**  (min 1 chars) */
  version?: string; /**  (default: "1.0") */
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 1800) */
};

export type IaCreateBaselineResult = Record<string, unknown>;

/** Capture live microphone or loopback audio once and transcribe via Deepgram. */
export type IaTranscribeOnceArgs = {
  duration_seconds?: number; /**  (integer, ≥ 1, default: 8) */
  source?: "microphone" | "loopback"; /**  (default: "microphone") */
  mic_device_id?: string;
  mic_device_name?: string;
  sample_rate?: number; /**  (integer, ≥ 8000, default: 16000) */
  model?: string; /**  (default: "nova-2") */
  language?: string; /**  (default: "en") */
  endpointing_ms?: number; /**  (integer, ≥ 0, default: 300) */
  utterance_end_ms?: number; /**  (integer, ≥ 0, default: 1000) */
  diarize?: boolean; /**  (default: false) */
  output_file?: string;
  repo_path?: string;
  timeout_seconds?: number; /**  (integer, ≥ 1, default: 180) */
};

export type IaTranscribeOnceResult = Record<string, unknown>;

/** List available STT audio sources. */
export type SttListDevicesArgs = {
  repo_path?: string;
};

export type SttListDevicesResult = Record<string, unknown>;

/** Start a continuous STT session and return a session_id. */
export type SttStartSessionArgs = {
  source?: "microphone" | "loopback"; /**  (default: "microphone") */
  mic_device_id?: string;
  mic_device_name?: string;
  model?: string; /**  (default: "nova-2") */
  language?: string; /**  (default: "en") */
  sample_rate?: number; /**  (integer, ≥ 8000, default: 16000) */
  endpointing_ms?: number; /**  (integer, ≥ 0, default: 300) */
  utterance_end_ms?: number; /**  (integer, ≥ 0, default: 1000) */
  diarize?: boolean; /**  (default: false) */
  chunk_seconds?: number; /**  (integer, ≥ 1, default: 4) */
  repo_path?: string;
};

export type SttStartSessionResult = Record<string, unknown>;

/** Poll incremental STT events from a running session. */
export type SttGetUpdatesArgs = {
  session_id: string; /**  (min 1 chars) */
  since_seq?: number; /**  (integer, ≥ 0, default: 0) */
  limit?: number; /**  (integer, 1–500, default: 100) */
};

export type SttGetUpdatesResult = Record<string, unknown>;

/** Get current STT session status and counters. */
export type SttGetSessionArgs = {
  session_id: string; /**  (min 1 chars) */
};

export type SttGetSessionResult = Record<string, unknown>;

/** Stop an STT session. */
export type SttStopSessionArgs = {
  session_id: string; /**  (min 1 chars) */
};

export type SttStopSessionResult = Record<string, unknown>;
