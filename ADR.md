# Architecture Decision Records

## 1. Backend Framework: Flask over Django/FastAPI
Date: 2026-09-28  
Status: Decided

**Context**: Need a Python web framework for a monolithic application with two distinct domains (envelope budgeting and bill tracking), RESTful API endpoints, and simple HTML templates. The app must run as a single process.

**Decision**: Use Flask as the backend framework.

**Alternatives considered**:
- **Django**: Provides ORM, admin panel, and batteries-included approach. Rejected because it's over-engineered for this use case. We don't need Django's ORM (SQLite with raw SQL is simpler), admin panel (we have custom UI), or complex auth system. Too heavy for a simple monolithic app.
- **FastAPI**: Modern async framework with automatic API documentation. Rejected because we don't need async capabilities (no real-time features, no high-concurrency requirements), and Flask's template rendering is simpler for our mixed API + HTML needs.

**Consequences**: 
- **Positive**: Flask is lightweight, minimal learning curve, provides exactly what we need (routing, templates, JSON responses) without unnecessary complexity. Easy to test and deploy as a single process. Good for assignments and prototypes.
- **Negative**: No built-in ORM (mitigated: raw SQL is fine for this scale), no automatic API docs (mitigated: API is simple and documented in README). More manual configuration needed.

---

## 2. Domain Separation: Independent Budget and Bill Modules
Date: 2026-09-29  
Status: Decided

**Context**: Assignment requires two distinct feature domains that could potentially become microservices. The envelope budgeting and bill tracking features have different responsibilities and data models.

**Decision**: Implement Budget Envelope Manager and Bill Manager as separate Python modules (`budget_domain.py` and `bill_domain.py`) with no cross-dependencies. Each encapsulates its own business logic, database interactions, and validation rules.

**Alternatives considered**:
- **Single unified FinanceManager class**: Would combine all logic into one module. Rejected because it violates single responsibility principle and makes future microservice split impossible. Would create a God object anti-pattern.
- **Shared base classes/interfaces**: Could create abstract base classes for common operations. Rejected as premature abstraction—the domains don't share enough behavior to justify it. YAGNI principle applies.

**Consequences**:
- **Positive**: Clean separation of concerns. Each domain can be tested independently. Future microservice split is straightforward (each module becomes a service). No coupling between domains. Easy to understand and maintain.
- **Negative**: Some potential code duplication (e.g., both domains query database separately). Mitigated by keeping database.py as shared infrastructure.
- **Microservice seam**: The split would happen at the module boundary. `budget_domain.py` → Budget Service API, `bill_domain.py` → Bill Service API, each with their own database tables or separate databases.

---

## 3. Database Schema: Separate Table Hierarchies for Each Domain
Date: 2026-09-30  
Status: Decided

**Context**: Need SQLite schema supporting envelope budgeting (envelopes, transactions, rollover history) and bill tracking (bills, payment records, projections). Must align with domain separation (ADR-2) to enable future microservice split.

**Decision**: 
- **Budget Domain tables**: `envelopes`, `transactions`, `envelope_history`, `category_rules`
- **Bill Domain tables**: `bills`, `bill_payments`
- **No foreign keys between domains**: Envelopes and Bills are completely independent

**Alternatives considered**:
- **Linking bills to envelopes**: Could add `envelope_id` to bills table to auto-deduct bill payments from budget envelopes. Rejected because it couples the domains together, making microservice split harder. Cross-domain foreign keys are a red flag for future service boundaries.
- **Unified transaction table**: Could merge envelope transactions and bill payments into one table with a `type` discriminator. Rejected because they have different semantics (spending vs. bills) and splitting them makes domain independence clearer.

**Consequences**:
- **Positive**: Schema visually matches domain boundaries. Each domain "owns" its tables. Easy to split into separate databases later (just move tables). No cascade delete issues across domains.
- **Negative**: Can't enforce "pay bill from envelope" with database constraints if we want that feature later. Mitigated by implementing in application layer when needed. Some data denormalization (next_due_date stored in bills table).
- **Future**: When splitting to microservices, Budget Service gets `{envelopes, transactions, envelope_history, category_rules}` and Bill Service gets `{bills, bill_payments}`. No schema migration needed.

---

## 4. Testing Strategy: Focus on Business Logic, Not Flask Routes
Date: 2026-10-01  
Status: Decided

**Context**: Assignment requires ≥70% test coverage on core business logic. Need to prioritize what to test comprehensively vs. what to test lightly. Limited time to write tests.

**Decision**: 
- **Comprehensive testing (aim for 85%+)**: `budget_domain.py` (all envelope operations, overspend rules, rollover logic, auto-categorization) and `bill_domain.py` (bill creation, payment tracking, recurrence calculations, projections)
- **Light testing (aim for 40-50%)**: `database.py` (basic init/connection tests only), `llm_analyzer.py` (spot-check a few analysis functions)
- **No unit testing**: `app.py` (Flask routes are thin wrappers), templates (no complex logic)

**Alternatives considered**:
- **Test Flask routes with Flask test client**: Would increase coverage numbers but tests integration, not logic. Rejected because it's slower, more brittle (depends on templates, HTTP), and doesn't test business rules directly. Integration tests are useful but not the priority for this assignment.
- **Test everything equally**: Would waste time on low-value tests (e.g., "does this route return 200?"). Rejected in favor of focusing on where bugs would hurt most—the business logic that calculates money.

**Consequences**:
- **Positive**: Tests focus on the hardest, most error-prone code (rollover calculations, overspend rules, bill recurrence). Fast test suite (no Flask overhead, no HTTP mocking). Easy to run in CI. High confidence in core logic.
- **Negative**: Low coverage on `app.py` and `llm_analyzer.py` might trigger coverage warnings. Mitigated by documenting that we measured coverage on *core business logic* files specifically.
- **Coverage target achieved**: 85% on budget_domain.py, 82% on bill_domain.py, exceeding the 70% requirement.

---

## 5. Deliberately Chose NOT to Build: Real LLM Integration
Date: 2026-10-02  
Status: Decided

**Context**: Application includes an AI financial advisor feature that answers user questions. Could integrate with OpenAI API, Anthropic Claude, or similar LLM services.

**Decision**: Implement a **rule-based "fake LLM"** that pattern-matches questions and generates insights using hardcoded business rules. Do NOT integrate with external LLM APIs.

**Reasons**:
1. **Assignment constraint**: "No required external runtime dependency beyond a public API your use case genuinely needs." An LLM is not genuinely needed—the core use case (envelope budgeting + bill tracking) works fine without it.
2. **Cost & API keys**: Real LLM APIs require paid accounts and API keys, creating a barrier for anyone running the app (professor, TAs, other students testing it).
3. **Determinism & testing**: Rule-based responses are predictable and testable. LLM responses are non-deterministic, making automated tests fragile.
4. **Deployment simplicity**: No need to manage API keys in environment variables, no external service dependencies, works offline.
5. **Sufficient for demo**: The fake LLM demonstrates the feature concept without adding complexity.

**Alternatives considered**:
- **OpenAI GPT API**: Would provide more natural language responses. Rejected due to cost, API key management, and non-determinism.
- **Local LLM (llama.cpp)**: Would avoid API costs. Rejected because it violates the single-container constraint (huge model files, slow startup, memory requirements).
- **Remove AI feature entirely**: Would simplify the app. Rejected because it's a differentiating feature that shows creativity and adds value.

**Consequences**:
- **Positive**: No external dependencies, predictable behavior, instant responses, works offline, free to run, easy to test, simple deployment.
- **Negative**: Responses are less sophisticated than real LLM, limited to pre-defined question patterns, requires manual rule authoring. 
- **Mitigation**: The rule-based analyzer covers common financial questions well enough for a prototype/assignment. If this were production, we'd reconsider.
- **Documentation**: Clearly labeled as "simulated LLM" in code comments and documentation so it's not misleading.

**Implementation**: See `llm_analyzer.py` for pattern matching and response generation logic.

## 6. Static Frontend Boundary
Date: 2026-11-26
Status: Decided

**Context**: Assignment 2 requires the user interface to be independent from
the two backend services and deployable as an Azure Storage Static Website.

**Decision**: Build the frontend as vanilla HTML, CSS and JavaScript in `ui/`.
The browser calls the Budget and Bills REST APIs using configurable base URLs.
The frontend does not contain server-side templates, database access, or a
third application backend.

**Alternatives considered**:
- **Keep the original Flask templates**: Rejected because they depend on the
  monolithic Flask process and post forms back to routes that no longer own the
  data.
- **Add a frontend backend or proxy service**: Rejected because it adds an
  unnecessary deployable service and conflicts with the static UI requirement.

**Consequences**:
- **Positive**: The UI can be uploaded directly to Azure Storage Static Website,
  backend services remain independently deployable, and API boundaries are
  visible in browser network calls.
- **Negative**: API origins and CORS configuration must be set correctly for
  each environment. This is handled through `ui/config.js` and `UI_ORIGIN`.

## 7. Static Delivery and API Proxy
Date: 2026-11-26
Status: Decided

**Context**: A browser cannot resolve Docker service names such as `budget` and
`bills`, and direct cross-origin API calls require environment-specific CORS
configuration.

**Decision**: Deliver `ui/` with an Nginx Alpine container. Nginx serves the
static assets and proxies `/api/budget/*` and `/api/bills/*` to the existing
Budget and Bills containers. The proxy uses Docker's embedded DNS resolver so
backend container recreation does not leave stale upstream IP addresses.

**Consequences**:
- **Positive**: Browser requests are same-origin, Docker-only service names stay
  inside the Compose network, and the two domain services remain the only
  application backends.
- **Negative**: The UI delivery container must be deployed alongside the
  backend services for the local/Compose proxy paths. Azure Static Website
  deployment needs its public API origins configured separately.

## 8. Azure SQL Connection and Initialization Boundary
Date: 2026-11-26
Status: Decided

**Context**: Azure SQL logical servers do not provide the local Docker SQL
Server `sa`/server-login workflow. Azure SQL serverless databases can also be
paused and return transient connection errors while resuming.

**Decision**: Keep the existing Compose initialization path unchanged and add
`db/azure_init.py` for already-provisioned Azure databases. The Azure path
connects independently to each database, creates contained users idempotently,
and grants only the required database roles. `DATABASE_URL` is the primary
service contract, with the existing Compose variables retained as a fallback.
The `pymssql` encryption option is used for Azure URLs and certificate bypasses
are rejected. Only connection establishment retries known transient failures;
financial operations are not retried after a request has begun.

**Alternatives considered**:

- **Use `sa` and `CREATE LOGIN` in Azure**: Rejected because it is not an Azure
  SQL contained-user deployment model and would violate database isolation.
- **Retry all database operations**: Rejected because a financial write may
  have committed before a connection error is observed.
- **Replace the existing migrations**: Rejected because the current versioned
  migrations are already SQL Server compatible and transactional.

**Consequences**:

- **Positive**: Local Compose behavior remains unchanged; Azure credentials and
  databases are isolated; cold-start failures become controlled 503 responses.
- **Negative**: Azure setup must run the explicit contained-user initializer
  and service-specific migration URLs, and live Azure SQL verification remains
  pending until the resources exist.

## 9. Independent OpenAPI contracts for Budget and Bills

Decided on November 27, 2026.

**Context** — Each split Flask service has its own public API. The static
frontend calls both, and Budget also depends on the Bills list and due-date
routes. The assignment's system schema identifies each service's OpenAPI
document by a repository-relative path.

**Decision** — Maintain an OpenAPI 3.0.3 document beside each Flask app.
Use the default local origin in each document and capture the HTTP behavior
of the Flask routes, including monthly rollover and repeated deactivation,
payment retry behavior, distinct health and application error bodies, and
Budget's dependency errors. The contract tests load both service apps, match
the documented operations to their Flask route maps, and validate responses
with SQL and outbound HTTP fixtures.

**Verification** — Both documents passed the OpenAPI validator and all 137
Python tests passed. Live Compose probes validated JSON responses from both
services and reached both APIs through the UI proxy. The frontend review
findings are recorded in the README.

[Budget OpenAPI](services/budget/openapi.yaml) · [Bills OpenAPI](services/bills/openapi.yaml) · [Verification and findings](README.md#assignment-2-api-contracts)

### Step 22.1 validation and error handling

Decided on November 27, 2026.

Handle a dedicated input-validation exception as JSON 400 in each service.
Validate dates and client values before database access or cross-service
calls. Date parsing accepts the documented ISO forms and keeps the existing
empty-value defaults. Invalid amounts and text are checked against the SQL
column range or length where applicable. SQL connection and Bills dependency
errors continue to return 503. Unexpected exceptions reach Flask's server
error handler.

The static UI reflects the existing domain rules. The due-day maximum
depends on the bill frequency, and the purchase notice follows the Budget
response status. The dashboard still counts overdue active bills as due and
labels them explicitly. Form validation messages appear inside the relevant
dialog.

Regression tests verify the 400 schema, compatibility defaults, and failure
handling at the Flask boundary. Both OpenAPI documents validated and all
149 tests passed. Live HTTP probes and a Chrome smoke test exercised the
rebuilt Compose stack.
