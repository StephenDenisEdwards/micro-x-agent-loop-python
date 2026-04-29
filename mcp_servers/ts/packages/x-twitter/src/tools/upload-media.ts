import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";

const MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload";

const MIME_TYPES: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".gif": "image/gif",
  ".webp": "image/webp",
};

/**
 * Upload a media file to X using the v2 chunked upload API.
 *
 * Flow: INIT → APPEND → FINALIZE → (optional) METADATA for alt text.
 *
 * Returns the media_id string for use in tweet payloads.
 */
export async function uploadMedia(
  accessToken: string,
  filePath: string,
  altText: string | undefined,
  logger: Logger,
): Promise<string> {
  const ext = path.extname(filePath).toLowerCase();
  const mediaType = MIME_TYPES[ext];
  if (!mediaType) {
    throw new Error(`Unsupported media type: ${ext}. Supported: ${Object.keys(MIME_TYPES).join(", ")}`);
  }

  const fileData = await readFile(filePath);
  const fileStat = await stat(filePath);
  const totalBytes = fileStat.size;

  logger.info({ tool: "upload_media", file: filePath, size: totalBytes, type: mediaType }, "media_upload_start");

  // Step 1: INIT
  const initParams = new URLSearchParams({
    command: "INIT",
    total_bytes: totalBytes.toString(),
    media_type: mediaType,
    media_category: "tweet_image",
  });

  const initResponse = await resilientFetch(
    MEDIA_UPLOAD_URL,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${accessToken}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: initParams.toString(),
    },
    { timeoutMs: 15_000, retries: 2 },
  );

  if (!initResponse.ok) {
    const errorText = await initResponse.text();
    throw new UpstreamError(`Media INIT failed (${initResponse.status}): ${errorText}`, initResponse.status);
  }

  const initData = await initResponse.json() as { media_id_string: string };
  const mediaId = initData.media_id_string;

  // Step 2: APPEND (single chunk for images — typically < 5MB)
  const formData = new FormData();
  formData.append("command", "APPEND");
  formData.append("media_id", mediaId);
  formData.append("segment_index", "0");
  formData.append("media_data", Buffer.from(fileData).toString("base64"));

  const appendResponse = await resilientFetch(
    MEDIA_UPLOAD_URL,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${accessToken}`,
      },
      body: formData,
    },
    { timeoutMs: 30_000, retries: 2 },
  );

  if (!appendResponse.ok) {
    const errorText = await appendResponse.text();
    throw new UpstreamError(`Media APPEND failed (${appendResponse.status}): ${errorText}`, appendResponse.status);
  }

  // Step 3: FINALIZE
  const finalizeParams = new URLSearchParams({
    command: "FINALIZE",
    media_id: mediaId,
  });

  const finalizeResponse = await resilientFetch(
    MEDIA_UPLOAD_URL,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${accessToken}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: finalizeParams.toString(),
    },
    { timeoutMs: 15_000, retries: 2 },
  );

  if (!finalizeResponse.ok) {
    const errorText = await finalizeResponse.text();
    throw new UpstreamError(`Media FINALIZE failed (${finalizeResponse.status}): ${errorText}`, finalizeResponse.status);
  }

  // Step 4: METADATA (alt text) — optional
  if (altText) {
    const metadataParams = new URLSearchParams({
      command: "METADATA",
      media_id: mediaId,
      alt_text: altText,
    });

    const metadataResponse = await resilientFetch(
      MEDIA_UPLOAD_URL,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${accessToken}`,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: metadataParams.toString(),
      },
      { timeoutMs: 15_000, retries: 1 },
    );

    if (!metadataResponse.ok) {
      // Non-fatal: alt text failure shouldn't block the upload
      logger.warn({ tool: "upload_media", media_id: mediaId, status: metadataResponse.status }, "alt_text_failed");
    }
  }

  logger.info({ tool: "upload_media", media_id: mediaId }, "media_upload_complete");
  return mediaId;
}
