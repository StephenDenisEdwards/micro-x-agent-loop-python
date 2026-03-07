/**
 * Reddit OAuth2 password grant for "script" apps.
 *
 * Token endpoint: POST https://www.reddit.com/api/v1/access_token
 * Authorization: Basic base64(client_id:client_secret)
 * Content-Type: application/x-www-form-urlencoded
 * Body: grant_type=password&username=X&password=Y
 *
 * Token lifetime: 3600s (1 hour). No refresh tokens for script apps.
 * Cache token, auto-refresh before expiry (1-min buffer).
 *
 * All API requests go to https://oauth.reddit.com (NOT www.reddit.com)
 * All API requests need: Authorization: Bearer {token}, User-Agent: {custom}
 */

import { resilientFetch, UpstreamError } from "@micro-x/mcp-shared";

const TOKEN_URL = "https://www.reddit.com/api/v1/access_token";

interface CachedToken {
  accessToken: string;
  expiryDate: number; // absolute epoch ms
}

let cachedToken: CachedToken | null = null;

/**
 * Get a valid Reddit access token. Returns cached token if still valid.
 * Re-authenticates automatically when expired (1-minute buffer).
 */
export async function getRedditAuth(
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): Promise<{ accessToken: string; username: string }> {
  // Return cached token if still valid
  if (cachedToken && Date.now() < cachedToken.expiryDate - 60_000) {
    return { accessToken: cachedToken.accessToken, username };
  }

  const response = await resilientFetch(
    TOKEN_URL,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": `Basic ${btoa(`${clientId}:${clientSecret}`)}`,
        "User-Agent": userAgent,
      },
      body: new URLSearchParams({
        grant_type: "password",
        username,
        password,
      }).toString(),
    },
    { timeoutMs: 15_000, retries: 2 },
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new UpstreamError(
      `Reddit auth failed (${response.status}): ${errorText}`,
      response.status,
    );
  }

  const data = await response.json() as {
    access_token: string;
    token_type: string;
    expires_in: number;
    scope: string;
  };

  if (!data.access_token) {
    throw new Error("Reddit auth response missing access_token");
  }

  cachedToken = {
    accessToken: data.access_token,
    expiryDate: Date.now() + data.expires_in * 1000,
  };

  return { accessToken: cachedToken.accessToken, username };
}
