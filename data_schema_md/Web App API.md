# Web App API Specification

> Markdown version of `Web App API.txt`. The `.txt` file is the source; this copy keeps its content and reformats it for Markdown.

| | |
|---|---|
| **Component** | Web App (front end / system workflow) |
| **Derived from** | `API Spec.txt` (Core API), `Data Schema & Examples.txt`, `Requirements.txt`, `system_overview.png` |
| **Status** | Draft v0.1 |

## 1. Purpose and scope

The Web App is the user-facing part of the system (see `system_overview.png`). It serves the browser over HTTPS and handles six workflows:

- Manual intake (create incidents by hand)
- Incident info (view and edit incidents, tickets and logs)
- Decision, priority (materiality, severity, urgency decisions)
- Queue and claim (team ticket queues, claiming and notifying)
- Dependencies (manage third-party dependency list)
- 8-K view (organize incident info per Form 8-K Item 1.05)

The Web App API is the set of HTTP endpoints the browser calls. It is a "backend-for-frontend" layer. It follows these rules:

- **R-1 No direct database access.** Per the system approach ("Internal API for accessing all services and data"), every read and write goes through the Core API. Each Web App endpoint lists the Core API calls it makes.
- **R-2 Same vocabulary.** Field names, enums and formats are the same as the Core API (`Incident_ID`, `Description`, `Materiality`, `Severity`, `Urgency`, `Ticket_number`, `Team_list`, `dp_name`, ...). Types are referenced from the Core API contract and not redefined (Section 3).
- **R-3 Same error envelope.** Errors use the Core `{Error, Message}` shape. Core errors are passed through unchanged. The Web App adds only a small set of web-only error codes for auth and upstream failures (Section 3.3).
- **R-4 Server-set timestamps.** The Web App fills every Core `Timestamp` field itself in UTC (ISO 8601, `Z` suffix) when it receives the request. Users never type it. This makes "not in the future" true by construction and gives one consistent time zone in the log (AC-02 boundary case). The one exception is the optional discovery time on manual intake (Section 4.1).
- **R-5 Validate early, Core decides.** The Web App checks inputs against the same constraints as the Core API (enum values, Description <= 5000 chars, ID formats, non-empty team lists) so users get fast feedback. The Core API is still the authority. If the Core API rejects a request, its error is returned unchanged.
- **R-6 User actions are logged.** Every state-changing user action (intake, decision, ticket creation/edit, claim) produces a Core ticket or Core notifier record, so it appears in the immutable incident log (REQ-02).
- **R-7 `/reset` is not exposed.** The Core `/reset` path is for testing only and is not reachable through the Web App.

| | |
|---|---|
| **Base path** | `/webapp/v1` |
| **Content type** | `application/json` |
| **Transport** | HTTPS only |
| **Authentication** | TBD (system overview marks Users auth as undecided). Spec uses a session cookie placeholder; see Section 7, gap G-6. |

## 2. Operations summary and Core API mapping

All paths are relative to `/webapp/v1`.

| Web App endpoint | Core API calls (in order) | Requirement |
|---|---|---|
| `POST /incidents` (intake) | [`/dependencies` MATCH] → `/incidents` NEW → `/tickets` NEW (intake audit ticket) | REQ-01, REQ-02, REQ-05 |
| `GET /incidents` (list) | PROPOSED - needs Core list operation (G-5) | REQ-01 |
| `GET /incidents/{Incident_ID}` | `/incidents` GET | REQ-01 |
| `PATCH /incidents/{Incident_ID}` | `/incidents` GET → [`/dependencies` MATCH] → `/incidents` EDIT → `/tickets` NEW (audit) | REQ-01, REQ-02 |
| `PUT /incidents/{Incident_ID}/decision` | `/incidents` GET → `/incidents` EDIT → `/tickets` NEW (decision audit ticket) → [`/notifier` NOTIFY if MATERIAL] | REQ-02, REQ-03, REQ-04 |
| `GET /incidents/{Incident_ID}/tickets` | `/logs` → [`/tickets` GET per ticket] | REQ-02 |
| `POST /incidents/{Incident_ID}/tickets` | `/tickets` NEW → [`/notifier` NOTIFY] | REQ-02, REQ-04 |
| `GET /incidents/{Incident_ID}/tickets/{Ticket_number}` | `/tickets` GET | REQ-02 |
| `PATCH /incidents/{Incident_ID}/tickets/{Ticket_number}` | `/tickets` EDIT (new version) | REQ-02, REQ-03 |
| `POST /tickets/{Ticket_number}/claim` | `/notifier` CLAIM | REQ-04 |
| `POST /tickets/{Ticket_number}/notify` | `/notifier` NOTIFY | REQ-04 |
| `GET /queue` | PROPOSED - needs Core queue query (G-5) | REQ-04 |
| `GET /incidents/{Incident_ID}/log` | `/logs` | REQ-02, REQ-06 |
| `GET /incidents/{Incident_ID}/form-8k` | `/incidents` GET → `/logs` → `/tickets` GET (each) | REQ-06 |
| `POST /dependencies` | `/dependencies` NEW | REQ-05 |
| `GET /dependencies/{dp_name}` | `/dependencies` MATCH | REQ-05 |
| `DELETE /dependencies/{dp_name}` | `/dependencies` REMOVE | REQ-05 |
| `GET /teams` | none - Web App configuration (G-5) | REQ-04 |
| (none) | `/reset` - intentionally not exposed (R-7) | - |

## 3. Types

### 3.1 Types reused from the Core API contract (not redefined)

`Materiality_type`, `Severity_type`, `Urgency_type`, `Error_type`, `Ticket_type_weak`, `Ticket_type_strong`, `Ticket_claim_type`, `Team_type`, `Method_IC_type`, `Method_dp_type`, `Method_note_type`

### 3.2 Web App conventions for those types

| Field | Convention |
|---|---|
| `Incident_ID` | String of digits, e.g. `"102356304331"`. Sent to Core as a string, matching the Core examples. (See G-1.) |
| `Ticket_number` | `Ticket_type_weak`, format `<Incident_ID>_<n>`, regex `^[0-9]+_[0-9]+$`, e.g. `"102356304331_1"` |
| `Ticket_ID` | `Ticket_type_strong`, format `<Incident_ID>_<n>_<version>`, regex `^[0-9]+_[0-9]+_[0-9]+$`, e.g. `"102356304331_1_2"`. `Ticket_number` = `Ticket_ID` with the `_<version>` suffix removed. |
| `Timestamp` | RFC 3339 date-time in UTC, `Z` suffix. |
| `Team_type` | Values come from the Web App team configuration, returned by `GET /webapp/v1/teams`. Any team name not in that list is rejected with `INVALID_DATA`. |

### 3.3 Web App error codes

`WebApp_error_type` = `Error_type` (Core) + `{UNAUTHORIZED, FORBIDDEN, UPSTREAM_UNAVAILABLE}`

| Error | HTTP | Source | Meaning |
|---|---|---|---|
| `UUID_EXISTS` | 400 | Core | Incident_ID already exists |
| `UUID_DNE` | 400 | Core | Incident_ID / ticket does not exist |
| `INVALID_DATA` | 400 | Core/Web | Field fails type, enum or constraint check |
| `DP_EXISTS` | 400 | Core | Dependency already exists |
| `DP_DNE` | 400 | Core | Dependency does not exist |
| `TIMEOUT` | 504 | Core/Web | Core API did not answer in time |
| `UNAUTHORIZED` | 401 | Web | No valid session |
| `FORBIDDEN` | 403 | Web | User's role may not do this action |
| `UPSTREAM_UNAVAILABLE` | 502 | Web | Core API unreachable or gave a non-spec response |

The web-only codes are never sent to the Core API. They only exist between the browser and the Web App.

### 3.4 Multi-step operations

Some endpoints make more than one Core call (e.g. decision = EDIT incident + log decision ticket + notify). The Core API has no transactions. If a later step fails, the Web App returns the error with `Completed_Steps` listing the Core calls that already succeeded, so the user (or a retry) knows the state. Calls are ordered so the record of truth (`/incidents`) is written before the audit ticket and the notification.

## 4. Endpoint details

### 4.1 `POST /webapp/v1/incidents` - Manual intake

**Input:**

| Field | Required | Type / constraints |
|---|---|---|
| `Incident_ID` | Optional | string. If omitted, Web App generates a new unique numeric ID. If given, must not exist. |
| `Description` | Required | string, <= 5000 chars |
| `Dependency_Name` | Optional | string. Must exist (checked via `/dependencies` MATCH) or `DP_DNE` is returned. |
| `Timestamp` | Optional | date-time, discovery time of the incident. Must not be in the future. Default = now (UTC). |
| `Materiality` | Optional | `Materiality_type`, default `UNDECIDED` |
| `Severity` | Optional | `Severity_type`, default `UNDECIDED` |
| `Urgency` | Optional | `Urgency_type`, default `UNDECIDED` |

**Core calls:**

1. `/dependencies` `{dp_name, method: MATCH}` (only if `Dependency_Name`)
2. `/incidents` `{Method: NEW, ...}`
3. `/tickets` `{Method: NEW, Description: "INTAKE: incident created via manual intake by <user>", Team_list: []}`

**Output 200:** Core `/incidents` response fields (`Incident_ID`, Status `"Created"`, `Description`, `Materiality`, `Severity`, `Urgency`) plus `Dependency_Name` and `Intake_Ticket_ID` (`Ticket_type_strong`).

### 4.2 `GET /webapp/v1/incidents` - List incidents [PROPOSED, see G-5]

**Query:** `Materiality`, `Severity`, `Urgency` (optional filters), `page`, `page_size`

**Output 200:** `{ Incidents: [IncidentSummary], page, page_size, total }`

Cannot be built on the current Core API, which has no list operation.

### 4.3 `GET /webapp/v1/incidents/{Incident_ID}` - Incident info

**Core call:** `/incidents` `{Method: GET}`

**Output 200:** Core response passed through (Status `"Data Fetched"`).

### 4.4 `PATCH /webapp/v1/incidents/{Incident_ID}` - Edit incident details

**Input (at least one):** `Description`, `Dependency_Name`

`Materiality`/`Severity`/`Urgency` are NOT accepted here; they change only through `/decision`, so every decision is logged with a reason.

**Core calls:** `/incidents` GET (to fill unchanged fields, since Core EDIT needs the full record) → [`/dependencies` MATCH] → `/incidents` EDIT → `/tickets` NEW (audit ticket `"EDIT: <fields changed> by <user>"`)

**Output 200:** Core `/incidents` response (Status `"Edited"`) + `Audit_Ticket_ID`.

### 4.5 `PUT /webapp/v1/incidents/{Incident_ID}/decision` - Decision and priority

**Input:**

| Field | Required | Type / constraints |
|---|---|---|
| `Materiality` | Optional | `Materiality_type` |
| `Severity` | Optional | `Severity_type` |
| `Urgency` | Optional | `Urgency_type` |
| `Rationale` | Required | string, <= 4000 chars (leaves room inside the 5000-char ticket Description for the header) |

At least one of `Materiality` / `Severity` / `Urgency` is required.

**Core calls:**

1. `/incidents` GET
2. `/incidents` EDIT with the new values (others unchanged)
3. `/tickets` NEW, Description = `"DECISION by <user>: Materiality=<..>; Severity=<..>; Urgency=<..>. Rationale: <..>"`, `Ticket_severity` / `Ticket_urgency` = the new values
4. If `Materiality` changed to `MATERIAL`: `/notifier` NOTIFY with `Team_Names` = all configured teams, `Ticket_Number` = decision ticket.

**Output 200:** `Incident_ID`, Status `"Decision Recorded"`, `Materiality`, `Severity`, `Urgency`, `Decision_Ticket_ID`, `Determined_At` (Timestamp of step 3), `Notified_Teams` (list, empty if no notify), `Filing_Deadline` (date-time or null; see G-8)

**Notes:**

- Materiality is stored at the incident level, as the Core schema does (see G-11). The decision ticket is the immutable record of who decided, when, and why (REQ-02, REQ-03).
- `Determined_At` starts the 4-business-day Form 8-K clock (REQ-04).

### 4.6 `GET /webapp/v1/incidents/{Incident_ID}/tickets` - List an incident's tickets

**Query:** `expand` (boolean, default false)

**Core calls:** `/logs` → if expand: `/tickets` GET once per unique `Ticket_number`

**Output 200:** `Incident_ID`, `Ticket_ID_List` (strong ids), `Tickets` (only if expand)

### 4.7 `POST /webapp/v1/incidents/{Incident_ID}/tickets` - Create ticket

**Input:**

| Field | Required | Type / constraints |
|---|---|---|
| `Description` | Required | string, <= 5000 chars |
| `Ticket_severity` | Optional | `Severity_type` |
| `Ticket_urgency` | Optional | `Urgency_type` |
| `Team_list` | Optional | list of `Team_type` |
| `Notify` | Optional | boolean, default true. If true and `Team_list` is not empty, notifies those teams. |

**Core calls:** `/tickets` NEW → [`/notifier` NOTIFY]

**Output 200:** Core `/tickets` response (Status `"Logged"`) + `Notified_Teams`.

### 4.8 `GET /webapp/v1/incidents/{Incident_ID}/tickets/{Ticket_number}`

**Core call:** `/tickets` `{Method: GET, Ticket_number}`

**Output 200:** Core response passed through (Status `"Displayed"`).

Web App also checks that `Ticket_number` starts with `"<Incident_ID>_"`, otherwise `INVALID_DATA`.

### 4.9 `PATCH /webapp/v1/incidents/{Incident_ID}/tickets/{Ticket_number}` - Edit ticket

**Input:** `Description` (Required by Core for EDIT), `Ticket_severity`, `Ticket_urgency`, `Team_list`

**Core call:** `/tickets` `{Method: EDIT, Ticket_number, ...}` (see G-4)

**Output 200:** Core response. `Ticket_ID` has a new version number; the old version stays in the log.

### 4.10 `POST /webapp/v1/tickets/{Ticket_number}/claim` - Claim ticket

**Input:** `Team_Name` - Required, `Team_type` (exactly one team; REQ-04 says one team claims)

**Core call:** `/notifier` `{Method: CLAIM, Team_Names: [Team_Name], Ticket_Number}`

**Output 200:** Core response passed through (Status `"Claimed ticket"`).

The user must belong to `Team_Name`, otherwise `FORBIDDEN`.

### 4.11 `POST /webapp/v1/tickets/{Ticket_number}/notify` - Notify teams

**Input:** `Team_Names` - Required, non-empty list of `Team_type`

**Core call:** `/notifier` `{Method: NOTIFY, Team_Names, Ticket_Number}`

**Output 200:** Core response passed through (Status `"Notified team"`).

### 4.12 `GET /webapp/v1/queue` - Team queue [PROPOSED, see G-5]

**Query:** `team` (Required, `Team_type`), `claim` (`Ticket_claim_type`, default `UNCLAIMED`)

**Output 200:** `{ Team, Tickets: [QueueItem] }` where `QueueItem` has `Ticket_number`, `Incident_ID`, `Ticket_Description`, `ticket_severity`, `ticket_urgency`, `Ticket_Claim`, `Notified_At`, `Filing_Deadline`

Cannot be built on the current Core API without a query by team / claim.

### 4.13 `GET /webapp/v1/incidents/{Incident_ID}/log` - Incident log

**Core call:** `/logs` `{Incident_ID, Timestamp: now}`

**Output 200:** Core response passed through (Status `"Log Retrieved"`). `Ticket_ID_List` is normalized to one id per array element (see G-9).

### 4.14 `GET /webapp/v1/incidents/{Incident_ID}/form-8k` - 8-K view

**Core calls:** `/incidents` GET → `/logs` → `/tickets` GET for each `Ticket_number`

**Rule:** if `Materiality` is not `MATERIAL`, return 400 `INVALID_DATA` "Form 8-K view is only available for incidents marked MATERIAL." (AC-06 boundary case)

**Output 200:** Incident data grouped by the parts of Form 8-K Item 1.05:

- `Item_1_05`:
  - `Nature` - incident Description + ticket descriptions
  - `Scope` - Severity, Dependency_Name, Team_List involved
  - `Timing` - discovery Timestamp, Determined_At, ticket timestamps in order
  - `Material_Impact` - Rationale text from decision ticket(s)
- `Filing`: `Determined_At`, `Filing_Deadline` (4 business days; see G-8)
- `Source_Tickets`: list of Ticket_IDs used, so each fact can be traced

This is a read-only summary to help fill the form. It does not file or auto-complete Form 8-K (REQ-06).

### 4.15 Dependencies - `/webapp/v1/dependencies`

| Endpoint | Body | Core call | Status |
|---|---|---|---|
| `POST /dependencies` | `{dp_name}` | `/dependencies` NEW | `"Added"` |
| `GET /dependencies/{dp_name}` | - | `/dependencies` MATCH | `"Exists"` / `"Does not Exist"` |
| `DELETE /dependencies/{dp_name}` | - | `/dependencies` REMOVE | `"Removed"` |

**Output:** Core response passed through. A list of all dependencies is PROPOSED (G-5).

### 4.16 `GET /webapp/v1/teams` - Configured teams

No Core call. Returns the `Team_type` values from the Web App configuration, used to fill team pickers and validate `Team_list` / `Team_Names`.

**Output 200:** `{ Teams: ["LEGAL", "CYBER1", "CYBER2"] }`

## 5. HTTP structured spec (OpenAPI)

```yaml
openapi: 3.0.3
info:
  title: SEC-Check Web App API
  version: 0.1.0
  description: >
    Browser-facing API for the Web App component. Every operation is carried out
    through the Core API ("Incident and Dependency Platform Cross-Team Testing
    API"). Field names, enums and error envelope match the Core API.
servers:
  - url: /webapp/v1
security:
  - sessionCookie: []
paths:
  /incidents:
    post:
      summary: Manual intake
      description: "Core: [/dependencies MATCH] -> /incidents NEW -> /tickets NEW (intake audit ticket). REQ-01, REQ-02, REQ-05."
      operationId: createIncident
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/IncidentCreateRequest'
      responses:
        '200':
          description: Incident created.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/IncidentCreateResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'
        '401':
          $ref: '#/components/responses/ErrorResponse'
        '502':
          $ref: '#/components/responses/ErrorResponse'
        '504':
          $ref: '#/components/responses/ErrorResponse'
    get:
      summary: List incidents (PROPOSED - requires Core list operation)
      operationId: listIncidents
      parameters:
        - name: Materiality
          in: query
          schema:
            $ref: '#/components/schemas/Materiality_type'
        - name: Severity
          in: query
          schema:
            $ref: '#/components/schemas/Severity_type'
        - name: Urgency
          in: query
          schema:
            $ref: '#/components/schemas/Urgency_type'
        - name: page
          in: query
          schema:
            type: integer
            minimum: 1
            default: 1
        - name: page_size
          in: query
          schema:
            type: integer
            minimum: 1
            maximum: 100
            default: 25
      responses:
        '200':
          description: Page of incidents.
          content:
            application/json:
              schema:
                type: object
                properties:
                  Incidents:
                    type: array
                    items:
                      $ref: '#/components/schemas/Incident'
                  page:
                    type: integer
                  page_size:
                    type: integer
                  total:
                    type: integer
        '401':
          $ref: '#/components/responses/ErrorResponse'

  /incidents/{Incident_ID}:
    parameters:
      - $ref: '#/components/parameters/Incident_ID'
    get:
      summary: Incident info
      description: "Core: /incidents GET. REQ-01."
      operationId: getIncident
      responses:
        '200':
          description: Incident data fetched.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Incident'
        '400':
          $ref: '#/components/responses/ErrorResponse'
        '401':
          $ref: '#/components/responses/ErrorResponse'
    patch:
      summary: Edit incident details (not decision fields)
      description: "Core: /incidents GET -> [/dependencies MATCH] -> /incidents EDIT -> /tickets NEW (audit). REQ-01, REQ-02."
      operationId: editIncident
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              minProperties: 1
              additionalProperties: false
              properties:
                Description:
                  type: string
                  maxLength: 5000
                Dependency_Name:
                  type: string
      responses:
        '200':
          description: Incident edited.
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/Incident'
                  - type: object
                    properties:
                      Audit_Ticket_ID:
                        $ref: '#/components/schemas/Ticket_type_strong'
        '400':
          $ref: '#/components/responses/ErrorResponse'
        '401':
          $ref: '#/components/responses/ErrorResponse'

  /incidents/{Incident_ID}/decision:
    parameters:
      - $ref: '#/components/parameters/Incident_ID'
    put:
      summary: Record materiality / severity / urgency decision
      description: "Core: /incidents GET -> /incidents EDIT -> /tickets NEW (decision ticket) -> [/notifier NOTIFY all teams if MATERIAL]. REQ-02, REQ-03, REQ-04."
      operationId: recordDecision
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DecisionRequest'
      responses:
        '200':
          description: Decision recorded.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DecisionResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'
        '401':
          $ref: '#/components/responses/ErrorResponse'
        '403':
          $ref: '#/components/responses/ErrorResponse'

  /incidents/{Incident_ID}/tickets:
    parameters:
      - $ref: '#/components/parameters/Incident_ID'
    get:
      summary: List tickets for an incident
      description: "Core: /logs -> [/tickets GET per ticket if expand=true]. REQ-02."
      operationId: listIncidentTickets
      parameters:
        - name: expand
          in: query
          schema:
            type: boolean
            default: false
      responses:
        '200':
          description: Tickets listed.
          content:
            application/json:
              schema:
                type: object
                properties:
                  Incident_ID:
                    type: string
                  Ticket_ID_List:
                    type: array
                    items:
                      $ref: '#/components/schemas/Ticket_type_strong'
                  Tickets:
                    type: array
                    items:
                      $ref: '#/components/schemas/Ticket'
        '400':
          $ref: '#/components/responses/ErrorResponse'
    post:
      summary: Create ticket
      description: "Core: /tickets NEW -> [/notifier NOTIFY Team_list]. REQ-02, REQ-04."
      operationId: createTicket
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TicketCreateRequest'
      responses:
        '200':
          description: Ticket logged.
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/Ticket'
                  - type: object
                    properties:
                      Notified_Teams:
                        type: array
                        items:
                          type: string
        '400':
          $ref: '#/components/responses/ErrorResponse'
        '401':
          $ref: '#/components/responses/ErrorResponse'

  /incidents/{Incident_ID}/tickets/{Ticket_number}:
    parameters:
      - $ref: '#/components/parameters/Incident_ID'
      - $ref: '#/components/parameters/Ticket_number'
    get:
      summary: Get ticket
      description: "Core: /tickets GET. REQ-02."
      operationId: getTicket
      responses:
        '200':
          description: Ticket displayed.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Ticket'
        '400':
          $ref: '#/components/responses/ErrorResponse'
    patch:
      summary: Edit ticket (creates a new version)
      description: "Core: /tickets EDIT. Old version remains in log. REQ-02, REQ-03."
      operationId: editTicket
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - Description
              additionalProperties: false
              properties:
                Description:
                  type: string
                  maxLength: 5000
                Ticket_severity:
                  $ref: '#/components/schemas/Severity_type'
                Ticket_urgency:
                  $ref: '#/components/schemas/Urgency_type'
                Team_list:
                  type: array
                  items:
                    type: string
      responses:
        '200':
          description: Ticket edited; new Ticket_ID version returned.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Ticket'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /tickets/{Ticket_number}/claim:
    parameters:
      - $ref: '#/components/parameters/Ticket_number'
    post:
      summary: Claim a ticket for one team
      description: "Core: /notifier CLAIM with Team_Names = [Team_Name]. REQ-04."
      operationId: claimTicket
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - Team_Name
              additionalProperties: false
              properties:
                Team_Name:
                  type: string
                  description: Team_type; user must be a member.
      responses:
        '200':
          description: Ticket claimed.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotifierResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'
        '403':
          $ref: '#/components/responses/ErrorResponse'

  /tickets/{Ticket_number}/notify:
    parameters:
      - $ref: '#/components/parameters/Ticket_number'
    post:
      summary: Notify teams about a ticket
      description: "Core: /notifier NOTIFY. REQ-04."
      operationId: notifyTeams
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - Team_Names
              additionalProperties: false
              properties:
                Team_Names:
                  type: array
                  minItems: 1
                  items:
                    type: string
      responses:
        '200':
          description: Teams notified.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotifierResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /queue:
    get:
      summary: Team ticket queue (PROPOSED - requires Core queue query)
      operationId: getQueue
      parameters:
        - name: team
          in: query
          required: true
          schema:
            type: string
        - name: claim
          in: query
          schema:
            $ref: '#/components/schemas/Ticket_claim_type'
      responses:
        '200':
          description: Queue for the team.
          content:
            application/json:
              schema:
                type: object
                properties:
                  Team:
                    type: string
                  Tickets:
                    type: array
                    items:
                      $ref: '#/components/schemas/QueueItem'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /incidents/{Incident_ID}/log:
    parameters:
      - $ref: '#/components/parameters/Incident_ID'
    get:
      summary: Incident log
      description: "Core: /logs (Timestamp set by Web App). REQ-02, REQ-06."
      operationId: getIncidentLog
      responses:
        '200':
          description: Log retrieved.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LogResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /incidents/{Incident_ID}/form-8k:
    parameters:
      - $ref: '#/components/parameters/Incident_ID'
    get:
      summary: Form 8-K Item 1.05 view (MATERIAL incidents only)
      description: "Core: /incidents GET -> /logs -> /tickets GET per ticket. Returns INVALID_DATA if not MATERIAL. REQ-06, AC-06."
      operationId: getForm8kView
      responses:
        '200':
          description: 8-K view assembled.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Form8kView'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /dependencies:
    post:
      summary: Add dependency
      description: "Core: /dependencies NEW. REQ-05."
      operationId: addDependency
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - dp_name
              additionalProperties: false
              properties:
                dp_name:
                  type: string
      responses:
        '200':
          description: Dependency added.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DependencyResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /dependencies/{dp_name}:
    parameters:
      - name: dp_name
        in: path
        required: true
        schema:
          type: string
    get:
      summary: Check whether a dependency exists
      description: "Core: /dependencies MATCH. REQ-05."
      operationId: matchDependency
      responses:
        '200':
          description: Match result ("Exists" or "Does not Exist").
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DependencyResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'
    delete:
      summary: Remove dependency
      description: "Core: /dependencies REMOVE. REQ-05."
      operationId: removeDependency
      responses:
        '200':
          description: Dependency removed.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DependencyResponse'
        '400':
          $ref: '#/components/responses/ErrorResponse'

  /teams:
    get:
      summary: Configured teams
      description: "No Core call. Returns Team_type values from Web App configuration."
      operationId: listTeams
      responses:
        '200':
          description: Team list.
          content:
            application/json:
              schema:
                type: object
                properties:
                  Teams:
                    type: array
                    items:
                      type: string

components:
  securitySchemes:
    sessionCookie:
      type: apiKey
      in: cookie
      name: secheck_session
      description: Placeholder. User authentication method is TBD in the system design.

  parameters:
    Incident_ID:
      name: Incident_ID
      in: path
      required: true
      schema:
        type: string
        pattern: '^[0-9]+$'
    Ticket_number:
      name: Ticket_number
      in: path
      required: true
      schema:
        $ref: '#/components/schemas/Ticket_type_weak'

  schemas:
    Materiality_type:
      type: string
      enum: [MATERIAL, IMMATERIAL, UNDECIDED]
    Severity_type:
      type: string
      enum: [HIGH, MEDIUM, LOW, UNDECIDED, RESOLVED]
    Urgency_type:
      type: string
      enum: [URGENT, NOT_URGENT, UNDECIDED, RESOLVED]
    Ticket_claim_type:
      type: string
      enum: [CLAIMED, UNCLAIMED]
    Ticket_type_weak:
      type: string
      pattern: '^[0-9]+_[0-9]+$'
    Ticket_type_strong:
      type: string
      pattern: '^[0-9]+_[0-9]+_[0-9]+$'
    WebApp_error_type:
      type: string
      enum: [UUID_EXISTS, UUID_DNE, INVALID_DATA, DP_EXISTS, DP_DNE, TIMEOUT, UNAUTHORIZED, FORBIDDEN, UPSTREAM_UNAVAILABLE]

    IncidentCreateRequest:
      type: object
      required:
        - Description
      additionalProperties: false
      properties:
        Incident_ID:
          type: string
          pattern: '^[0-9]+$'
          description: Optional. Generated by Web App if omitted. Must not already exist.
        Description:
          type: string
          maxLength: 5000
        Dependency_Name:
          type: string
        Timestamp:
          type: string
          format: date-time
          description: Discovery time. Must not be in the future. Default now (UTC).
        Materiality:
          $ref: '#/components/schemas/Materiality_type'
        Severity:
          $ref: '#/components/schemas/Severity_type'
        Urgency:
          $ref: '#/components/schemas/Urgency_type'

    Incident:
      type: object
      properties:
        Incident_ID:
          type: string
        Status:
          type: string
          example: Data Fetched
        Description:
          type: string
        Dependency_Name:
          type: string
        Materiality:
          $ref: '#/components/schemas/Materiality_type'
        Severity:
          $ref: '#/components/schemas/Severity_type'
        Urgency:
          $ref: '#/components/schemas/Urgency_type'

    IncidentCreateResponse:
      allOf:
        - $ref: '#/components/schemas/Incident'
        - type: object
          properties:
            Intake_Ticket_ID:
              $ref: '#/components/schemas/Ticket_type_strong'

    DecisionRequest:
      type: object
      required:
        - Rationale
      additionalProperties: false
      minProperties: 2
      properties:
        Materiality:
          $ref: '#/components/schemas/Materiality_type'
        Severity:
          $ref: '#/components/schemas/Severity_type'
        Urgency:
          $ref: '#/components/schemas/Urgency_type'
        Rationale:
          type: string
          minLength: 1
          maxLength: 4000

    DecisionResponse:
      type: object
      properties:
        Incident_ID:
          type: string
        Status:
          type: string
          example: Decision Recorded
        Materiality:
          $ref: '#/components/schemas/Materiality_type'
        Severity:
          $ref: '#/components/schemas/Severity_type'
        Urgency:
          $ref: '#/components/schemas/Urgency_type'
        Decision_Ticket_ID:
          $ref: '#/components/schemas/Ticket_type_strong'
        Determined_At:
          type: string
          format: date-time
        Notified_Teams:
          type: array
          items:
            type: string
        Filing_Deadline:
          type: string
          format: date-time
          nullable: true

    TicketCreateRequest:
      type: object
      required:
        - Description
      additionalProperties: false
      properties:
        Description:
          type: string
          maxLength: 5000
        Ticket_severity:
          $ref: '#/components/schemas/Severity_type'
        Ticket_urgency:
          $ref: '#/components/schemas/Urgency_type'
        Team_list:
          type: array
          items:
            type: string
        Notify:
          type: boolean
          default: true

    Ticket:
      type: object
      description: Same fields as the Core /tickets response.
      properties:
        Incident_ID:
          type: string
        Ticket_ID:
          $ref: '#/components/schemas/Ticket_type_strong'
        Status:
          type: string
          example: Displayed
        UUID_Description:
          type: string
        Ticket_Description:
          type: string
        Materiality_type:
          $ref: '#/components/schemas/Materiality_type'
        uuid_severity:
          $ref: '#/components/schemas/Severity_type'
        uuid_urgency:
          $ref: '#/components/schemas/Urgency_type'
        ticket_severity:
          $ref: '#/components/schemas/Severity_type'
        ticket_urgency:
          $ref: '#/components/schemas/Urgency_type'
        Ticket_Claim:
          $ref: '#/components/schemas/Ticket_claim_type'
        Team_List:
          type: array
          items:
            type: string

    NotifierResponse:
      type: object
      description: Same fields as the Core /notifier response.
      properties:
        UUID:
          type: string
        Ticket_Number:
          $ref: '#/components/schemas/Ticket_type_weak'
        Status:
          type: string
          example: Claimed ticket

    QueueItem:
      type: object
      properties:
        Ticket_number:
          $ref: '#/components/schemas/Ticket_type_weak'
        Incident_ID:
          type: string
        Ticket_Description:
          type: string
        ticket_severity:
          $ref: '#/components/schemas/Severity_type'
        ticket_urgency:
          $ref: '#/components/schemas/Urgency_type'
        Ticket_Claim:
          $ref: '#/components/schemas/Ticket_claim_type'
        Notified_At:
          type: string
          format: date-time
        Filing_Deadline:
          type: string
          format: date-time
          nullable: true

    LogResponse:
      type: object
      description: Same fields as the Core /logs response.
      properties:
        Incident_ID:
          type: string
        Description:
          type: string
        Materiality_type:
          $ref: '#/components/schemas/Materiality_type'
        Severity:
          $ref: '#/components/schemas/Severity_type'
        Urgency:
          $ref: '#/components/schemas/Urgency_type'
        Ticket_ID_List:
          type: array
          items:
            $ref: '#/components/schemas/Ticket_type_strong'
        Status:
          type: string
          example: Log Retrieved

    Form8kView:
      type: object
      properties:
        Incident_ID:
          type: string
        Status:
          type: string
          example: 8-K View Assembled
        Item_1_05:
          type: object
          properties:
            Nature:
              type: string
            Scope:
              type: object
              properties:
                Severity:
                  $ref: '#/components/schemas/Severity_type'
                Dependency_Name:
                  type: string
                Teams_Involved:
                  type: array
                  items:
                    type: string
            Timing:
              type: object
              properties:
                Discovered_At:
                  type: string
                  format: date-time
                Determined_At:
                  type: string
                  format: date-time
                Events:
                  type: array
                  items:
                    type: object
                    properties:
                      Ticket_ID:
                        $ref: '#/components/schemas/Ticket_type_strong'
                      Timestamp:
                        type: string
                        format: date-time
                      Summary:
                        type: string
            Material_Impact:
              type: string
        Filing:
          type: object
          properties:
            Determined_At:
              type: string
              format: date-time
            Filing_Deadline:
              type: string
              format: date-time
              nullable: true
        Source_Tickets:
          type: array
          items:
            $ref: '#/components/schemas/Ticket_type_strong'

    DependencyResponse:
      type: object
      description: Same fields as the Core /dependencies response.
      properties:
        dp_name:
          type: string
        status:
          type: string
          example: Added

  responses:
    ErrorResponse:
      description: Same {Error, Message} envelope as the Core API, with optional Web App extras.
      content:
        application/json:
          schema:
            type: object
            required:
              - Error
              - Message
            properties:
              Error:
                $ref: '#/components/schemas/WebApp_error_type'
              Message:
                type: string
              Core_Path:
                type: string
                description: Core API path that produced the error, if any.
              Completed_Steps:
                type: array
                description: Core calls that already succeeded in a multi-step operation.
                items:
                  type: string
```

## 6. Examples (one valid and one invalid per core workflow)

### 6.1 `POST /webapp/v1/incidents`

**Input OK:**

```json
{
  "Incident_ID": "102356304331",
  "Description": "Critical API gateway timeout linked to third-party auth provider.",
  "Dependency_Name": "auth-service-v2",
  "Timestamp": "2026-09-25T20:00:00Z",
  "Severity": "HIGH",
  "Urgency": "URGENT"
}
```

**Core calls made:**

```text
  /dependencies {"dp_name": "auth-service-v2", "method": "MATCH"}             -> "Exists"
  /incidents    {"Incident_ID": "102356304331", "Method": "NEW",
                 "Timestamp": "2026-09-25T20:00:00Z", "Description": "...",
                 "Dependency": "auth-service-v2", "Materiality": "UNDECIDED",
                 "Severity": "HIGH", "Urgency": "URGENT"}                       -> "Created"
  /tickets      {"Incident_ID": "102356304331", "Method": "NEW",
                 "Timestamp": "2026-10-13T18:05:00Z",
                 "Description": "INTAKE: incident created via manual intake by jdoe",
                 "Team_list": []}                                               -> "Logged"
```

**Output 200 OK:**

```json
{
  "Incident_ID": "102356304331",
  "Status": "Created",
  "Description": "Critical API gateway timeout linked to third-party auth provider.",
  "Dependency_Name": "auth-service-v2",
  "Materiality": "UNDECIDED",
  "Severity": "HIGH",
  "Urgency": "URGENT",
  "Intake_Ticket_ID": "102356304331_1_1"
}
```

**Input Bad:** (dependency not registered)

```json
{
  "Description": "Suspicious outbound traffic from payroll host.",
  "Dependency_Name": "payroll-saas"
}
```

**Output 400 Bad Request:**

```json
{
  "Error": "DP_DNE",
  "Message": "The dependency name does not exist in the system.",
  "Core_Path": "/dependencies",
  "Completed_Steps": []
}
```

### 6.2 `PUT /webapp/v1/incidents/102356304331/decision`

**Input OK:**

```json
{
  "Materiality": "MATERIAL",
  "Severity": "HIGH",
  "Urgency": "URGENT",
  "Rationale": "Customer authentication unavailable for 6 hours; revenue impact expected to exceed internal threshold."
}
```

**Output 200 OK:**

```json
{
  "Incident_ID": "102356304331",
  "Status": "Decision Recorded",
  "Materiality": "MATERIAL",
  "Severity": "HIGH",
  "Urgency": "URGENT",
  "Decision_Ticket_ID": "102356304331_2_1",
  "Determined_At": "2026-10-13T18:20:00Z",
  "Notified_Teams": ["LEGAL", "CYBER1", "CYBER2"],
  "Filing_Deadline": null
}
```

**Input Bad:** (no decision field, only rationale)

```json
{
  "Rationale": "Reviewed."
}
```

**Output 400 Bad Request:**

```json
{
  "Error": "INVALID_DATA",
  "Message": "At least one of Materiality, Severity or Urgency is required."
}
```

### 6.3 `POST /webapp/v1/incidents/102356304331/tickets`

**Input OK:**

```json
{
  "Description": "Initial triage ticket logged for authentication failure.",
  "Ticket_severity": "HIGH",
  "Ticket_urgency": "URGENT",
  "Team_list": ["CYBER1", "LEGAL"]
}
```

**Output 200 OK:**

```json
{
  "Incident_ID": "102356304331",
  "Ticket_ID": "102356304331_3_1",
  "Status": "Logged",
  "UUID_Description": "Critical API gateway timeout linked to third-party auth provider.",
  "Ticket_Description": "Initial triage ticket logged for authentication failure.",
  "Materiality_type": "MATERIAL",
  "uuid_severity": "HIGH",
  "uuid_urgency": "URGENT",
  "ticket_severity": "HIGH",
  "ticket_urgency": "URGENT",
  "Team_List": ["CYBER1", "LEGAL"],
  "Notified_Teams": ["CYBER1", "LEGAL"]
}
```

**Input Bad:** (team not configured)

```json
{
  "Description": "Forward to marketing.",
  "Team_list": ["MARKETING"]
}
```

**Output 400 Bad Request:**

```json
{
  "Error": "INVALID_DATA",
  "Message": "Team_list contains unknown team: MARKETING."
}
```

### 6.4 `POST /webapp/v1/tickets/102356304331_3/claim`

**Input OK:**

```json
{
  "Team_Name": "CYBER1"
}
```

**Output 200 OK:**

```json
{
  "UUID": "102356304331",
  "Ticket_Number": "102356304331_3",
  "Status": "Claimed ticket"
}
```

**Input Bad:** (user is not a member of LEGAL)

```json
{
  "Team_Name": "LEGAL"
}
```

**Output 403 Forbidden:**

```json
{
  "Error": "FORBIDDEN",
  "Message": "You are not a member of team LEGAL."
}
```

### 6.5 `GET /webapp/v1/incidents/102356304331/log`

**Output 200 OK:**

```json
{
  "Incident_ID": "102356304331",
  "Description": "Critical API gateway timeout linked to third-party auth provider.",
  "Materiality_type": "MATERIAL",
  "Severity": "HIGH",
  "Urgency": "URGENT",
  "Ticket_ID_List": ["102356304331_1_1", "102356304331_2_1", "102356304331_3_1"],
  "Status": "Log Retrieved"
}
```

**Bad:** `GET /webapp/v1/incidents/000000000001/log`

**Output 400 Bad Request:**

```json
{
  "Error": "UUID_DNE",
  "Message": "The specified Incident_ID does not exist.",
  "Core_Path": "/logs"
}
```

### 6.6 `GET /webapp/v1/incidents/102356304331/form-8k`

**Output 200 OK:**

```json
{
  "Incident_ID": "102356304331",
  "Status": "8-K View Assembled",
  "Item_1_05": {
    "Nature": "Critical API gateway timeout linked to third-party auth provider. Initial triage ticket logged for authentication failure.",
    "Scope": {
      "Severity": "HIGH",
      "Dependency_Name": "auth-service-v2",
      "Teams_Involved": ["CYBER1", "LEGAL"]
    },
    "Timing": {
      "Discovered_At": "2026-09-25T20:00:00Z",
      "Determined_At": "2026-10-13T18:20:00Z",
      "Events": [
        {"Ticket_ID": "102356304331_1_1", "Timestamp": "2026-10-13T18:05:00Z", "Summary": "INTAKE: incident created via manual intake by jdoe"},
        {"Ticket_ID": "102356304331_2_1", "Timestamp": "2026-10-13T18:20:00Z", "Summary": "DECISION by jdoe: Materiality=MATERIAL; Severity=HIGH; Urgency=URGENT"}
      ]
    },
    "Material_Impact": "Customer authentication unavailable for 6 hours; revenue impact expected to exceed internal threshold."
  },
  "Filing": {
    "Determined_At": "2026-10-13T18:20:00Z",
    "Filing_Deadline": null
  },
  "Source_Tickets": ["102356304331_1_1", "102356304331_2_1", "102356304331_3_1"]
}
```

**Bad:** `GET /webapp/v1/incidents/188948234932/form-8k`  (incident is IMMATERIAL)

**Output 400 Bad Request:**

```json
{
  "Error": "INVALID_DATA",
  "Message": "Form 8-K view is only available for incidents marked MATERIAL."
}
```

### 6.7 `POST /webapp/v1/dependencies`

**Input OK:**

```json
{
  "dp_name": "auth-service-v2"
}
```

**Output 200 OK:**

```json
{
  "dp_name": "auth-service-v2",
  "status": "Added"
}
```

**Input Bad:** (already added)

```json
{
  "dp_name": "auth-service-v2"
}
```

**Output 400 Bad Request:**

```json
{
  "Error": "DP_EXISTS",
  "Message": "The dependency name already exists in the system.",
  "Core_Path": "/dependencies"
}
```

## 7. Gaps and questions for the Core API owner

These are places where the Core API spec, data schema or examples disagree, or where the Web App needs something the Core API does not yet provide. The Web App API above uses the stated workaround until each is settled.

**G-1 Incident_ID type.** OpenAPI says "string, format uuid"; the data schema says "Integer"; the examples use 12-digit numeric strings. Workaround: Web App treats it as a digit-only string. Decision needed on one type.

**G-2 Path spelling.** Operations list says `/dependancies`; OpenAPI says `/dependencies`. Web App calls `/dependencies`.

**G-3 Field mismatches.** `/incidents` uses `Dependency` in OpenAPI but `Dependency_Name` in the data schema (and the `Dependency` line in the OpenAPI block is mis-indented). `Ticket_Claim` is in the data schema for `/tickets` but missing from the OpenAPI. Web App uses `Dependency_Name` externally and maps it to `Dependency` when calling Core.

**G-4 `/tickets` EDIT.** `Ticket_number` is only required for GET, so an EDIT cannot say which ticket to edit, and no EDIT Status string is defined. Workaround: Web App always sends `Ticket_number` on EDIT. Proposed Status: `"Edited"`.

**G-5 Missing list/query operations.** The Web App needs these for its main screens but the Core API has none:

| Needed | Used by |
|---|---|
| list incidents (with filters) | `GET /webapp/v1/incidents` |
| tickets by team and claim state | `GET /webapp/v1/queue` |
| list all dependencies | dependency screen |
| list configured teams | `GET /webapp/v1/teams` |

Teams are in the database (system overview) but have no Core path. Proposed: a Core `/query` path, or Method `LIST` on the existing paths.

**G-6 No actor field.** REQ-02 requires logging user actions, but no Core request carries who did the action. Workaround: Web App writes "by <user>" into the audit ticket Description (uses part of the 5000-char limit). Proposed: optional `Actor` field on all Core write requests. Also: user authentication method is still TBD.

**G-7 Ticket versions.** `/logs` returns strong ids (with version) but `/tickets` GET only accepts weak ids, so older versions cannot be viewed. Proposed: allow `Ticket_type_strong` in `/tickets` GET.

**G-8 Deadlines.** The Deadline scheduler (4 business days) reports only to the Core API, and no Core response includes a deadline or due/overdue state. Workaround: `Filing_Deadline` is returned as null. Proposed: add `Filing_Deadline` / `Deadline_Status` to `/incidents` GET and `/tickets` GET.

**G-9 Format inconsistencies in examples:**

- `Ticket_type_weak` is defined as UUID + '' + number, but examples use "_" between them. Web App uses "_".
- The `/logs` example `Ticket_ID_List` is one comma-joined string, not a list. Web App splits it into separate ids if received that way.
- `/notifier` response `UUID` is an integer, unlike `Incident_ID` elsewhere. Web App returns it as a string.
- Some `/tickets` examples are missing the opening quote on `Incident_ID`.

**G-10** `/incidents` requires `Description` for every Method, including GET. Web App sends an empty string on GET. Proposed: required only for NEW and EDIT.

**G-11 Materiality level.** REQ-03 says tickets are marked material/immaterial, but the Core schema only stores Materiality on the incident. Web App records the decision on the incident and logs it with a decision ticket. Confirm this is the intended model.

**G-12 Notifier records.** `/notifier` responses have no timestamp, so the Web App cannot show when a team was notified or claimed (needed for AC-04 audit ordering). Proposed: add `Timestamp` to the `/notifier` response.
