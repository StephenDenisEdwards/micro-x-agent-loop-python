# Salesforce CRM API Investigation Report
*Generated: April 4, 2026*

## Executive Summary

Salesforce provides a comprehensive suite of APIs for CRM integration, ranging from lightweight REST endpoints to enterprise SOAP services and specialized bulk processing APIs. This investigation covers core API types, authentication patterns, CRM objects, limits, and best practices for integration.

---

## 1. Core API Types

### 1.1 REST API (Primary Integration Method)

**Overview:**
- Lightweight, modern HTTP/JSON interface
- Recommended for mobile/web applications and content-related objects
- Supports multiple standards (OAuth, JSON, XML)

**Key Endpoints:**

| Endpoint | Purpose | Method | Notes |
|----------|---------|--------|-------|
| `/services/data/vXX.X/query?q={SOQL}` | Execute SOQL queries | GET | URL-encode query; returns all or paginated results |
| `/services/data/vXX.X/queryAll` | Query including deleted/archived | GET | Includes soft-deleted records |
| `/services/data/vXX.X/sobjects/{Object}` | Object metadata/CRUD | GET/POST/PATCH/DELETE | Standard CRUD operations |
| `/services/data/vXX.X/limits` | Current org limits | GET | Monitor API consumption |
| `/services/data/vXX.X/composite` | Multi-step operations | POST | Transactional batching |

**SOQL Query Features:**
- Nested queries for parent/child relationships (Account → Contacts → Assets → WorkOrders)
- URL encoding required (spaces → `+`)
- Use correct API object names (e.g., "Opportunity" not "Opportunities")
- Cannot use LIKE clause on Id fields

**Resources:**
- REST API Guide: `developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_rest.htm`
- REST API Reference: `developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_list.htm`

### 1.2 SOAP API (Enterprise Integration)

**Overview:**
- Uses WSDL contract, HTTP/XML only
- Robust for server-to-server enterprise integrations
- Strongly-typed interface

**Use Cases:**
- Legacy system integration
- Enterprise middleware requiring WSDL contracts
- Systems needing strongly-typed interfaces

**Resources:**
- SOAP API Guide: `developer.salesforce.com/docs/atlas.en-us.api.meta/api`

### 1.3 Bulk API 2.0 (Large-Scale Operations)

**Overview:**
- Specialized RESTful API for 50,000+ records
- Asynchronous job-based processing
- Handles up to 1 TB/day data extraction

**Volume Guidelines:**
- **< 2,000 records**: Use REST Composite API (synchronous)
- **> 2,000 records**: Use Bulk API 2.0 (asynchronous)
- **Millions of records**: Bulk API v2 required

**Features:**
- Dedicated bulk allocations (separate from API limits)
- Job, batch, file sizing controls
- Built-in retry for query jobs
- Efficient for single sObject operations

**Resources:**
- Bulk API intro: `developer.salesforce.com/docs/.../asynch_api_intro.htm`

### 1.4 Composite API (Transactional Batching)

**Purpose:** Reduce API calls and enable transactional operations

**Types & Limits:**

| Type | Max Records/Subrequests | Execution Mode | Key Features |
|------|-------------------------|----------------|--------------|
| **Composite Batch** | 25 subrequests | Independent | Unrelated operations in single call |
| **Composite Graph** | 500 records | Synchronous, transactional | Chain requests (output → input) |
| **sObject Collections** | 200 records | Bulk CRUD | Single object type operations |

**Key Constraints:**
- Maximum **5 subrequests** can be sObject Collections or query operations per composite request
- All subrequests count as **single API call** toward limits
- `allOrNone: true` flag enables transactional rollback

**Use Cases:**
- Atomic Account + Contact creation
- Multi-step operations with dependencies
- Reducing API consumption for related operations

**Endpoint:**
- `/services/data/vXX.X/composite/batch/`

**Resources:**
- Composite Batch: `developer.salesforce.com/docs/.../resources_composite_batch.htm`

### 1.5 Additional APIs

| API | Purpose | Interface | Use Case |
|-----|---------|-----------|----------|
| **Tooling API** | Metadata introspection | REST+SOAP | Dev tools, CI, source control |
| **Metadata API** | Deploy/retrieve metadata | SOAP+file-based | Config-as-code, org migrations |
| **Streaming API** | Real-time notifications (legacy) | CometD+JSON | Push notifications (Salesforce recommends Pub/Sub for new apps) |
| **Pub/Sub API** | High-throughput event pub/sub | gRPC/HTTP2+Avro | CDC, platform events |
| **GraphQL (UI API)** | Nested UI queries | GraphQL/HTTP | Fewer round-trips, max 10 subqueries |
| **Apex REST** | Custom endpoints | REST (@RestResource) | Policy-checked "safe action façade" |

---

## 2. Authentication & Authorization

### 2.1 OAuth 2.0 JWT Bearer Flow (Recommended for Server-to-Server)

**Purpose:** API-only access without UI interaction (ETL tools, middleware, CI environments)

**Process:**
1. Construct JWT with claims about server and desired access
2. Sign JWT with private key
3. POST to token endpoint:
   ```
   POST https://login.salesforce.com/services/oauth2/token
   ?grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
   &assertion=<JWT>
   ```
4. Receive access token

**Connected App Setup:**
- Callback URL: Required but unused (use `http://localhost/` or dummy)
- Enable "Use digital signatures" - upload certificate (e.g., `salesforce.crt`)
- OAuth Scopes:
  - `api` (Access and manage data)
  - `refresh_token, offline_access` (Perform requests anytime)

**Response Format:**
```json
{
  "access_token": "...",
  "scope": "api",
  "instance_url": "https://ap4.salesforce.com",
  "id": "https://login.salesforce.com/id/xxx/yyy",
  "token_type": "Bearer"
}
```

### 2.2 Other Authentication Patterns

| Pattern | Use Case | Flow Type |
|---------|----------|-----------|
| **OAuth 2.0 Web Server Flow** | User-delegated access | Authorization code |
| **Username-Password Flow** | Testing (not production) | Direct credentials + security token |
| **Named/External Credentials** | Salesforce calling external systems | JWT bearer support |

---

## 3. Core CRM Objects

### 3.1 Standard Objects (Sales Cloud)

| Object | Purpose | Key Relationships |
|--------|---------|-------------------|
| **Lead** | Prospect or potential customer | Converts to Account/Contact/Opportunity |
| **Account** | Organization/company | Parent to Contacts, Opportunities |
| **Contact** | Individual person | Belongs to Account, linked to Opportunities |
| **Opportunity** | Sale or pending deal | Belongs to Account, linked to Contacts |
| **OpportunityContactRole** | Contact's role in opportunity | Links Contact ↔ Opportunity |

### 3.2 Lead Conversion Process

**Critical Behavior:** Lead conversion creates up to **3 objects simultaneously**:
1. Account (if new)
2. Contact (always)
3. Opportunity (optional)

**API Implications:**
- Use transactional APIs (Composite Graph) for atomic operations
- Handle rollback scenarios for partial failures

### 3.3 Object Metadata

**Resources:**
- Object Reference: `developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/`
- Data Model ERD (Entity Relationship Diagram) available in developer docs
- Use Tooling API for programmatic schema discovery

---

## 4. Governor Limits & Best Practices

### 4.1 Limit Types

**Hard Limits:** Cannot be exceeded
- Apex CPU time
- DML operations per transaction
- SOQL queries per transaction

**Soft Limits:** Can be increased by Salesforce Support or purchasing add-ons
- API calls per 24 hours
- Data storage
- File storage

### 4.2 Common Limit Categories

| Category | Examples | Default Limits |
|----------|----------|----------------|
| **Apex Limits** | DML operations, CPU time, heap size | 150 DML/transaction, 10s CPU |
| **Platform Limits** | Total code size, API calls, jobs | 6MB code, varies by edition |
| **Flow/Automation** | Share Apex DML/SOQL limits | Same as Apex |

### 4.3 API Call Limits

**Calculation:**
- Two types of API limits (varies by Salesforce edition)
- Composite subrequests count individually against rate limits
- Bulk API has dedicated allocations (separate from REST/SOAP)

**Monitoring:**
- `/services/data/vXX.X/limits` endpoint
- OrgLimits class (Apex)
- Developer Console

### 4.4 Best Practices

**Avoid Common Issues:**
- Mixed DML operations
- Too many SOQL queries in loops
- Too many DML statements
- CPU timeout

**Solutions:**
1. **Efficient Querying:** Bulk processing, minimize queries
2. **Asynchronous Processing:**
   - Queueable Apex
   - Future methods
   - Batch Apex
   - Time-based workflows
3. **Bulk API:** For large data operations (different limits)
4. **Platform Events:** Event-driven architecture
5. **Recursive Guards:** Static flags, "already run" checks in triggers

**Event-Driven vs Polling:**
- **Prefer:** Pub/Sub + Change Data Capture (CDC) for record changes
- **Use:** Platform Events for custom domain events
- **Fallback:** Poll with backoff using `/limits` to adapt frequency
- CDC explicitly designed to avoid repeated API calls

**Resources:**
- Governor Limits: `developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm`

---

## 5. Integration Patterns

### 5.1 API Selection Decision Tree

```
Volume < 2,000 records?
  ├─ YES → REST Composite API (synchronous)
  └─ NO → Volume > 50,000 records?
           ├─ YES → Bulk API 2.0 (asynchronous)
           └─ NO → REST API with pagination

Need real-time notifications?
  ├─ YES → Pub/Sub API + CDC
  └─ NO → Polling with /limits monitoring

Legacy SOAP system?
  ├─ YES → SOAP API + WSDL2Apex
  └─ NO → REST API (preferred)

Multiple related operations?
  ├─ Atomic/transactional? → Composite Graph (allOrNone: true)
  └─ Independent operations? → Composite Batch (25 subrequests)
```

### 5.2 Safe Action Façade Pattern

**Concept:** Expose policy-checked Apex REST endpoints vs raw CRUD

**Benefits:**
- Encapsulate business logic
- Enforce data validation
- Apply security policies
- Prevent invalid state transitions

**Example:**
Instead of direct `POST /sobjects/Lead`, create:
```
POST /services/apexrest/CreateQualifiedLead
```
With Apex logic validating lead quality, duplicate checking, assignment rules, etc.

### 5.3 Transaction Handling

| API | Atomicity | Rollback Behavior |
|-----|-----------|-------------------|
| **Composite sObject Tree** | All-or-nothing | Automatic rollback on error |
| **Apex operations** | Transactional | Platform rollback |
| **Bulk API 2.0** | Job-level | Built-in retry for query jobs |
| **GraphQL** | N/A | Returns HTTP 503 when rate-limited |

---

## 6. Third-Party Integration Tools

### 6.1 Wrapper Libraries

| Library | Language | Features |
|---------|----------|----------|
| **JSforce** | Node.js | Full REST/Bulk/Streaming API support |
| **Restforce** | Ruby | Idiomatic Ruby interface |
| **simple-salesforce** | Python | Used by LangChain/LlamaIndex |

### 6.2 iPaaS & Automation Platforms

| Platform | Type | Integration | Pricing |
|----------|------|-------------|---------|
| **Workato** (Genies) | SaaS iPaaS+agents | Prebuilt connectors | Contact sales |
| **Tray.ai** (Merlin) | Agent builder+iPaaS | Hundreds of connectors | Commercial |
| **Zapier** | Workflow automation | Triggers/actions (CRUD, reports, flows, SOQL) | Commercial tiers |
| **n8n** | Workflow automation | Salesforce node (CRUD, documents) | Free/source-available |

### 6.3 RPA Tools

| Tool | Integration | Key Capabilities |
|------|-------------|------------------|
| **UiPath** | Salesforce activities | Insert/update/SOQL, attended/unattended automation |
| **Automation Anywhere** | AppExchange+REST APIs | Launch bots from Salesforce pages |
| **Robocorp** | RPA Framework library | REST-based robots, Apache license |

---

## 7. Security & Governance

### 7.1 Key Controls

- **Least Privilege:** OAuth scopes at connected/external client apps
- **Data Residency:** Hyperforce local storage (in-country, no relocation)
- **Transaction Security Policies (TSPs):** Real-time event interception for monitoring/blocking
- **Event Monitoring:** `EventLogFile` object via SOAP/REST; "API Total Usage" event type for capacity planning

### 7.2 Monitoring Resources

| Resource | Access Method | Use Case |
|----------|---------------|----------|
| `/limits` endpoint | REST API | Real-time limit consumption |
| `EventLogFile` object | SOAP/REST | Historical usage analysis |
| "API Total Usage" event | Event Monitoring | Capacity planning |

---

## 8. Key Takeaways

### For AI Agents & Automation:

1. **Use Composite APIs** to minimize API call consumption
2. **Prefer event-driven** (Pub/Sub + CDC) over polling for scalability
3. **Monitor `/limits`** before high-cost tasks
4. **Build safe action façades** (Apex REST) vs raw CRUD for policy enforcement
5. **Choose async processing** (Bulk API 2.0) for >2,000 records
6. **Use JWT bearer flow** for server-to-server authentication

### Critical Considerations:

- Composite subrequests count individually against rate limits
- Lead conversion creates up to 3 objects atomically
- Governor limits vary by Salesforce edition
- URL-encode SOQL queries; use correct API object names
- Bulk API has separate allocations from REST/SOAP

### Documentation Gaps:

- API limits may not apply uniformly across all orgs
- Quick reference guides not exhaustive
- Version-specific behavior may vary

---

## 9. References

**Official Documentation:**
- API Library: `developer.salesforce.com/docs/apis`
- REST API Guide: `developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/`
- Object Reference: `developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/`
- Governor Limits: `developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm`

**Community Resources:**
- Trailhead: `trailhead.salesforce.com/content/learn/modules/api_basics`
- GitHub: JWT bearer flow examples
- Stack Exchange: Salesforce community Q&A

---

*Investigation conducted April 4, 2026 | Salesforce API versions current as of Spring '26 Release*
