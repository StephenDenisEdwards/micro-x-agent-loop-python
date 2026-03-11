import { OAuth2Client } from "google-auth-library";
import { google } from "googleapis";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import http from "node:http";
import { URL } from "node:url";

/**
 * Cached service instances keyed by token directory path.
 * Each service domain (Gmail, Calendar, People) uses its own
 * token directory and scopes, so we cache per-directory.
 */
const serviceCache = new Map<string, ReturnType<typeof google.gmail> | ReturnType<typeof google.calendar> | ReturnType<typeof google.people>>();

/**
 * Base directory for OAuth token storage.
 * Defaults to process.cwd() but can be overridden via GOOGLE_TOKEN_BASE_DIR
 * so that task apps spawned in subdirectories reuse the main project's tokens.
 */
const TOKEN_BASE_DIR = process.env.GOOGLE_TOKEN_BASE_DIR || process.cwd();

interface TokenData {
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expiry_date?: number;
  scope?: string;
}

/**
 * Run a local HTTP server to handle the OAuth2 redirect.
 * Opens the authorization URL and waits for the callback with the auth code.
 */
async function getAuthCodeViaLocalServer(authorizeUrl: string): Promise<{ code: string; redirectUri: string }> {
  // Dynamic import for open (ESM-only package)
  const openModule = await import("open");
  const openBrowser = openModule.default;

  return new Promise<{ code: string; redirectUri: string }>((resolve, reject) => {
    let actualRedirectUri = "";
    const server = http.createServer((req, res) => {
      if (!req.url) {
        return;
      }

      const url = new URL(req.url, "http://localhost");
      const code = url.searchParams.get("code");
      const error = url.searchParams.get("error");

      if (error) {
        res.writeHead(400, { "Content-Type": "text/html" });
        res.end(`<html><body><h1>Authorization failed</h1><p>${error}</p></body></html>`);
        server.close();
        reject(new Error(`OAuth authorization failed: ${error}`));
        return;
      }

      if (code) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end("<html><body><h1>Authorization successful!</h1><p>You can close this window.</p></body></html>");
        server.close();
        resolve({ code, redirectUri: actualRedirectUri });
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

      actualRedirectUri = `http://127.0.0.1:${addr.port}`;

      // Replace the redirect_uri in the authorize URL
      const authUrl = new URL(authorizeUrl);
      authUrl.searchParams.set("redirect_uri", actualRedirectUri);

      // eslint-disable-next-line no-console
      console.error(`Opening browser for Google authorization...`);
      console.error(`If the browser doesn't open, visit: ${authUrl.toString()}`);

      openBrowser(authUrl.toString()).catch(() => {
        console.error(`Could not open browser automatically. Please visit the URL above.`);
      });
    });

    // Timeout after 2 minutes
    setTimeout(() => {
      server.close();
      reject(new Error("OAuth authorization timed out after 2 minutes"));
    }, 120_000);
  });
}

/**
 * Get an authenticated OAuth2Client for the given scopes and token directory.
 *
 * - Reads stored tokens from `{tokenDir}/token.json`
 * - Refreshes expired tokens automatically
 * - Initiates browser-based OAuth flow if no valid tokens exist
 * - Stores new tokens for future use
 */
async function getAuthenticatedClient(
  clientId: string,
  clientSecret: string,
  scopes: string[],
  tokenDir: string,
): Promise<OAuth2Client> {
  const tokenPath = path.join(tokenDir, "token.json");

  // Use a temporary redirect_uri — will be replaced during auth flow
  const oauth2Client = new OAuth2Client(clientId, clientSecret, "http://127.0.0.1");

  // Try to load existing tokens
  if (existsSync(tokenPath)) {
    const tokenContent = await readFile(tokenPath, "utf-8");
    const tokens: TokenData = JSON.parse(tokenContent);

    oauth2Client.setCredentials({
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      token_type: tokens.token_type,
      expiry_date: tokens.expiry_date,
    });

    // Check if token needs refresh
    const expiryDate = tokens.expiry_date ?? 0;
    const isExpired = expiryDate > 0 && Date.now() >= expiryDate - 60_000; // 1min buffer

    if (isExpired && tokens.refresh_token) {
      const { credentials } = await oauth2Client.refreshAccessToken();
      oauth2Client.setCredentials(credentials);

      // Save refreshed tokens (preserve refresh_token if not returned)
      const updatedTokens: TokenData = {
        access_token: credentials.access_token ?? undefined,
        refresh_token: credentials.refresh_token ?? tokens.refresh_token ?? undefined,
        token_type: credentials.token_type ?? undefined,
        expiry_date: credentials.expiry_date ?? undefined,
        scope: credentials.scope ?? undefined,
      };
      await writeFile(tokenPath, JSON.stringify(updatedTokens, null, 2), "utf-8");
    }

    return oauth2Client;
  }

  // No existing tokens — run interactive OAuth flow
  const authorizeUrl = oauth2Client.generateAuthUrl({
    access_type: "offline",
    scope: scopes,
    prompt: "consent",
  });

  const { code, redirectUri } = await getAuthCodeViaLocalServer(authorizeUrl);

  // Exchange the authorization code using a client with the exact redirect_uri
  // that was sent to Google during authorization (must match for token exchange)
  const exchangeClient = new OAuth2Client(clientId, clientSecret, redirectUri);
  const { tokens } = await exchangeClient.getToken(code);
  oauth2Client.setCredentials(tokens);

  // Store tokens
  await mkdir(tokenDir, { recursive: true });
  const tokenData: TokenData = {
    access_token: tokens.access_token ?? undefined,
    refresh_token: tokens.refresh_token ?? undefined,
    token_type: tokens.token_type ?? undefined,
    expiry_date: tokens.expiry_date ?? undefined,
    scope: tokens.scope ?? undefined,
  };
  await writeFile(tokenPath, JSON.stringify(tokenData, null, 2), "utf-8");

  return oauth2Client;
}

// ── Gmail ──

const GMAIL_SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.send",
];

export async function getGmailService(clientId: string, clientSecret: string) {
  const tokenDir = path.join(TOKEN_BASE_DIR, ".gmail-tokens");
  const cacheKey = tokenDir;

  const cached = serviceCache.get(cacheKey);
  if (cached) {
    return cached as ReturnType<typeof google.gmail>;
  }

  const auth = await getAuthenticatedClient(clientId, clientSecret, GMAIL_SCOPES, tokenDir);
  const service = google.gmail({ version: "v1", auth });
  serviceCache.set(cacheKey, service);
  return service;
}

// ── Calendar ──

const CALENDAR_SCOPES = [
  "https://www.googleapis.com/auth/calendar",
];

export async function getCalendarService(clientId: string, clientSecret: string) {
  const tokenDir = path.join(TOKEN_BASE_DIR, ".calendar-tokens");
  const cacheKey = tokenDir;

  const cached = serviceCache.get(cacheKey);
  if (cached) {
    return cached as ReturnType<typeof google.calendar>;
  }

  const auth = await getAuthenticatedClient(clientId, clientSecret, CALENDAR_SCOPES, tokenDir);
  const service = google.calendar({ version: "v3", auth });
  serviceCache.set(cacheKey, service);
  return service;
}

// ── Contacts (People API) ──

const CONTACTS_SCOPES = [
  "https://www.googleapis.com/auth/contacts",
];

export async function getContactsService(clientId: string, clientSecret: string) {
  const tokenDir = path.join(TOKEN_BASE_DIR, ".contacts-tokens");
  const cacheKey = tokenDir;

  const cached = serviceCache.get(cacheKey);
  if (cached) {
    return cached as ReturnType<typeof google.people>;
  }

  const auth = await getAuthenticatedClient(clientId, clientSecret, CONTACTS_SCOPES, tokenDir);
  const service = google.people({ version: "v1", auth });
  serviceCache.set(cacheKey, service);
  return service;
}
