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
