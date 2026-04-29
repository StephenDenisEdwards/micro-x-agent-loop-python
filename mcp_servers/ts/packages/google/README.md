# @micro-x-ai/mcp-google

Google MCP server providing Gmail, Calendar, and Contacts tools over OAuth2. Works with any MCP-compatible client including Claude Desktop, Claude Code, and the micro-x agent loop.

## Install and run

```bash
npx -y @micro-x-ai/mcp-google
```

On first run, a browser window opens for Google OAuth consent. Tokens are cached locally and refreshed automatically on subsequent runs.

## Required environment variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | OAuth2 client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth2 client secret from Google Cloud Console |

## Optional environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_TOKEN_BASE_DIR` | Directory for cached OAuth tokens | POSIX: `${XDG_DATA_HOME:-~/.local/share}/mcp-google` · Windows: `%APPDATA%/mcp-google` |

## OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Enable the **Gmail API**, **Google Calendar API**, and **People API**.
4. Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**.
5. Application type: **Web application**.
6. Add `http://127.0.0.1` as an authorised redirect URI (the server picks a random port at runtime and appends it).
7. Copy the client ID and client secret into your environment.

## Tools

### Gmail

| Tool | Description |
|------|-------------|
| `gmail_search` | Search Gmail messages by query |
| `gmail_read` | Read a Gmail message by ID |
| `gmail_send` | Send an email via Gmail |

### Calendar

| Tool | Description |
|------|-------------|
| `calendar_list` | List upcoming calendar events |
| `calendar_create` | Create a calendar event |
| `calendar_get` | Get a calendar event by ID |

### Contacts

| Tool | Description |
|------|-------------|
| `contacts_search` | Search contacts by name or email |
| `contacts_list` | List contacts |
| `contacts_get` | Get a contact by resource name |
| `contacts_create` | Create a new contact |
| `contacts_update` | Update an existing contact |
| `contacts_delete` | Delete a contact |

## Client configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "google": {
      "command": "npx",
      "args": ["-y", "@micro-x-ai/mcp-google"],
      "env": {
        "GOOGLE_CLIENT_ID": "your-client-id",
        "GOOGLE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

### Claude Code

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "google": {
      "command": "npx",
      "args": ["-y", "@micro-x-ai/mcp-google"],
      "env": {
        "GOOGLE_CLIENT_ID": "your-client-id",
        "GOOGLE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

### micro-x agent loop

Add to `config.json` under `McpServers`:

```json
{
  "McpServers": {
    "google": {
      "Command": "npx",
      "Args": ["-y", "@micro-x-ai/mcp-google"],
      "Env": {
        "GOOGLE_CLIENT_ID": "your-client-id",
        "GOOGLE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

## Security

- OAuth tokens are cached locally in `GOOGLE_TOKEN_BASE_DIR` and are never sent anywhere except Google's APIs.
- Tokens include a refresh token — revoke access at any time via [Google Account Permissions](https://myaccount.google.com/permissions).
- The OAuth scopes requested are: `gmail.readonly`, `gmail.send`, `calendar`, `contacts`.

## Flags

| Flag | Description |
|------|-------------|
| `--help`, `-h` | Print usage information and exit |

## License

MIT
