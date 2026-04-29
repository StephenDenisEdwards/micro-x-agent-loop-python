#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x/mcp-shared";
import { registerGmailSearch } from "./tools/gmail-search.js";
import { registerGmailRead } from "./tools/gmail-read.js";
import { registerGmailSend } from "./tools/gmail-send.js";
import { registerCalendarList } from "./tools/calendar-list.js";
import { registerCalendarCreate } from "./tools/calendar-create.js";
import { registerCalendarGet } from "./tools/calendar-get.js";
import { registerContactsSearch } from "./tools/contacts-search.js";
import { registerContactsList } from "./tools/contacts-list.js";
import { registerContactsGet } from "./tools/contacts-get.js";
import { registerContactsCreate } from "./tools/contacts-create.js";
import { registerContactsUpdate } from "./tools/contacts-update.js";
import { registerContactsDelete } from "./tools/contacts-delete.js";

// --help / -h flag
if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`@micro-x/mcp-google — Gmail, Calendar, and Contacts MCP server

Usage:
  npx -y @micro-x/mcp-google          Start the server (stdio transport)
  npx -y @micro-x/mcp-google --help   Show this message

Required environment variables:
  GOOGLE_CLIENT_ID        OAuth2 client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET    OAuth2 client secret from Google Cloud Console

Optional environment variables:
  GOOGLE_TOKEN_BASE_DIR   Directory for cached OAuth tokens
                          Default (POSIX):   \${XDG_DATA_HOME:-~/.local/share}/mcp-google
                          Default (Windows): %APPDATA%/mcp-google

Tools:
  gmail_search         Search Gmail messages
  gmail_read           Read a Gmail message by ID
  gmail_send           Send an email via Gmail
  calendar_list        List upcoming calendar events
  calendar_create      Create a calendar event
  calendar_get         Get a calendar event by ID
  contacts_search      Search contacts by name or email
  contacts_list        List contacts
  contacts_get         Get a contact by resource name
  contacts_create      Create a new contact
  contacts_update      Update an existing contact
  contacts_delete      Delete a contact

On first run, the server opens a browser for OAuth consent. Tokens are
cached locally and refreshed automatically. Tokens are never sent anywhere
except Google's APIs.
`);
  process.exit(0);
}

const logger = createLogger("mcp-google");

// Configuration from environment
const clientId = process.env.GOOGLE_CLIENT_ID ?? "";
const clientSecret = process.env.GOOGLE_CLIENT_SECRET ?? "";

if (!clientId || !clientSecret) {
  logger.fatal("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set");
  process.exit(1);
}

const server = createServer({
  name: "google",
  version: "0.1.0",
  logger,
});

// Register Gmail tools
registerGmailSearch(server, logger, clientId, clientSecret);
registerGmailRead(server, logger, clientId, clientSecret);
registerGmailSend(server, logger, clientId, clientSecret);

// Register Calendar tools
registerCalendarList(server, logger, clientId, clientSecret);
registerCalendarCreate(server, logger, clientId, clientSecret);
registerCalendarGet(server, logger, clientId, clientSecret);

// Register Contacts tools
registerContactsSearch(server, logger, clientId, clientSecret);
registerContactsList(server, logger, clientId, clientSecret);
registerContactsGet(server, logger, clientId, clientSecret);
registerContactsCreate(server, logger, clientId, clientSecret);
registerContactsUpdate(server, logger, clientId, clientSecret);
registerContactsDelete(server, logger, clientId, clientSecret);

// Start
startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start Google server");
  process.exit(1);
});
