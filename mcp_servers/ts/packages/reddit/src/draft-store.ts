/**
 * In-memory draft store for the draft-then-publish pattern.
 *
 * Drafts expire after 10 minutes. This gives the agent time to
 * preview and confirm before publishing, without accumulating stale drafts.
 */

export interface PostDraft {
  subreddit: string;
  title: string;
  kind: "self" | "link";
  text?: string;
  url?: string;
  flair_id?: string;
  flair_text?: string;
  nsfw: boolean;
  sendreplies: boolean;
}

export interface Draft {
  id: string;
  type: "post";
  payload: PostDraft;
  preview: string;
  createdAt: number;
}

const drafts = new Map<string, Draft>();
const DRAFT_TTL_MS = 10 * 60 * 1000; // 10 minutes

export function createDraft(
  type: Draft["type"],
  payload: PostDraft,
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
