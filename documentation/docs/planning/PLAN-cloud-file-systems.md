# Plan: Cloud File System Tools

**Status: Planned**

## Context

The agent can interact with Gmail, Google Calendar, Google Contacts, web pages, and LinkedIn — but has no access to cloud-stored files. Adding cloud file system tools enables the agent to search, read, create, and manage files in services like Google Drive and OneDrive, unlocking use cases such as:

- Finding and reading documents, spreadsheets, and PDFs stored in the cloud
- Creating and uploading files on behalf of the user
- Organizing files (move, rename, delete)
- Searching across file content and metadata

## Phased Approach

### Phase 1: Google Drive (Recommended First)

**Why Google Drive first:**

1. **Existing infrastructure** — the project already has Google OAuth 2.0 for Gmail, Calendar, and Contacts. Same `client_id`/`client_secret`, same token flow, same SDK.
2. **No new Python dependencies** — `google-api-python-client` is already installed. Just add the Drive scope and call `build('drive', 'v3', credentials=creds)`.
3. **Richest search** — query by name, content, MIME type, date, ownership, etc.
4. **Best free tier** — 15 GB (vs 5 GB OneDrive, 2 GB Dropbox).
5. **Generous rate limits** — 20,000 requests per 100 seconds.

### Phase 2: OneDrive (Microsoft Graph API)

- Requires separate Azure app registration (free, but more setup)
- Uses `msgraph-sdk` + `azure-identity` (new dependencies)
- Native async support
- Implements the same `CloudFileProvider` protocol defined in Phase 1

### Phase 3: Dropbox (if needed)

- OAuth 2.0 with manual flow (no `InstalledAppFlow` equivalent)
- Official `dropbox` SDK (sync only, would need async wrappers)
- Smallest free tier (2 GB)

## Provider Comparison

| Factor | Google Drive | OneDrive | Dropbox | Box | iCloud |
|--------|:-----------:|:--------:|:-------:|:---:|:------:|
| Official Python SDK | `google-api-python-client` | `msgraph-sdk` | `dropbox` | `boxsdk` | None |
| Auth | OAuth 2.0 | OAuth 2.0 (Azure AD) | OAuth 2.0 | OAuth 2.0 / JWT | Unofficial |
| Full CRUD + Search | Yes | Yes | Yes | Yes | Read-only |
| Free storage | 15 GB | 5 GB | 2 GB | 10 GB | 5 GB |
| API cost | Free | Free | Free | Free | N/A |
| Async support | Via wrappers | Native | Sync only | Sync only | N/A |
| Existing project infra | Yes | No | No | No | No |
| Integration effort | ~1-2 days | ~3-5 days | ~2-3 days | ~2-3 days | Not viable |

**iCloud** is excluded — no official API, unofficial libraries are fragile, and Apple can ban accounts using them.

## Unified Abstraction Libraries

No viable open-source library exists that abstracts across Google Drive, OneDrive, and Dropbox. All existing options (Apache Libcloud, `cloudstorage`, `cloudpathlib`) target IaaS object storage (S3, GCS, Azure Blob), not consumer file services.

**Decision:** Define our own `CloudFileProvider` protocol (mirroring the `SearchProvider` pattern from web search) so multiple providers can be added behind a common interface.

## Phase 1 Implementation: Google Drive

### New Files

```
tools/
├── cloud_files/
│   ├── cloud_file_provider.py        # Protocol / base interface
│   ├── google_drive_provider.py      # Google Drive implementation
│   ├── drive_auth.py                 # OAuth (same pattern as gmail_auth.py)
│   ├── drive_list_tool.py            # List files/folders
│   ├── drive_read_tool.py            # Download/read file content
│   ├── drive_upload_tool.py          # Upload/create files
│   ├── drive_search_tool.py          # Search by name/content/type
│   └── drive_delete_tool.py          # Delete/trash files
```

### Provider Protocol

```python
@runtime_checkable
class CloudFileProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    async def list_files(self, folder_id: str | None, page_size: int) -> list[CloudFile]: ...
    async def read_file(self, file_id: str) -> CloudFileContent: ...
    async def upload_file(self, name: str, content: bytes, folder_id: str | None, mime_type: str | None) -> CloudFile: ...
    async def search_files(self, query: str, page_size: int) -> list[CloudFile]: ...
    async def delete_file(self, file_id: str) -> None: ...
```

### Tool Input Schemas

**`drive_search`** (primary discovery tool)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | Search query (searches name and content) |
| `mimeType` | string | no | — | Filter by MIME type (e.g. `application/pdf`) |
| `maxResults` | number | no | `10` | Max results to return (max 50) |

**`drive_list`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `folderId` | string | no | `root` | Folder to list (default: root) |
| `maxResults` | number | no | `20` | Max results to return (max 100) |

**`drive_read`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `fileId` | string | yes | — | ID of the file to read |
| `maxChars` | number | no | `50000` | Max characters to return |

Google Docs/Sheets/Slides will be exported to plain text or CSV automatically. Binary files (images, PDFs) will return metadata only with a download note.

**`drive_upload`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | yes | — | File name |
| `content` | string | yes | — | File content (text) |
| `folderId` | string | no | `root` | Target folder ID |
| `mimeType` | string | no | `text/plain` | MIME type of the content |

**`drive_delete`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `fileId` | string | yes | — | ID of the file to delete |
| `permanent` | boolean | no | `false` | If false, moves to trash; if true, permanently deletes |

### Authentication

Follow the existing Google auth pattern (`gmail_auth.py`):

- Scope: `https://www.googleapis.com/auth/drive` (or `drive.file` for narrower access)
- Token storage: `.drive-tokens/token.json`
- Module-level singleton cache for the service object
- Reuse `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from `.env`

### Registration

In `tool_registry.py`, add Drive tools to the existing Google conditional block:

```python
if google_client_id and google_client_secret:
    from .tools.cloud_files.drive_list_tool import DriveListTool
    from .tools.cloud_files.drive_read_tool import DriveReadTool
    from .tools.cloud_files.drive_upload_tool import DriveUploadTool
    from .tools.cloud_files.drive_search_tool import DriveSearchTool
    from .tools.cloud_files.drive_delete_tool import DriveDeleteTool

    tools.extend([
        DriveSearchTool(google_client_id, google_client_secret),
        DriveListTool(google_client_id, google_client_secret),
        DriveReadTool(google_client_id, google_client_secret),
        DriveUploadTool(google_client_id, google_client_secret),
        DriveDeleteTool(google_client_id, google_client_secret),
    ])
```

### Output Formats

**List/Search results:**
```
Google Drive: 3 files in "My Documents"

1. Project Proposal.docx (Google Doc)
   ID: 1aBcDeFgHiJkLmNoPqRsT
   Modified: 2026-02-15 14:30
   Size: 24 KB

2. Budget 2026.xlsx (Google Sheet)
   ID: 2uVwXyZaBcDeFgHiJkLm
   Modified: 2026-02-10 09:15
   Size: 156 KB

3. meeting-notes.pdf
   ID: 3nOpQrStUvWxYzAbCdEf
   Modified: 2026-02-01 11:00
   Size: 892 KB
```

**Read result:**
```
File: Project Proposal.docx
ID: 1aBcDeFgHiJkLmNoPqRsT
Type: Google Doc (exported as text/plain)
Modified: 2026-02-15 14:30
Length: 3,245 chars

--- Content ---

[file content here]
```

## Dependencies

### Phase 1 (Google Drive)
- No new Python packages — `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` already installed
- Google Drive API must be enabled in the existing Google Cloud project

### Phase 2 (OneDrive)
- New packages: `msgraph-sdk`, `azure-identity`
- Azure app registration (free)
- New env vars: `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`

## Not in Scope

- **Google Workspace admin operations** — no domain-wide delegation or admin consent
- **Real-time sync / change tracking** — polling for changes; no webhooks
- **Binary file manipulation** — reading/writing images, audio, video content
- **Shared drive management** — focus on personal "My Drive" first
- **File versioning** — read current version only
- **Large file uploads** — simple upload only (<5 MB); resumable upload sessions deferred

## Verification

1. **Search**: `drive_search` with a query → returns matching files with IDs
2. **List**: `drive_list` on root → returns top-level files and folders
3. **Read text file**: `drive_read` on a Google Doc → returns exported plain text
4. **Read PDF metadata**: `drive_read` on a PDF → returns metadata + content
5. **Upload**: `drive_upload` creates a new text file → appears in Drive
6. **Delete**: `drive_delete` trashes a file → file moved to trash
7. **Tools registered**: All 5 Drive tools appear in startup banner when Google credentials present
