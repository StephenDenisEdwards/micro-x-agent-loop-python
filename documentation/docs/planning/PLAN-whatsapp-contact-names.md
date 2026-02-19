# Plan: Fix WhatsApp Contact Names

**Status: Completed** (2026-02-19)

## Problem

WhatsApp tools return phone numbers instead of contact names for individual chats. Group names work correctly.

**Example:** The agent shows `447930348027` where the phone and desktop app show "John Smith".

All 59 chats in `messages.db` have a `name` column, but for individual contacts the value is the raw phone number or JID — never the person's actual name.

## Root Cause

The Go bridge (`whatsapp-mcp/whatsapp-bridge/main.go`) stores phone numbers as names because its `GetChatName()` function only checks `contact.FullName` (rarely populated via app state sync) and falls back to the raw JID. It ignores `PushName` and `BusinessName`, and doesn't handle `events.PushName` or `events.Contact`.

## Key Discovery: whatsapp.db

While investigating, we found that **whatsmeow already stores contact names** in a separate SQLite database (`whatsapp-bridge/store/whatsapp.db`), in the `whatsmeow_contacts` table:

```
whatsmeow_contacts:
  our_jid      TEXT    -- our account JID
  their_jid    TEXT    -- the contact's JID (matches chats.jid in messages.db)
  first_name   TEXT    -- from phone address book
  full_name    TEXT    -- from phone address book (99/138 contacts populated)
  push_name    TEXT    -- self-chosen WhatsApp display name (60/138 populated)
  business_name TEXT   -- verified business name
```

Sample data confirms names are present:

| messages.db chats.name | whatsmeow_contacts full_name | push_name |
|------------------------|------------------------------|-----------|
| `447740948859` | John Taliadoros | John |
| `447939245392` | Kinga | Kinga |
| `447966909882` | Lawrie (Lawrence) | Lawrence Cook |
| `447831592032` | Doug Packer | Doug Packer |

The Go bridge writes to `messages.db`. Whatsmeow itself maintains `whatsapp.db` as part of its internal state. The Python MCP server currently only reads `messages.db`.

## How Other Projects Handle This

### OpenClaw (Baileys / Node.js)

OpenClaw uses the Baileys library (TypeScript equivalent of whatsmeow) and extracts `pushName` directly from each incoming message object:

```typescript
// src/web/inbound/monitor.ts:208
pushName: msg.pushName ?? undefined

// src/web/inbound/monitor.ts:296
const senderName = msg.pushName ?? undefined
```

This works because Baileys runs in-process — the push name is available on every message. Our architecture is different (separate Go bridge + SQLite), but we can achieve the same result by reading from whatsmeow's own contact cache.

## Approach: Read from whatsapp.db (Python MCP server fix)

Instead of modifying the Go bridge (upstream code we don't control), fix name resolution in the **Python MCP server** by reading contact names from `whatsapp.db`'s `whatsmeow_contacts` table.

### Changes to `whatsapp-mcp/whatsapp-mcp-server/whatsapp.py`

1. Add `CONTACTS_DB_PATH` constant pointing to `../whatsapp-bridge/store/whatsapp.db`

2. Add a `_resolve_contact_name(jid)` function that queries `whatsmeow_contacts` with the priority: `full_name` > `push_name` > `business_name`

3. Update `get_sender_name()` to fall back to `_resolve_contact_name()` when the `chats` table only has a phone number

4. Apply name resolution when constructing `Chat` and `Contact` objects wherever `chats.name` is currently used

### Name Priority

1. **`full_name`** from whatsmeow_contacts — your phone's address book name (best, 99/138 populated)
2. **`push_name`** from whatsmeow_contacts — the name they chose for themselves (60/138 populated)
3. **`business_name`** from whatsmeow_contacts — verified business name
4. **`chats.name`** from messages.db — falls back to phone number (current behaviour)

### Files Affected

| File | Change |
|------|--------|
| `whatsapp-mcp/whatsapp-mcp-server/whatsapp.py` | Add contacts DB path, name resolution function, apply to all name lookups |
| No Go bridge changes | whatsmeow already maintains the contact data we need |
| No agent code changes | The fix is entirely in the Python MCP server |

### Advantages over Go bridge fix

- **No upstream fork needed** — we don't modify code we don't control
- **Already populated** — whatsmeow has 99/138 full names and 60/138 push names stored
- **Simple** — one new function, applied at the Python layer
- **`full_name` available** — the Go bridge only tried `FullName` at runtime via API call; the SQLite store has it already persisted from app state sync

## Limitations

- **Names depend on app state sync completing.** If whatsmeow hasn't synced contacts yet, `whatsmeow_contacts` will be empty. This typically completes on first connection.
- **Push names are not your address book names.** If you saved someone as "Mom" but their push name is "Jane Edwards", and `full_name` is empty, you'll see "Jane Edwards".
- **LID JIDs may not resolve.** Some contacts appear with `@lid` JIDs in `messages.db` which may not match `their_jid` in `whatsmeow_contacts`.
