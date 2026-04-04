# Salesforce CRM API Technical Reference

> **Purpose:** Concrete technical details for building MCP tool servers and agent integrations against Salesforce APIs.  
> **Companion:** See `salesforce-research-report.md` for the broader landscape survey, third-party ecosystem, and architectural recommendations.  
> **Date:** 2026-04-04

---

## Table of contents

1. [Authentication](#1-authentication)
2. [REST API — Core CRUD](#2-rest-api--core-crud)
3. [SOQL Queries](#3-soql-queries)
4. [Composite API](#4-composite-api)
5. [Schema Discovery](#5-schema-discovery)
6. [Bulk API 2.0](#6-bulk-api-20)
7. [Event-Driven APIs](#7-event-driven-apis)
8. [Rate Limits & Org Limits](#8-rate-limits--org-limits)
9. [Security & Data Governance](#9-security--data-governance)
10. [Agentforce & AI APIs](#10-agentforce--ai-apis)
11. [API Versioning](#11-api-versioning)
12. [MCP Tool Server Design Recommendations](#12-mcp-tool-server-design-recommendations)

---

## 1. Authentication

### 1.1 JWT Bearer Flow (server-to-server — recommended)

The preferred flow for an MCP tool server. No interactive user login, no refresh tokens to manage.

**Prerequisites:**
- Connected App in Salesforce with "Enable OAuth Settings" and "Use Digital Signatures"
- X.509 certificate uploaded to the Connected App; private key stored securely by the MCP server
- Salesforce user pre-authorized (Permitted Users = "Admin approved", assigned via Profile or Permission Set)
- Minimum OAuth scope: `api`

**Certificate/key generation:**

```bash
openssl req -x509 -sha256 -nodes -days 365 \
  -newkey rsa:2048 -keyout private.pem -out certificate.pem
```

**Token endpoint:**

| Environment | URL |
|---|---|
| Production | `POST https://login.salesforce.com/services/oauth2/token` |
| Sandbox | `POST https://test.salesforce.com/services/oauth2/token` |
| My Domain | `POST https://{MyDomain}.my.salesforce.com/services/oauth2/token` |

**JWT claims:**

```json
{
  "iss": "<connected_app_consumer_key>",
  "sub": "<salesforce_username>",
  "aud": "https://login.salesforce.com",
  "exp": 1714000000
}
```

| Claim | Value |
|---|---|
| `iss` | Consumer Key (client_id) from the Connected App |
| `sub` | Username of the Salesforce user the app acts as |
| `aud` | `https://login.salesforce.com` (production) or `https://test.salesforce.com` (sandbox) |
| `exp` | Expiration — must be within **5 minutes** of current time |

**Signing:** RS256 with private key. Header: `{"alg": "RS256"}`.

**Token request:**

```
POST /services/oauth2/token HTTP/1.1
Host: login.salesforce.com
Content-Type: application/x-www-form-urlencoded

grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=<signed_jwt>
```

**Successful response (200):**

```json
{
  "access_token": "00D...!AQ...",
  "scope": "api",
  "instance_url": "https://yourorg.my.salesforce.com",
  "id": "https://login.salesforce.com/id/00Dxx.../005xx...",
  "token_type": "Bearer"
}
```

**Token refresh pattern:** No refresh_token is issued. When the access token expires (org session timeout, typically ~2 hours), mint and sign a new JWT and POST again. Catch 401 responses and re-authenticate automatically.

**Common errors:** `invalid_grant` (user not pre-authorized, cert mismatch, expired JWT, wrong audience), `invalid_client_id` (wrong consumer key in `iss`).

### 1.2 Authorization Code Flow (user-delegated)

Use when the agent must act on behalf of a specific user.

**Step 1 — Authorization redirect:**

```
GET https://login.salesforce.com/services/oauth2/authorize
  ?response_type=code
  &client_id={consumer_key}
  &redirect_uri={callback_url}
  &scope=api+refresh_token
  &state={csrf_token}
```

**Step 2 — Callback:** `{redirect_uri}?code={authorization_code}&state={csrf_token}`

**Step 3 — Token exchange:**

```
grant_type=authorization_code&code={auth_code}
&client_id={consumer_key}&client_secret={consumer_secret}&redirect_uri={callback_url}
```

Returns both `access_token` and `refresh_token`. Refresh tokens don't expire by default (configurable per connected app).

**Refresh:** `grant_type=refresh_token&refresh_token={token}&client_id={key}&client_secret={secret}`

### 1.3 Client Credentials Flow

Available since Spring '23 (API v57.0+). No user impersonation — the connected app itself is the identity, running as a configured "Run As" user.

```
grant_type=client_credentials&client_id={consumer_key}&client_secret={consumer_secret}
```

Simpler than JWT bearer (no certificate) but client_secret must be protected. JWT bearer is preferred for high-security environments.

### 1.4 OAuth Scopes

| Scope | Purpose |
|---|---|
| `api` | REST/SOAP API access (**required** for most integrations) |
| `refresh_token` / `offline_access` | Obtain refresh tokens |
| `full` | All user permissions |
| `id` | Identity URL access |
| `openid` / `profile` / `email` | OIDC claims |
| `chatter_api` | Chatter API access |
| `wave_api` | CRM Analytics access |
| `cdp_query` / `cdp_ingest` | Data Cloud access |

Scopes on the connected app act as a ceiling; scopes requested at auth time select a subset.

---

## 2. REST API — Core CRUD

**Base URL:** `https://<instance_url>/services/data/v63.0`

**Required headers:**

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

### Standard CRM object endpoints

All paths relative to `/services/data/v63.0`.

| Object | Create | Read / Update / Delete |
|---|---|---|
| Account | `POST /sobjects/Account/` | `GET/PATCH/DELETE /sobjects/Account/{id}` |
| Contact | `POST /sobjects/Contact/` | `GET/PATCH/DELETE /sobjects/Contact/{id}` |
| Lead | `POST /sobjects/Lead/` | `GET/PATCH/DELETE /sobjects/Lead/{id}` |
| Opportunity | `POST /sobjects/Opportunity/` | `GET/PATCH/DELETE /sobjects/Opportunity/{id}` |
| Case | `POST /sobjects/Case/` | `GET/PATCH/DELETE /sobjects/Case/{id}` |

### Create

```
POST /services/data/v63.0/sobjects/Account/
```

```json
{
  "Name": "Acme Corporation",
  "Industry": "Technology",
  "Website": "https://acme.example.com"
}
```

Response (201):

```json
{
  "id": "001xx000003DGb2AAG",
  "success": true,
  "errors": []
}
```

### Read

```
GET /services/data/v63.0/sobjects/Account/001xx000003DGb2AAG
```

Optional field selection: `?fields=Name,Industry,Website`

Response (200):

```json
{
  "attributes": {
    "type": "Account",
    "url": "/services/data/v63.0/sobjects/Account/001xx000003DGb2AAG"
  },
  "Id": "001xx000003DGb2AAG",
  "Name": "Acme Corporation",
  "Industry": "Technology",
  "Website": "https://acme.example.com"
}
```

### Update

```
PATCH /services/data/v63.0/sobjects/Account/001xx000003DGb2AAG
```

```json
{ "Industry": "Manufacturing" }
```

Response: **204 No Content**

### Delete

```
DELETE /services/data/v63.0/sobjects/Account/001xx000003DGb2AAG
```

Response: **204 No Content**

### Upsert by External ID

```
PATCH /services/data/v63.0/sobjects/Account/External_Id__c/EXT-001
```

```json
{ "Name": "Acme Corporation", "Industry": "Technology" }
```

Response: **201** (created) or **204** (updated)

---

## 3. SOQL Queries

### Execute a query

```
GET /services/data/v63.0/query?q=SELECT+Id,Name,Industry+FROM+Account+WHERE+Industry='Technology'+LIMIT+100
```

The SOQL string must be URL-encoded.

### Response

```json
{
  "totalSize": 2340,
  "done": false,
  "nextRecordsUrl": "/services/data/v63.0/query/01gxx00000FAKE-2000",
  "records": [
    {
      "attributes": { "type": "Account", "url": "/services/data/v63.0/sobjects/Account/001xx..." },
      "Id": "001xx000003DGb2AAG",
      "Name": "Acme Corporation",
      "Industry": "Technology"
    }
  ]
}
```

### Pagination

- Default batch size: 2000 records. Set with header: `Sforce-Query-Options: batchSize=500` (range: 200–2000)
- When `done` is `false`, follow `nextRecordsUrl` with GET to retrieve the next batch
- Query locator valid for **15 minutes** of inactivity
- Keep calling until `done` is `true`

### queryAll (includes deleted/archived)

```
GET /services/data/v63.0/queryAll?q=SELECT+Id,Name+FROM+Account+WHERE+IsDeleted=true
```

### Key limits

| Limit | Value |
|---|---|
| Max SOQL query string length | 100,000 characters |
| Max OFFSET | 2,000 |
| Max relationship subquery types | 20 per query |
| Query timeout | 120 seconds |
| API calls | 1 per query execution + 1 per `nextRecordsUrl` page |

---

## 4. Composite API

Three composite resources under `/services/data/v63.0/composite/`.

### 4.1 Composite Request (dependent subrequests with references)

```
POST /services/data/v63.0/composite
```

Up to **25 subrequests** (5 can be queries). Subrequests execute sequentially; results can be referenced with `@{referenceId.field}`.

```json
{
  "allOrNone": true,
  "compositeRequest": [
    {
      "method": "POST",
      "url": "/services/data/v63.0/sobjects/Account",
      "referenceId": "newAccount",
      "body": { "Name": "Acme Corporation" }
    },
    {
      "method": "POST",
      "url": "/services/data/v63.0/sobjects/Contact",
      "referenceId": "newContact",
      "body": {
        "LastName": "Smith",
        "AccountId": "@{newAccount.id}"
      }
    }
  ]
}
```

Response:

```json
{
  "compositeResponse": [
    {
      "body": { "id": "001xx...", "success": true, "errors": [] },
      "httpStatusCode": 201,
      "referenceId": "newAccount"
    },
    {
      "body": { "id": "003xx...", "success": true, "errors": [] },
      "httpStatusCode": 201,
      "referenceId": "newContact"
    }
  ]
}
```

`allOrNone: true` rolls back all changes if any subrequest fails.

### 4.2 sObject Tree (parent-child creation)

```
POST /services/data/v63.0/composite/tree/Account/
```

All-or-nothing. Up to **200 total records**.

```json
{
  "records": [
    {
      "attributes": { "type": "Account", "referenceId": "acct1" },
      "Name": "Acme Corporation",
      "Contacts": {
        "records": [
          {
            "attributes": { "type": "Contact", "referenceId": "c1" },
            "LastName": "Smith",
            "Email": "smith@acme.example.com"
          }
        ]
      }
    }
  ]
}
```

Success (201):

```json
{
  "hasErrors": false,
  "results": [
    { "referenceId": "acct1", "id": "001xx..." },
    { "referenceId": "c1", "id": "003xx..." }
  ]
}
```

### 4.3 sObject Collections (batch CRUD, same object type)

Up to **200 records** per request. Supports `allOrNone`.

| Operation | Method | Endpoint |
|---|---|---|
| Create | POST | `/composite/sobjects` |
| Update | PATCH | `/composite/sobjects` |
| Delete | DELETE | `/composite/sobjects?ids=001xx,003xx&allOrNone=false` |
| Retrieve | POST | `/composite/sobjects/Account` (with `ids` + `fields` body) |

---

## 5. Schema Discovery

### List all objects (Describe Global)

```
GET /services/data/v63.0/sobjects/
```

```json
{
  "sobjects": [
    {
      "name": "Account",
      "label": "Account",
      "keyPrefix": "001",
      "custom": false,
      "queryable": true,
      "createable": true,
      "updateable": true,
      "deletable": true,
      "urls": {
        "describe": "/services/data/v63.0/sobjects/Account/describe"
      }
    }
  ]
}
```

### Describe a specific object

```
GET /services/data/v63.0/sobjects/Account/describe
```

Returns full metadata: fields (name, type, length, nillable, createable, updateable, picklistValues), child relationships, record type infos.

Key field properties:

```json
{
  "name": "Industry",
  "label": "Industry",
  "type": "picklist",
  "length": 255,
  "nillable": true,
  "createable": true,
  "updateable": true,
  "picklistValues": [
    { "active": true, "value": "Technology", "defaultValue": false, "label": "Technology" }
  ]
}
```

### Picklist values via UI API (record-type-aware)

```
GET /services/data/v63.0/ui-api/object-info/Account/picklist-values/{recordTypeId}
```

Default record type: `012000000000000AAA`.

### Data classification via Tooling API

```
SELECT QualifiedApiName, SecurityClassification, ComplianceGroup
FROM FieldDefinition WHERE EntityDefinitionId = 'Account'
```

Returns field-level sensitivity labels (PII, HIPAA, GDPR, etc.) — useful for building a redaction map.

---

## 6. Bulk API 2.0

For large-scale data operations (thousands to millions of records).

### Job lifecycle

`Create Job` → `Upload CSV` → `Close Job` → `Poll Status` → `Retrieve Results`

### Endpoints

**Base:** `/services/data/v62.0/jobs/ingest` (ingest) or `/jobs/query` (query)

| Step | Method | Endpoint | Content-Type |
|---|---|---|---|
| Create ingest job | POST | `/jobs/ingest` | `application/json` |
| Upload CSV | PUT | `/jobs/ingest/{jobId}/batches` | `text/csv` |
| Close job | PATCH | `/jobs/ingest/{jobId}` | `application/json` |
| Poll status | GET | `/jobs/ingest/{jobId}` | — |
| Successful results | GET | `/jobs/ingest/{jobId}/successfulResults` | — |
| Failed results | GET | `/jobs/ingest/{jobId}/failedResults` | — |
| Unprocessed records | GET | `/jobs/ingest/{jobId}/unprocessedrecords` | — |

### Operations

`insert`, `update`, `upsert`, `delete`, `hardDelete`, `query`, `queryAll`

### Create job payload

```json
{
  "object": "Account",
  "operation": "upsert",
  "externalIdFieldName": "MyExtId__c",
  "contentType": "CSV",
  "lineEnding": "LF",
  "columnDelimiter": "COMMA"
}
```

### Close job (signal upload complete)

```json
{ "state": "UploadComplete" }
```

### Job states

`Open` → `UploadComplete` → `InProgress` → `JobComplete` | `Failed` | `Aborted`

### Error handling

**Partial success is the default.** Each record processed independently. Check `numberRecordsFailed` in job status; retrieve failed records CSV for error details.

Failed results CSV includes: `sf__Id`, `sf__Error` (e.g., `REQUIRED_FIELD_MISSING:Required fields are missing: [Name]`), plus all original input columns.

### Limits

| Limit | Value |
|---|---|
| Max file size per upload | 150 MB |
| Max record size (single row) | 10 MB |
| Max concurrent ingest jobs | 15 per org |
| Max concurrent query jobs | 5 per org |
| Job auto-abort timeout | 10 minutes with no data upload |
| Query result pagination | `locator` parameter; `null` = all results retrieved |
| Max query results size | 1 GB per job |

---

## 7. Event-Driven APIs

### 7.1 Change Data Capture (CDC)

Publishes near-real-time change events when records are created, updated, deleted, or undeleted.

**Supported objects:** ~40+ standard objects (Account, Contact, Lead, Opportunity, Case, Task, Event, Order, etc.) + all custom objects. Must be enabled in Setup > Change Data Capture.

**Channel naming:**

| Scope | Pattern | Example |
|---|---|---|
| Standard object | `/data/{Object}ChangeEvent` | `/data/AccountChangeEvent` |
| Custom object | `/data/{Object}__ChangeEvent` | `/data/MyObj__ChangeEvent` |
| All CDC | `/data/ChangeEvents` | `/data/ChangeEvents` |

**Event payload:**

```json
{
  "schema": "TlGL0MRhTgO3fL9_lFYEjA",
  "payload": {
    "ChangeEventHeader": {
      "entityName": "Account",
      "recordIds": ["001xx000003DGQWAA4"],
      "changeType": "UPDATE",
      "changeOrigin": "com/salesforce/api/rest/48.0",
      "transactionKey": "000a1f13-...",
      "sequenceNumber": 1,
      "commitTimestamp": 1695000000000,
      "commitUser": "005xx000001XyZAA0",
      "changedFields": ["Industry", "Description", "LastModifiedDate"],
      "diffFields": ["Industry", "Description"],
      "nulledFields": []
    },
    "Industry": "Technology",
    "Description": "Updated description"
  },
  "event": {
    "replayId": 12345,
    "EventUuid": "a1b2c3d4-..."
  }
}
```

Key details:
- `changeType`: `CREATE`, `UPDATE`, `DELETE`, `UNDELETE`, `GAP_*` (missed events)
- UPDATE events include only **changed fields** (not full record)
- `nulledFields` lists fields set to null (null values absent from JSON body)
- DELETE events contain only the header (no field values)

**Replay ID handling:**
- `-1` = new events only; `-2` = earliest available (up to 72 hours retention)
- Specific `replayId` = replay from after that event
- **Retention: 3 days (72 hours)**
- Store last processed `replayId` persistently for reliable resume

### 7.2 Pub/Sub API (gRPC) — recommended for new integrations

**Endpoint:** `api.pubsub.salesforce.com:7443` (TLS required)

**gRPC service definition:**

```protobuf
service PubSub {
  rpc Subscribe (stream FetchRequest) returns (stream FetchResponse);
  rpc GetSchema (SchemaRequest) returns (SchemaInfo);
  rpc GetTopic (TopicRequest) returns (TopicInfo);
  rpc Publish (PublishRequest) returns (PublishResponse);
  rpc PublishStream (stream PublishRequest) returns (stream PublishResponse);
}
```

**Authentication via gRPC metadata:**

| Key | Value |
|---|---|
| `accesstoken` | OAuth 2.0 access token |
| `instanceurl` | e.g., `https://myorg.my.salesforce.com` |
| `tenantid` | 18-character Salesforce org ID |

**Subscribe flow control:** Client sends `num_requested` to indicate capacity. Server sends up to that many events, then waits for another `FetchRequest`.

**Payloads:** Apache Avro binary. Use `GetSchema` RPC with the `schema_id` from each event to retrieve the Avro JSON schema, then decode.

**Limits:**

| Limit | Value |
|---|---|
| Max events per Publish call | 100 |
| Max events per FetchRequest | 100 |
| Max concurrent subscriptions per org | 2,000 |
| Max event payload size | 1 MB |
| Event retention | 72 hours |

### 7.3 Platform Events

Custom event definitions (API name ends in `__e`). Published/subscribed from Apex, APIs, Flows, and external systems.

**Publish via REST:**

```
POST /services/data/v63.0/sobjects/Order_Status__e
```

```json
{
  "Order_Id__c": "001xx000003DGQW",
  "Status__c": "Shipped"
}
```

**Batch publish** (up to 10 events):

```
POST /services/data/v63.0/composite/sobjects
```

**Subscribe externally:** Via Pub/Sub API (topic: `/event/{EventApiName}`) or CometD (channel: `/event/{EventApiName}`). Pub/Sub API is recommended.

**Limits (Enterprise Edition):**

| Limit | Value |
|---|---|
| Max events published per hour | 250,000 (standard) |
| Max event payload size | 1 MB |
| Event retention (high-volume) | 72 hours |
| Max custom Platform Event definitions | 200 per org |

---

## 8. Rate Limits & Org Limits

### Limits endpoint

```
GET /services/data/v63.0/limits/
```

```json
{
  "DailyApiRequests": { "Max": 1000000, "Remaining": 985432 },
  "DailyBulkApiRequests": { "Max": 15000, "Remaining": 14998 },
  "DailyBulkV2QueryJobs": { "Max": 10000, "Remaining": 10000 },
  "SingleEmail": { "Max": 5000, "Remaining": 4999 },
  "DailyStandardVolumePlatformEvents": { "Max": 25000, "Remaining": 25000 }
}
```

### Key limits for agent integrations

| Limit | Controls | Typical allocation |
|---|---|---|
| `DailyApiRequests` | Total REST + SOAP calls / 24h | Edition-dependent (Enterprise: base 100k + per-user) |
| `DailyBulkApiRequests` | Bulk API job submissions | 15,000 |
| `DailyStreamingApiEvents` | Platform events + CDC events | Based on add-on purchases |
| Per-user concurrent requests | Long-running requests | 25 |

**Operational notes:**
- Limits accurate within 5 minutes of actual consumption
- Exceeding `DailyApiRequests` returns **HTTP 403** with `REQUEST_LIMIT_EXCEEDED`
- The `/limits` call itself counts as 1 API call
- GraphQL returns **HTTP 503** when rate-limited (uses Connect API limits)

---

## 9. Security & Data Governance

### 9.1 Permission model

The API enforces the **same security model** as the UI — no bypass.

| Layer | Effect on API |
|---|---|
| "API Enabled" permission | Without it: zero API access |
| Object-level CRUD | Per profile, per sObject |
| Field-Level Security (FLS) | Fields without read access **silently omitted** from API results |
| Record-level sharing | SOQL returns only records visible to the running user |

**SOQL enforcement modifiers:**
- `WITH SECURITY_ENFORCED` — enforces FLS, errors on inaccessible fields
- `WITH USER_MODE` (Spring '23+) — enforces CRUD + FLS + sharing

**Recommendation:** Dedicated integration user with minimal profile. No "View All Data" unless genuinely needed.

### 9.2 Transaction Security Policies

Real-time policies that can **block, notify, or freeze** based on events:
- `ApiEvent` — monitors SOQL/SOSL via API (entity, query, rows returned, source IP)
- `LoginEvent` — block from unexpected IPs
- `ReportEvent` / `BulkApiResultEvent` — report/bulk monitoring

Handle `BLOCKED_BY_POLICY` errors gracefully.

### 9.3 Event Monitoring

**EventLogFile (daily CSV):**

```
GET /services/data/vXX.0/query?q=SELECT+Id,EventType,LogDate+FROM+EventLogFile
```

Key log types: `API`, `RestApi`, `Login`, `BulkApi`, `BulkApi2`. Retention: 30 days standard, 6 months with Shield.

**Real-Time Event Monitoring:** Platform Events (`ApiEvent`, `LoginEvent`, `ApiAnomalyEvent`) via Pub/Sub API. Requires Shield or Event Monitoring license.

### 9.4 Shield Platform Encryption

- **Deterministic encryption:** Fields usable in SOQL WHERE (exact match)
- **Probabilistic encryption:** Fields cannot be filtered/sorted
- Without "View Encrypted Data" permission: values returned as `********`

### 9.5 Consent API

```
GET /services/data/vXX.0/consent/action/lookup?actions=email,track,process&ids={contactId}
```

Returns per-action consent status. Individual object tracks: `ShouldForget`, `HasOptedOutTracking`, `HasOptedOutProcessing`, `CanStorePII`.

### 9.6 Data classification

Field-level metadata via Tooling API: `SecurityClassification` (Public/Internal/Confidential/Restricted/MissionCritical), `ComplianceGroup` (CCPA/COPPA/GDPR/HIPAA/PCI/PII).

### 9.7 Sandbox Data Masking

Salesforce Data Mask (managed package) — masks/deletes/replaces sensitive data in sandboxes after refresh. Masked data cannot be unmasked. Essential for agent testing.

---

## 10. Agentforce & AI APIs

### 10.1 Agent API

External apps can run conversational sessions with Agentforce agents.

**Authentication:** OAuth 2.0 Client Credentials via **External Client App** (not standard Connected App). Issues JWT-based access tokens. Cannot reuse the same Connected App used for standard Salesforce APIs.

**Base URL:** `https://api.salesforce.com/einstein/ai-agent/v1/`

| Operation | Method | Endpoint |
|---|---|---|
| Start session | POST | `/agents/{AGENT_ID}/sessions` |
| Send message (sync) | POST | `/sessions/{SESSION_ID}/messages` |
| Send message (stream) | POST | `/sessions/{SESSION_ID}/messages/stream` |
| End session | DELETE | `/sessions/{SESSION_ID}` |

**Start session request:**

```json
{
  "externalSessionKey": "{UUID}",
  "instanceConfig": { "endpoint": "https://{MY_DOMAIN_URL}" },
  "streamingCapabilities": { "chunkTypes": ["Text"] },
  "bypassUser": true
}
```

**Send message request:**

```json
{
  "message": {
    "sequenceId": 1,
    "type": "Text",
    "text": "What is the status of case 00001234?"
  }
}
```

**Streaming response (SSE):** `ProgressIndicator` → `TextChunk` (repeated) → `Inform` → `EndOfTurn`

**Limitations:**
- Not supported for "Agentforce (Default)" agents — only custom-configured agents
- Requires separate auth infrastructure from standard Salesforce APIs
- Recommended max 10 turns per session
- Sessions time out if idle

### 10.2 Models API (Einstein Generative AI)

Call LLMs through Salesforce's Trust Layer.

**Base URL:** `https://api.salesforce.com/einstein/platform/v1/models/`

| Operation | Method | Endpoint |
|---|---|---|
| Text generation | POST | `/models/{modelName}/generations` |
| Chat completion | POST | `/models/{modelName}/chat-generations` |
| Embeddings | POST | `/models/{modelName}/embeddings` |

**Chat generations request:**

```json
{
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "Summarize the latest activity on account 001xx." }
  ]
}
```

**Available models:** OpenAI GPT-4o/GPT-4o mini, Anthropic Claude, Google Gemini, Amazon Bedrock models — referenced by `sfdc_ai__Default*` API names configured in Einstein Studio.

### 10.3 Einstein Trust Layer

All Models API calls pass through automatically:

| Protection | When | Details |
|---|---|---|
| Dynamic Grounding | Before LLM call | Augments prompt with CRM context |
| Data Masking | Before LLM call | PII replaced with placeholders, un-masked after response |
| Toxicity Detection | After response | Safety scoring |
| Audit Trail | Throughout | Full prompt tracking |
| Zero Data Retention | LLM provider | Contractual: no storage, no training |

**Important:** Data masking is **disabled for Agentforce** (relies on zero-data-retention and trust boundary instead).

### 10.4 Billing

**Einstein Requests** (outside Agentforce): `ceil((input + output tokens) / 2000) * multiplier` — multiplier varies by model tier (4x to 38x).

**Flex Credits** (through Agentforce, since May 2025): 20 credits per agent action ($0.10/action). Sold in 100k packs ($500). Einstein Requests not consumed when running through Agentforce.

### 10.5 Agentforce platform architecture

Agents run on the **Atlas Reasoning Engine** (ReAct pattern: reason → act → observe).

Three building blocks:
- **Topics** — categories of work with classification descriptions and scope boundaries
- **Instructions** — natural language directives for decisions and guardrails
- **Actions** — tools tied to topics (Flow, Apex `@InvocableMethod`, Prompt Templates, MuleSoft APIs)

Best practice: max **15 actions per topic**.

---

## 11. API Versioning

Salesforce increments API version by 1.0 per release (3 releases/year).

| Release | API Version |
|---|---|
| Spring '25 | v63.0 |
| Summer '25 | v64.0 |
| Winter '26 | v65.0 |
| Spring '26 | v66.0 |

**Discover available versions (no auth):**

```
GET https://<instance>.my.salesforce.com/services/data/
```

**Lifecycle:** Minimum 3-year support per version. Versions 21.0–30.0 retired Summer '25.

**Best practice:** Pin a recent version (v63.0+) in configuration. Discover available versions at startup.

---

## 12. MCP Tool Server Design Recommendations

### Recommended tool surface for an AI agent

| Tool | Maps to | Notes |
|---|---|---|
| `salesforce_query` | SOQL via REST `/query` | Auto-paginate; accept `maxRecords` cap |
| `salesforce_create_record` | `POST /sobjects/{type}/` | Single-record; return new ID |
| `salesforce_update_record` | `PATCH /sobjects/{type}/{id}` | Partial update |
| `salesforce_delete_record` | `DELETE /sobjects/{type}/{id}` | Confirm before execution |
| `salesforce_describe_object` | `GET /sobjects/{type}/describe` | Cache results; use for schema awareness |
| `salesforce_list_objects` | `GET /sobjects/` | Filter to queryable objects |
| `salesforce_get_limits` | `GET /limits/` | Include in tool responses for self-regulation |

### Architecture guidance

1. **Token management:** Store private key via env var (`${SF_PRIVATE_KEY_PATH}`). On startup and on 401, mint fresh JWT, POST to token endpoint. Cache `access_token` and `instance_url`.

2. **Tool granularity:** Expose single-record operations as tools. Use Composite API as an **internal optimization** (batching agent-requested writes) rather than exposing it directly — agents generate cleaner output with single-record tools.

3. **Safe action facade:** For write operations, prefer domain-specific Apex REST endpoints (e.g., `CreateQualifiedLead`, `CloseOpportunityWithReason`) over raw CRUD. Enforces validation, field-level rules, and auditability.

4. **Data protection:** Query `FieldDefinition` classification at startup. Build a sensitive-field map. Redact PII/Restricted/HIPAA fields before sending to external LLM. Check Consent API before processing personal data.

5. **Rate limit awareness:** Check `/limits` periodically. Include remaining quota in tool responses. Back off proactively when approaching thresholds.

6. **Config example:**

```json
{
  "SalesforceAuth": {
    "flow": "jwt_bearer",
    "consumer_key": "${SF_CONSUMER_KEY}",
    "username": "${SF_USERNAME}",
    "private_key_path": "${SF_PRIVATE_KEY_PATH}",
    "audience": "https://login.salesforce.com",
    "instance_url": "${SF_INSTANCE_URL}"
  }
}
```

### Integration patterns for external agent + Salesforce AI

| Pattern | Description | Trade-off |
|---|---|---|
| **A: Agent → Agent API** | Delegate Salesforce tasks to Agentforce agent | Leverages SF permissions/Trust Layer; limited to configured agent capabilities |
| **B: Agent → Models API** | Use Salesforce as LLM provider | Automatic masking/audit; adds latency and Einstein Request costs |
| **C: Agent → REST APIs + own LLM** | Salesforce as data platform only | Full control; must implement own safety controls |
| **D: Events bridge** | Agentforce handles SF-native work; external agent handles cross-system | Clean separation; coordination complexity |
