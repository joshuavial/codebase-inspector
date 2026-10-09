# PRD-05: System views

Builds on PRD-01 (stable code model and static viewer), PRD-02 (concept map and two-way navigation) and PRD-03 (the desktop app that hosts the same viewer).

## Problem

The concept map explains responsibilities and code relationships, but it does not answer two common system-level questions directly:

- What data does this system store, how are its tables related, and where does code read or change them?
- What HTTP endpoints does this system expose, what calls them, and what code and data sit behind them?

Developers currently reconstruct both views from migrations, ORM models, route declarations, SQL strings and call graphs. The inspector already extracts routes, client calls and much of the code graph. It should assemble those facts into dedicated views without asking an agent to repeat deterministic work.

## Users

- A developer learning a service or application with a database and HTTP API.
- A developer tracing a request from a caller through its handler and services to stored data.
- An agent that needs the schema, endpoint inventory or code locations in a queryable model.

## Outcome

The viewer has three top-level tabs:

1. Concept map, which keeps the current concept map unchanged.
2. Database, which shows a conventional entity relationship diagram and table details.
3. API endpoints, which lists every detected endpoint and connects it to callers, handlers, services and tables.

The same tabs appear in the static viewer and in the desktop app because the app hosts the built viewer. A link from one view to another preserves a visible way back. Esc, Backspace and browser back follow the PRD-02 navigation rules.

Success signals:

- On sample-apps and sample-saas, a developer can identify the main stored entities, their keys and relationships without opening a migration.
- From a table, a developer can reach every detected code location that reads or writes it.
- From an endpoint, a developer can reach its callers, handler, downstream services and touched tables, then return to the endpoint in one step.
- The model contains no diagram coordinates, sizes, routes or other layout choices.

## Model the user sees

- **Table.** A stored relation with its database name, source location and optional framework model name.
- **Column.** A named field with its declared type, nullability and default where those are available.
- **Key.** A primary, unique or foreign key. A foreign key links a local column to a target table and column.
- **Table use.** A read or write from a file or symbol to a table. A single code location may have both uses.
- **Endpoint.** A server route with method, normalised path, handler and short note. Its callers come from `http_calls`; its downstream code comes from resolved calls and imports; its tables come from direct or downstream table uses.

Tables and columns are derived nodes in the existing model. Foreign keys, reads and writes are edges. Endpoint routes stay on their handler nodes and `http_calls` remains the link from caller to handler. Viewer payloads are projections of those facts, not a second source of truth.

## User journeys

1. **Browse the schema.** Open Database to see tables as boxes with columns and relationship lines. Pan, zoom and fit work as they do on the concept map. Select a table to see all columns, primary and foreign keys, inbound relationships and code that reads or writes it.
2. **Trace data to code.** Choose a read or write in the table drawer. A code link opens the existing concept-map location and leaves a Back chip. Double-click opens the file in the configured editor at the recorded line.
3. **Browse endpoints.** Open API endpoints to see method, path and a short note for every detected server route. Filter by method or text. Select an endpoint to see callers, its handler, downstream services and touched tables.
4. **Trace an endpoint.** Follow a caller or handler to the concept map, or a table to the database view. Back, Backspace or the Back chip returns to the selected endpoint with its list position and filters restored.
5. **Use an incomplete model.** A repository with no detected schema or no detected endpoints still shows all three tabs and a plain empty state that explains what inputs are recognised.

## Requirements

### Extraction and model

- D1. Detect tables, columns, primary keys, unique keys and foreign keys from SQL migrations. Support common `CREATE TABLE` and `ALTER TABLE` forms without executing migrations.
- D2. Detect the same schema facts from SQLAlchemy and Django models, Prisma schemas, TypeORM entities and EF Core models as used by the target sample repositories and focused fixture repositories.
- D3. Reconcile repeated declarations of the same database table into one stable table node. Prefer explicit database names over inferred model names. Keep every source location as evidence.
- D4. Detect table reads and writes from literal SQL and common ORM calls. Reads include select, query and find forms. Writes include insert, update, delete, create, save, add and remove forms when the target model is known.
- D5. Attach a table use to the innermost enclosing symbol when possible, otherwise to its file. Store read and write as separate edge kinds so a location may do both.
- D6. Derived node and edge IDs are stable across scans and machines. A rescan replaces only derived data facts and cannot remove code, concept or judgement data.
- D7. Extraction never imports or executes target code, opens a database, or reads ignored and untracked files.
- D8. The schema model contains semantic facts and source evidence only. It contains no positions, dimensions, colours or edge routes.

### Endpoint catalogue

- A1. List every detected server route, including routes with no matched client call. Each entry has method, normalised path, handler and source location.
- A2. Use the handler summary as the endpoint note, falling back to the handler docstring, then the containing file summary, then a short deterministic handler name. Do not open a new judgement task while those sources are adequate.
- A3. Callers come from existing `http_calls` edges. Handler services come from resolved calls and imports, with repeated or internal helper paths collapsed for display.
- A4. Tables touched by an endpoint include direct handler uses and uses reached through the resolved call graph. The payload marks direct and downstream evidence separately.
- A5. The endpoint catalogue is a deterministic build projection. `cbi` never calls a model. If endpoint-specific notes later prove necessary, they use a new optional judgement task under the existing stale-answer, validation and cache protocol.

### Viewer and app

- V1. Concept map, Database and API endpoints are top-level tabs. Concept map behaviour and appearance remain unchanged inside its tab.
- V2. The selected tab is represented in the URL hash so refresh, deep links and the desktop app restore it.
- V3. The database diagram is a conventional ERD. Table cards show the table name, primary-key marker and column names and types. Foreign-key lines connect the relevant tables.
- V4. The database view uses automatic layout in viewer code. Wheel and touchpad pan, Cmd/Ctrl+wheel and pinch zoom, drag pan, plus, minus and fit controls match the concept map.
- V5. Selecting a table opens a drawer with columns, keys, inbound and outbound relationships, and grouped Reads and Writes links to code.
- V6. The endpoints tab is a searchable, method-filterable list sorted by path and method. Selecting an endpoint opens its callers, handler, downstream code and tables.
- V7. Code links select the code in the concept map when it has an owning concept. Double-click and explicit Open in editor use the existing editor path. Table links select the table in Database.
- V8. Every cross-view jump creates a visible Back chip. Browser back and Backspace perform the same step and restore selection, filter, scroll and camera state. Esc first closes or clears the current detail selection, then goes to the prior level or origin as specified in PRD-02.
- V9. Model text is rendered with `textContent`, never as HTML.
- V10. The desktop app needs no separate schema implementation. Its viewer host, deep-link state, editor bridge and saved view state accept the new tab state and continue to use the same built assets.

## Acceptance criteria

- E1. A SQL migration fixture produces the expected tables, columns, primary keys, foreign keys and source evidence, including an `ALTER TABLE` foreign key.
- E2. Focused SQLAlchemy, Django, Prisma, TypeORM and EF Core fixtures each produce their expected schema without running framework code.
- E3. SQL and ORM usage fixtures link reads and writes to the right tables and innermost functions. False matches in comments, unrelated method names and test doubles are covered.
- E4. A built fixture viewer has all three tabs. The database tab draws the expected tables and relationship, selection shows reads and writes, and pan, zoom and fit work under headless Chrome.
- E5. The endpoint tab includes matched and unmatched routes, notes, callers, handlers, downstream code and tables. Code and table jumps create a working return path, and Esc follows PRD-02.
- E6. The desktop app unit tests confirm that saved and deep-linked viewer state preserves the selected system tab. Electron smoke scripts are not required for this increment.
- E7. `uv run pytest` and `npm test` in `app/` pass. Headless Chrome screenshots of the database and endpoint views are inspected before completion.
- E8. Mapping sample-apps and sample-saas uses `--out` outside those repositories and leaves their working trees unchanged.

## Non-goals

- Connecting to a live database or comparing the model with one.
- Executing migrations or importing ORM metadata.
- Editing a schema or endpoint in the viewer.
- Full SQL parsing for every dialect or dynamic query construction.
- Query plans, row counts, indexes beyond declared keys, stored procedures or database permissions in this increment.
- OpenAPI generation or request and response schema inference.

## Assumptions and risks

- Static detection is strongest when table and route names are literal. Dynamic names remain undetected instead of being guessed.
- ORM conventions can infer table and foreign-key names differently under project configuration. The extractor records explicit names first and uses documented framework conventions only when needed.
- Large schemas can make an ERD crowded. Layout and progressive detail belong in the viewer; the stored model stays complete and layout-free.
- Downstream endpoint tables depend on resolved calls. The endpoint drawer distinguishes direct from downstream evidence so a partial call graph does not look exact.

## Open questions

- Whether indexes other than primary and unique keys should join the model after the target repositories are checked. Default: defer them.
- Whether endpoint request and response types should become a later fourth panel. Default: keep this increment focused on callers, code and tables.
