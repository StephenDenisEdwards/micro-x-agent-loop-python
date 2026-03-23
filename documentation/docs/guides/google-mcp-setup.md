# Google MCP Server Setup Guide

The Google MCP server provides Gmail, Calendar, and Contacts tools via OAuth2 authentication with the Google APIs.

## Tools Provided

| Tool | Description |
|------|-------------|
| `gmail_search` | Search Gmail using Gmail search syntax |
| `gmail_read` | Read full content of an email by message ID |
| `gmail_send` | Send an email |
| `calendar_list_events` | List calendar events |
| `calendar_create_event` | Create a calendar event |
| `calendar_get_event` | Get details of a specific event |
| `contacts_search` | Search contacts by name or email |
| `contacts_list` | List contacts |
| `contacts_get` | Get a specific contact |
| `contacts_create` | Create a contact |
| `contacts_update` | Update a contact |
| `contacts_delete` | Delete a contact |

---

## Prerequisites

- **Node.js** (v18+)
- A **Google Cloud project** with OAuth2 credentials
- The MCP server built (`npm run build` in the monorepo)

---

## Step 1: Create Google Cloud OAuth2 Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Navigate to **APIs & Services > OAuth consent screen**
   - Choose **External** user type (or Internal if using Google Workspace)
   - Fill in the app name (e.g. "micro-x-agent") and your email
   - Add your email as a test user (required for External apps in testing mode)
   - Click **Save and Continue** through the remaining steps
4. Navigate to **APIs & Services > Credentials**
   - Click **Create Credentials > OAuth client ID**
   - Application type: **Web application**
   - Name: e.g. "micro-x-agent-loop"
   - Authorized redirect URIs: add `http://127.0.0.1` (the server dynamically appends the port)
   - Click **Create**
5. Copy the **Client ID** and **Client Secret**

## Step 2: Enable the Required APIs

In the Google Cloud Console, navigate to **APIs & Services > Library** and enable:

- **Gmail API** — for gmail_search, gmail_read, gmail_send
- **Google Calendar API** — for calendar_list_events, calendar_create_event, calendar_get_event
- **People API** — for contacts_search, contacts_list, contacts_get, contacts_create, contacts_update, contacts_delete

Only enable the APIs you plan to use. The server will fail at runtime if a tool is called but its API is not enabled.

## Step 3: Configure Environment Variables

Add the credentials to your `.env` file in the project root:

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

These are loaded by the agent via `${ENV}` expansion in the config and passed to the MCP server process.

## Step 4: Configure the MCP Server in Config

The Google MCP server is configured in the `McpServers` section of your config file. It is already present in `config-base.json`:

```json
{
  "McpServers": {
    "google": {
      "transport": "stdio",
      "command": "node",
      "args": ["mcp_servers/ts/packages/google/dist/index.js"],
      "env": {
        "GOOGLE_TOKEN_BASE_DIR": "C:\\Users\\steph\\source\\repos\\micro-x-agent-loop-python"
      }
    }
  }
}
```

### Configuration keys

| Key | Description |
|-----|-------------|
| `transport` | Always `"stdio"` for this server |
| `command` | `"node"` — runs the compiled JavaScript |
| `args` | Path to the compiled `dist/index.js` entry point |
| `env.GOOGLE_TOKEN_BASE_DIR` | Base directory for OAuth token storage. Defaults to `process.cwd()` if not set. Set this to the project root so tokens are reused regardless of working directory. |

The server reads `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from the process environment (inherited from the agent's `.env` file). If either is missing, the server exits immediately with a fatal error.

## Step 5: Build the Server

From the MCP server monorepo root:

```bash
cd mcp_servers/ts
npm install
npm run build
```

Or build just the Google package:

```bash
cd mcp_servers/ts/packages/google
npm run build
```

The compiled output goes to `packages/google/dist/`.

## Step 6: First-Run OAuth Authorization

On first use of any Google tool, the server initiates an interactive OAuth flow:

1. The agent calls a Google tool (e.g. `gmail_search`)
2. The MCP server starts a temporary local HTTP server on a random port
3. Your default browser opens to Google's OAuth consent page
4. You grant the requested permissions
5. Google redirects back to `http://127.0.0.1:<port>` with an authorization code
6. The server exchanges the code for access + refresh tokens
7. Tokens are saved to a local directory for future use

**You have 2 minutes to complete the authorization before it times out.**

### Separate consent per service

Each Google service uses its own token directory and scopes, so you will be prompted separately for:

| Service | Token Directory | Scopes |
|---------|----------------|--------|
| Gmail | `.gmail-tokens/` | `gmail.readonly`, `gmail.send` |
| Calendar | `.calendar-tokens/` | `calendar` (full read/write) |
| Contacts | `.contacts-tokens/` | `contacts` (full read/write) |

The first time you use a Gmail tool, you authorize Gmail scopes. The first time you use a Calendar tool, you authorize Calendar scopes, and so on.

### Token storage

Tokens are stored as JSON files:

```
<GOOGLE_TOKEN_BASE_DIR>/
  .gmail-tokens/token.json
  .calendar-tokens/token.json
  .contacts-tokens/token.json
```

These directories are in `.gitignore` and must never be committed. Each `token.json` contains:

```json
{
  "access_token": "ya29...",
  "refresh_token": "1//...",
  "token_type": "Bearer",
  "expiry_date": 1774200000000,
  "scope": "https://www.googleapis.com/auth/gmail.readonly ..."
}
```

### Token refresh

Access tokens expire after ~1 hour. The server automatically refreshes them using the stored refresh token — no re-authorization is needed unless:

- The refresh token is revoked (e.g. from Google Account settings)
- The token file is deleted
- The OAuth app's consent is withdrawn

---

## Troubleshooting

### "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set"

The environment variables are not reaching the MCP server process. Check:

1. `.env` file exists in the project root and contains both variables
2. The agent's config loading expands `${GOOGLE_CLIENT_ID}` correctly (check with `DEBUG` log level)
3. If running the server standalone for testing: `GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... node dist/index.js`

### Browser doesn't open for OAuth

The server uses the `open` npm package to launch the default browser. If it fails:

- The authorization URL is printed to stderr — copy and paste it manually
- Ensure no firewall is blocking `127.0.0.1` on ephemeral ports

### "OAuth authorization timed out after 2 minutes"

You didn't complete the consent flow in time. Retry by calling a Google tool again.

### "Token has been expired or revoked"

Delete the affected token file and re-authorize:

```bash
rm .gmail-tokens/token.json      # For Gmail
rm .calendar-tokens/token.json   # For Calendar
rm .contacts-tokens/token.json   # For Contacts
```

The next tool call will trigger the OAuth flow again.

### "Access Not Configured" or "API not enabled"

The required Google API is not enabled in your Cloud project. Go to **APIs & Services > Library** and enable it. See [Step 2](#step-2-enable-the-required-apis).

### "Access blocked: This app's request is invalid" (redirect_uri_mismatch)

The authorized redirect URI in your Google Cloud credentials doesn't include `http://127.0.0.1`. Go to **Credentials > your OAuth client > Authorized redirect URIs** and add `http://127.0.0.1`.

### Tool calls return empty results

- Check that the authenticated Google account actually has data (emails, events, contacts)
- For Gmail, verify the search query syntax — the `query` parameter uses [Gmail search operators](https://support.google.com/mail/answer/7190)
- Check the agent logs at `DEBUG` level for the raw MCP response

---

## Security Notes

- **Never commit** `.env`, token files, or client secrets to version control
- Token directories (`.gmail-tokens/`, `.calendar-tokens/`, `.contacts-tokens/`) are in `.gitignore`
- The OAuth consent screen in "Testing" mode limits access to explicitly added test users
- For production use, you would need to submit the app for Google's OAuth verification process
- The `gmail.send` scope allows sending email — be cautious with autonomous/broker workflows that could trigger email sending without human review

---

## Related Documentation

- [Adding an MCP Server](adding-an-mcp-server.md) — general guide for adding any MCP server
- [Tool: gmail_search](../design/tools/gmail-search/README.md)
- [Tool: gmail_read](../design/tools/gmail-read/README.md)
- [Tool: gmail_send](../design/tools/gmail-send/README.md)
- [Tool: calendar_list_events](../design/tools/calendar-list-events/README.md)
- [Tool: calendar_create_event](../design/tools/calendar-create-event/README.md)
- [Tool: calendar_get_event](../design/tools/calendar-get-event/README.md)
- [Configuration Reference](../operations/config.md) — `McpServers` config section
