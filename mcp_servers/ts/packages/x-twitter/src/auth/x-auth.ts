import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import http from "node:http";
import { URL } from "node:url";
import { resilientFetch } from "@micro-x/mcp-shared";

/**
 * X (Twitter) OAuth 2.0 Authorization Code with PKCE.
 *
 * Key differences from LinkedIn OAuth:
 * - PKCE required (code_verifier + SHA256 code_challenge)
 * - Confidential client: client_id:client_secret as Basic auth
 * - Access tokens expire in 2 hours (not 60 days)
 * - Refresh tokens available with offline.access scope (rotating)
 * - Token endpoint: https://api.x.com/2/oauth2/token
 */

interface XTokenData {
  access_token: string;
  refresh_token: string;
  expires_in: number;        // seconds (from token response, typically 7200)
  expiry_date: number;       // absolute epoch ms
  user_id: string;           // authenticated user's ID
  username: string;          // authenticated user's @handle
}

export interface XClient {
  accessToken: string;
  userId: string;
  username: string;
}

const TOKEN_DIR = ".x-tokens";
const TOKEN_FILE = "token.json";
const SCOPES = "tweet.read tweet.write users.read offline.access";
const AUTH_URL = "https://x.com/i/oauth2/authorize";
const TOKEN_URL = "https://api.x.com/2/oauth2/token";

let cachedClient: XClient | null = null;

/**
 * Get an authenticated X client. Returns cached instance if valid.
 * Initiates browser-based OAuth flow if no valid tokens exist.
 */
export async function getXClient(
  clientId: string,
  clientSecret: string,
): Promise<XClient> {
  if (cachedClient) {
    return cachedClient;
  }

  const tokenDir = resolveTokenDir();
  const tokenPath = path.join(tokenDir, TOKEN_FILE);

  // Try to load existing tokens
  if (existsSync(tokenPath)) {
    const tokenContent = await readFile(tokenPath, "utf-8");
    const tokens: XTokenData = JSON.parse(tokenContent);

    // Check if token is still valid (1-minute buffer)
    const isExpired = Date.now() >= tokens.expiry_date - 60_000;

    if (!isExpired) {
      cachedClient = {
        accessToken: tokens.access_token,
        userId: tokens.user_id,
        username: tokens.username,
      };
      return cachedClient;
    }

    // Token expired — try refresh
    if (tokens.refresh_token) {
      try {
        const refreshed = await refreshAccessToken(clientId, clientSecret, tokens.refresh_token, tokens.user_id, tokens.username);
        await mkdir(tokenDir, { recursive: true });
        await writeFile(tokenPath, JSON.stringify(refreshed, null, 2), "utf-8");
        cachedClient = {
          accessToken: refreshed.access_token,
          userId: refreshed.user_id,
          username: refreshed.username,
        };
        return cachedClient;
      } catch {
        // Refresh failed — fall through to full re-auth
        console.error("X token refresh failed — re-authorization required.");
      }
    } else {
      console.error("X token expired and no refresh token — re-authorization required.");
    }
  }

  // No valid tokens — run interactive OAuth flow
  const tokens = await runOAuthFlow(clientId, clientSecret);

  // Store tokens
  await mkdir(tokenDir, { recursive: true });
  await writeFile(tokenPath, JSON.stringify(tokens, null, 2), "utf-8");

  cachedClient = {
    accessToken: tokens.access_token,
    userId: tokens.user_id,
    username: tokens.username,
  };
  return cachedClient;
}

function resolveTokenDir(): string {
  const envPath = process.env.X_TOKEN_PATH;
  if (envPath) {
    return path.dirname(path.resolve(envPath));
  }
  return path.join(process.cwd(), TOKEN_DIR);
}

/**
 * Refresh an expired access token using a refresh token.
 * X uses rotating refresh tokens — the response includes a new refresh token.
 */
async function refreshAccessToken(
  clientId: string,
  clientSecret: string,
  refreshToken: string,
  userId: string,
  username: string,
): Promise<XTokenData> {
  const response = await resilientFetch(
    TOKEN_URL,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": `Basic ${btoa(`${clientId}:${clientSecret}`)}`,
      },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
      }).toString(),
    },
    { timeoutMs: 15_000, retries: 1 },
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`X token refresh failed (${response.status}): ${errorText}`);
  }

  const data = await response.json() as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };

  return {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_in: data.expires_in,
    expiry_date: Date.now() + data.expires_in * 1000,
    user_id: userId,
    username,
  };
}

/**
 * Generate PKCE code verifier and challenge.
 */
function generatePKCE(): { codeVerifier: string; codeChallenge: string } {
  // Generate 32 random bytes → base64url encode → 43-char verifier
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const codeVerifier = base64UrlEncode(bytes);

  // SHA256 hash of verifier → base64url encode
  // Use synchronous approach via SubtleCrypto workaround
  // We'll compute it async in the caller instead
  return { codeVerifier, codeChallenge: "" }; // placeholder
}

function base64UrlEncode(buffer: Uint8Array): string {
  const base64 = Buffer.from(buffer).toString("base64");
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function computeCodeChallenge(codeVerifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(codeVerifier);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(hash));
}

/**
 * Run the full OAuth 2.0 Authorization Code with PKCE flow.
 */
async function runOAuthFlow(
  clientId: string,
  clientSecret: string,
): Promise<XTokenData> {
  const openModule = await import("open");
  const openBrowser = openModule.default;

  // Generate PKCE values
  const { codeVerifier } = generatePKCE();
  const codeChallenge = await computeCodeChallenge(codeVerifier);
  const state = crypto.randomUUID();

  const authResult = await new Promise<{ code: string; redirectUri: string }>((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (!req.url) return;

      const url = new URL(req.url, "http://localhost");
      const authCode = url.searchParams.get("code");
      const error = url.searchParams.get("error");
      const errorDescription = url.searchParams.get("error_description");
      const returnedState = url.searchParams.get("state");

      if (error) {
        res.writeHead(400, { "Content-Type": "text/html" });
        res.end(`<html><body><h1>Authorization failed</h1><p>${errorDescription ?? error}</p></body></html>`);
        server.close();
        reject(new Error(`X OAuth failed: ${errorDescription ?? error}`));
        return;
      }

      if (authCode) {
        // Verify state parameter
        if (returnedState !== state) {
          res.writeHead(400, { "Content-Type": "text/html" });
          res.end("<html><body><h1>Authorization failed</h1><p>State mismatch — possible CSRF attack.</p></body></html>");
          server.close();
          reject(new Error("X OAuth state mismatch"));
          return;
        }

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
      const authUrl = new URL(AUTH_URL);
      authUrl.searchParams.set("response_type", "code");
      authUrl.searchParams.set("client_id", clientId);
      authUrl.searchParams.set("redirect_uri", redirectUri);
      authUrl.searchParams.set("scope", SCOPES);
      authUrl.searchParams.set("state", state);
      authUrl.searchParams.set("code_challenge", codeChallenge);
      authUrl.searchParams.set("code_challenge_method", "S256");

      console.error("Opening browser for X (Twitter) authorization...");
      console.error(`If the browser doesn't open, visit: ${authUrl.toString()}`);

      openBrowser(authUrl.toString()).catch(() => {
        console.error("Could not open browser automatically. Please visit the URL above.");
      });
    });

    // Timeout after 2 minutes
    setTimeout(() => {
      server.close();
      reject(new Error("X OAuth authorization timed out after 2 minutes"));
    }, 120_000);
  });

  // Exchange authorization code for tokens
  const tokenResponse = await resilientFetch(
    TOKEN_URL,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": `Basic ${btoa(`${clientId}:${clientSecret}`)}`,
      },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        code: authResult.code,
        redirect_uri: authResult.redirectUri,
        code_verifier: codeVerifier,
      }).toString(),
    },
    { timeoutMs: 15_000, retries: 1 },
  );

  if (!tokenResponse.ok) {
    const errorText = await tokenResponse.text();
    throw new Error(`X token exchange failed (${tokenResponse.status}): ${errorText}`);
  }

  const tokenData = await tokenResponse.json() as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };

  // Fetch authenticated user info
  const userResponse = await resilientFetch(
    "https://api.x.com/2/users/me",
    {
      headers: {
        "Authorization": `Bearer ${tokenData.access_token}`,
      },
    },
    { timeoutMs: 15_000, retries: 2 },
  );

  if (!userResponse.ok) {
    const errorText = await userResponse.text();
    throw new Error(`X user info failed (${userResponse.status}): ${errorText}`);
  }

  const userInfo = await userResponse.json() as {
    data: { id: string; username: string };
  };

  return {
    access_token: tokenData.access_token,
    refresh_token: tokenData.refresh_token,
    expires_in: tokenData.expires_in,
    expiry_date: Date.now() + tokenData.expires_in * 1000,
    user_id: userInfo.data.id,
    username: userInfo.data.username,
  };
}
