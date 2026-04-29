import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import http from "node:http";
import { URL } from "node:url";
import { resilientFetch } from "@micro-x-ai/mcp-shared";

/**
 * LinkedIn OAuth 2.0 authentication module.
 *
 * Follows the same pattern as the Google auth module:
 * - Browser-based OAuth flow via local HTTP server
 * - Token storage at `.linkedin-tokens/token.json`
 * - Cached authenticated client for reuse across tool calls
 *
 * LinkedIn tokens expire in 60 days and do not support refresh tokens
 * for most apps — when expired, the browser flow re-runs.
 */

interface LinkedInTokenData {
  access_token: string;
  expires_in: number;       // seconds until expiry (from token response)
  expiry_date: number;      // absolute epoch ms (computed at storage time)
  person_urn: string;       // urn:li:person:{sub}
}

export interface LinkedInClient {
  accessToken: string;
  personUrn: string;
}

const TOKEN_DIR = ".linkedin-tokens";
const TOKEN_FILE = "token.json";
const SCOPES = "openid profile email w_member_social";

let cachedClient: LinkedInClient | null = null;

/**
 * Get an authenticated LinkedIn client. Returns cached instance if valid.
 * Initiates browser-based OAuth flow if no valid tokens exist.
 */
export async function getLinkedInClient(
  clientId: string,
  clientSecret: string,
): Promise<LinkedInClient> {
  if (cachedClient) {
    return cachedClient;
  }

  const tokenDir = path.join(process.cwd(), TOKEN_DIR);
  const tokenPath = path.join(tokenDir, TOKEN_FILE);

  // Try to load existing tokens
  if (existsSync(tokenPath)) {
    const tokenContent = await readFile(tokenPath, "utf-8");
    const tokens: LinkedInTokenData = JSON.parse(tokenContent);

    // Check if token is still valid (1-minute buffer)
    const isExpired = Date.now() >= tokens.expiry_date - 60_000;

    if (!isExpired) {
      cachedClient = {
        accessToken: tokens.access_token,
        personUrn: tokens.person_urn,
      };
      return cachedClient;
    }

    // LinkedIn doesn't support refresh tokens for most apps — re-auth needed
    // eslint-disable-next-line no-console
    console.error("LinkedIn token expired — re-authorization required.");
  }

  // No valid tokens — run interactive OAuth flow
  const tokens = await runOAuthFlow(clientId, clientSecret);

  // Store tokens
  await mkdir(tokenDir, { recursive: true });
  await writeFile(tokenPath, JSON.stringify(tokens, null, 2), "utf-8");

  cachedClient = {
    accessToken: tokens.access_token,
    personUrn: tokens.person_urn,
  };
  return cachedClient;
}

/**
 * Run the full OAuth 2.0 authorization code flow:
 * 1. Start local HTTP server
 * 2. Open browser to LinkedIn authorization URL
 * 3. Receive callback with authorization code
 * 4. Exchange code for access token
 * 5. Fetch user info to get Person URN
 */
async function runOAuthFlow(
  clientId: string,
  clientSecret: string,
): Promise<LinkedInTokenData> {
  // Dynamic import for open (ESM-only package)
  const openModule = await import("open");
  const openBrowser = openModule.default;

  const code = await new Promise<{ code: string; redirectUri: string }>((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (!req.url) return;

      const url = new URL(req.url, "http://localhost");
      const authCode = url.searchParams.get("code");
      const error = url.searchParams.get("error");
      const errorDescription = url.searchParams.get("error_description");

      if (error) {
        res.writeHead(400, { "Content-Type": "text/html" });
        res.end(`<html><body><h1>Authorization failed</h1><p>${errorDescription ?? error}</p></body></html>`);
        server.close();
        reject(new Error(`LinkedIn OAuth failed: ${errorDescription ?? error}`));
        return;
      }

      if (authCode) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end("<html><body><h1>Authorization successful!</h1><p>You can close this window.</p></body></html>");
        const addr = server.address();
        const port = typeof addr === "object" && addr ? addr.port : 0;
        server.close();
        resolve({ code: authCode, redirectUri: `http://127.0.0.1:${port}` });
        return;
      }

      res.writeHead(404);
      res.end();
    });

    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (!addr || typeof addr === "string") {
        reject(new Error("Failed to start local auth server"));
        return;
      }

      const redirectUri = `http://127.0.0.1:${addr.port}`;
      const authUrl = new URL("https://www.linkedin.com/oauth/v2/authorization");
      authUrl.searchParams.set("response_type", "code");
      authUrl.searchParams.set("client_id", clientId);
      authUrl.searchParams.set("redirect_uri", redirectUri);
      authUrl.searchParams.set("scope", SCOPES);
      authUrl.searchParams.set("state", crypto.randomUUID());

      // eslint-disable-next-line no-console
      console.error("Opening browser for LinkedIn authorization...");
      console.error(`If the browser doesn't open, visit: ${authUrl.toString()}`);

      openBrowser(authUrl.toString()).catch(() => {
        console.error("Could not open browser automatically. Please visit the URL above.");
      });
    });

    // Timeout after 2 minutes
    setTimeout(() => {
      server.close();
      reject(new Error("LinkedIn OAuth authorization timed out after 2 minutes"));
    }, 120_000);
  });

  // Exchange authorization code for access token
  const tokenResponse = await resilientFetch(
    "https://www.linkedin.com/oauth/v2/accessToken",
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        code: code.code,
        redirect_uri: code.redirectUri,
        client_id: clientId,
        client_secret: clientSecret,
      }).toString(),
    },
    { timeoutMs: 15_000, retries: 1 },
  );

  if (!tokenResponse.ok) {
    const errorText = await tokenResponse.text();
    throw new Error(`LinkedIn token exchange failed (${tokenResponse.status}): ${errorText}`);
  }

  const tokenData = (await tokenResponse.json()) as {
    access_token: string;
    expires_in: number;
  };

  // Fetch user info to get Person URN (sub field)
  const userInfoResponse = await resilientFetch(
    "https://api.linkedin.com/v2/userinfo",
    {
      headers: {
        Authorization: `Bearer ${tokenData.access_token}`,
      },
    },
    { timeoutMs: 15_000, retries: 2 },
  );

  if (!userInfoResponse.ok) {
    const errorText = await userInfoResponse.text();
    throw new Error(`LinkedIn userinfo failed (${userInfoResponse.status}): ${errorText}`);
  }

  const userInfo = (await userInfoResponse.json()) as { sub: string };

  return {
    access_token: tokenData.access_token,
    expires_in: tokenData.expires_in,
    expiry_date: Date.now() + tokenData.expires_in * 1000,
    person_urn: `urn:li:person:${userInfo.sub}`,
  };
}
