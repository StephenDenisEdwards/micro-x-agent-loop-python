/**
 * In-memory draft store for the draft-then-publish pattern.
 *
 * Drafts expire after 10 minutes. This gives the agent time to
 * preview and confirm before publishing, without accumulating stale drafts.
 */

export interface TweetDraft {
  text: string;
  reply_to_id?: string;
  quote_tweet_id?: string;
  media_paths?: string[];
}

export interface ThreadDraft {
  tweets: Array<{ text: string; media_paths?: string[] }>;
}

export interface Draft {
  id: string;
  type: "tweet" | "thread";
  payload: TweetDraft | ThreadDraft;
  preview: string;
  createdAt: number;
}

const drafts = new Map<string, Draft>();
const DRAFT_TTL_MS = 10 * 60 * 1000; // 10 minutes

export function createDraft(
  type: Draft["type"],
  payload: TweetDraft | ThreadDraft,
  preview: string,
): string {
  const id = crypto.randomUUID();
  drafts.set(id, { id, type, payload, preview, createdAt: Date.now() });
  return id;
}

export function getDraft(draftId: string): Draft | null {
  const draft = drafts.get(draftId);
  if (!draft) return null;

  if (Date.now() - draft.createdAt > DRAFT_TTL_MS) {
    drafts.delete(draftId);
    return null;
  }

  return draft;
}

export function removeDraft(draftId: string): void {
  drafts.delete(draftId);
}
