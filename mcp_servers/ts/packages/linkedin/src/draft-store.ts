/**
 * In-memory draft store for the draft-then-publish pattern.
 *
 * Drafts expire after 10 minutes. This gives the agent time to
 * preview and confirm before publishing, without accumulating stale drafts.
 */

export interface DraftPost {
  id: string;
  type: "text" | "article" | "image" | "document";
  payload: Record<string, unknown>;  // Validated, ready-to-send LinkedIn API payload
  preview: string;                   // Human-readable preview text
  createdAt: number;                 // Date.now()
}

const drafts = new Map<string, DraftPost>();
const DRAFT_TTL_MS = 10 * 60 * 1000; // 10 minutes

export function createDraft(
  type: DraftPost["type"],
  payload: Record<string, unknown>,
  preview: string,
): string {
  const id = crypto.randomUUID();
  drafts.set(id, { id, type, payload, preview, createdAt: Date.now() });
  return id;
}

export function getDraft(draftId: string): DraftPost | null {
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
