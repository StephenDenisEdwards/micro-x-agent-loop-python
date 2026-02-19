# Plan: Fix WhatsApp Contact Names

**Status: Proposed** (2026-02-19)

## Problem

WhatsApp tools return phone numbers instead of contact names for individual chats. Group names work correctly.

**Example:** The agent shows `447930348027` where the phone and desktop app show "John Smith".

All 59 chats in the SQLite database have a `name` column, but for individual contacts the value is the raw phone number or JID — never the person's actual name.

## Root Cause

The Go bridge (`whatsapp-mcp/whatsapp-bridge/main.go`) has three problems:

### 1. `GetChatName()` only checks `FullName` (line 991-999)

```go
contact, err := client.Store.Contacts.GetContact(context.Background(), jid)
if err == nil && contact.FullName != "" {
    name = contact.FullName
} else if sender != "" {
    name = sender        // falls through to phone number
} else {
    name = jid.User      // falls through to phone number
}
```

The `ContactInfo` struct (whatsmeow `types/user.go:64-74`) has three name fields:

| Field | Source | Populated? |
|-------|--------|------------|
| `FullName` | Your phone's address book (synced via app state) | Rarely — requires full app state sync |
| `PushName` | The name the contact chose for themselves in WhatsApp settings | Usually populated |
| `BusinessName` | Verified business name | Only for business accounts |

The code only checks `FullName` and never falls back to `PushName` or `BusinessName`.

### 2. `handleMessage()` ignores `msg.Info.PushName` (line 412-418)

```go
func handleMessage(..., msg *events.Message, ...) {
    sender := msg.Info.Sender.User           // phone number
    name := GetChatName(..., sender, ...)     // passes phone number as fallback
```

Every incoming `events.Message` has a `PushName` field (`types/message.go:101`) containing the sender's self-chosen display name. This is the most reliable source of contact names, but it's completely ignored.

### 3. No event handlers for name-related events (line 838-854)

The event handler switch only handles `events.Message`, `events.HistorySync`, `events.Connected`, and `events.LoggedOut`. It does not handle:

- **`events.PushName`** — emitted when a message arrives with a different push name than cached. Contains `NewPushName` and the contact's JID.
- **`events.Contact`** — emitted when a contact entry is modified (including during full app state sync). Contains `ContactAction.FullName` and `FirstName` from the user's address book.

## How Other Projects Handle This

### OpenClaw (Baileys / Node.js)

OpenClaw uses the Baileys library (TypeScript equivalent of whatsmeow) and extracts `pushName` directly from each incoming message:

```typescript
// src/web/inbound/monitor.ts:208
pushName: msg.pushName ?? undefined

// src/web/inbound/monitor.ts:296
const senderName = msg.pushName ?? undefined
```

The push name is passed through the message pipeline and stored in pairing request metadata. OpenClaw does not maintain a persistent contact database — it relies on per-message push names.

This confirms that **push names are the practical solution** for getting human-readable contact names without access to the phone's address book.

## Proposed Fix

Changes to `whatsapp-mcp/whatsapp-bridge/main.go` (upstream repo):

### A. Update `GetChatName()` fallback chain

For individual contacts, add `PushName` and `BusinessName` fallbacks:

```go
contact, err := client.Store.Contacts.GetContact(context.Background(), jid)
if err == nil && contact.FullName != "" {
    name = contact.FullName
} else if err == nil && contact.PushName != "" {
    name = contact.PushName
} else if err == nil && contact.BusinessName != "" {
    name = contact.BusinessName
} else if sender != "" {
    name = sender
} else {
    name = jid.User
}
```

### B. Pass push name from `handleMessage()`

Use `msg.Info.PushName` as the sender hint instead of the raw phone number:

```go
func handleMessage(..., msg *events.Message, ...) {
    sender := msg.Info.PushName
    if sender == "" {
        sender = msg.Info.Sender.User
    }
    name := GetChatName(..., sender, ...)
```

### C. Add event handlers for name updates

```go
case *events.PushName:
    if v.NewPushName != "" {
        chatJID := v.JID.String()
        messageStore.StoreChat(chatJID, v.NewPushName, time.Now())
        logger.Infof("Updated push name for %s: %s", chatJID, v.NewPushName)
    }

case *events.Contact:
    if v.Action != nil {
        fullName := v.Action.GetFullName()
        if fullName != "" {
            chatJID := v.JID.String()
            messageStore.StoreChat(chatJID, fullName, time.Now())
            logger.Infof("Updated contact name for %s: %s", chatJID, fullName)
        }
    }
```

### D. Update existing names on reconnect

After the bridge connects and the contact store is populated, iterate through existing chats and update any that still have phone numbers as names:

```go
// After connection stabilizes
rows, _ := messageStore.db.Query("SELECT jid FROM chats WHERE name = jid OR name LIKE '%@%'")
for rows.Next() {
    var chatJID string
    rows.Scan(&chatJID)
    jid, _ := types.ParseJID(chatJID)
    contact, err := client.Store.Contacts.GetContact(context.Background(), jid)
    if err == nil {
        newName := contact.FullName
        if newName == "" { newName = contact.PushName }
        if newName == "" { newName = contact.BusinessName }
        if newName != "" && newName != chatJID {
            messageStore.StoreChat(chatJID, newName, time.Now())
        }
    }
}
```

## Name Priority

The name resolution order (best to worst):

1. **`FullName`** from contact store — the name you gave them in your phone's address book
2. **`PushName`** from contact store or message — the name they chose for themselves
3. **`BusinessName`** from contact store — verified business name
4. **`msg.Info.PushName`** — push name from the current message (most reliable source)
5. **Phone number** — last resort

## Limitations

- **Push names are not your address book names.** If you saved someone as "Mom", but their WhatsApp push name is "Jane Edwards", the bridge will show "Jane Edwards". This matches WhatsApp Web's behaviour when it doesn't have access to your phone contacts.
- **Push names can change.** Users can update their WhatsApp display name at any time. The `events.PushName` handler keeps the database current.
- **First-time contacts without messages.** If you haven't received a message from someone yet, their push name is unknown. The phone number remains until a message arrives.
- **`events.Contact` depends on app state sync.** The full address book sync doesn't always complete, especially on reconnections. Push names are more reliable.

## Scope

This fix is in the **upstream** `whatsapp-mcp` Go bridge (not our code). Options:

1. **Fork and fix** — maintain our own fork with these changes
2. **Contribute upstream** — submit a PR to [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)
3. **Both** — fork for immediate use, PR upstream for long-term

## Files Affected

| File | Change |
|------|--------|
| `whatsapp-mcp/whatsapp-bridge/main.go` | Update `GetChatName()`, `handleMessage()`, add event handlers |
| No changes to the Python MCP server | It already reads `name` from SQLite correctly |
| No changes to our agent code | The issue is entirely in the Go bridge |
