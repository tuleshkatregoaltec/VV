# AI evaluation discovery and implementation plan

Discovery base: `9b3303f`, branch `refactor/backend-domain-boundaries`.
The completed migration and `ARCHITECTURE.md` remain authoritative.

## Execution evidence and blocking prerequisite

Source discovery is complete enough to identify the paths below. **None of the
15 live questions has executed yet.** Automatic approval review rejected the
proposed local authenticated run because OpenRouter could receive warehouse
results. Explicit approval of that data flow is pending. No trace upload has
occurred. Static reachability is not evidence of actual model tool selection.
Evaluator design and quality baselines must follow real execution, as requested.

The local API responds to health checks. The configured model is
`google/gemini-3.1-flash-lite` through OpenRouter. Pydantic AI is locked at 1.38.0,
Logfire at 4.19.0. No LangSmith dependency or key was found in the local env file.
These are discovery observations, not permanent configuration defaults.

## Actual AI capabilities, models, agents and tools

All currently found model calls select `settings.DEFAULT_CHAT_MODEL` and
`settings.OPENROUTER_API_KEY` (`app/config.py`). There is no application-level
multi-model fallback/routing mechanism. OpenRouter's downstream routing is
provider behavior and must be recorded from response metadata when available.

| Capability | Runtime entry and agent | Tools / model behavior | Data and downstream operations |
| --- | --- | --- | --- |
| Market chat | `app/chat/router.py` → `service.stream_chat_response` → `agent.agent.iter` | Three registered tools; low reasoning effort; text streaming | Conversation/history in chat PostgreSQL repository, usage through token usage service; tools below |
| Market pulse | `chat.tools.get_market_pulse` | `area`, `period_days` | `analytics.service.get_market_pulse` → `analytics.queries.fetch_market_pulse` → ClickHouse `ch_transactions` |
| Area rankings | `chat.tools.rank_areas` | `metric`, `limit`, `period_days` | `analytics.service.rank_areas` → `analytics.queries.fetch_rank_areas` → `ch_transactions` |
| Similar projects | `chat.tools.get_similar_projects` | `project_name`, `limit` | `project.service.get_similar_projects` → reference and comparable queries → `ch_transactions` |
| Feasibility workspace chat | `feasibility.router` → `chat.stream_chat_events` → `stream_feasibility_response` → `chat_agent.workspace_chat_agent.iter` | Research plus staged edits; temperature 0.1; supplied history/context | `research.get_area_market_research`, `rank_plot_comparables`, `plots.service.get_plot_details`, `plots.evidence.get_land_sale_evidence`; ClickHouse |
| HBU study generation | `feasibility.generation.generate_hbu_study` → `hbu_agent.run_seed_draft` | Selects `hbu_seed_agent_bts_prefetched` or `hbu_seed_agent_btr`; structured `HBUSeedDraft`; temperature 0.1; request limits 15 / 3 | Research is prefetched through public area, project, plots and feasibility operations; deterministic assumption composition follows model draft |
| Legacy HBU declaration | `feasibility.hbu_agent.hbu_seed_agent` | Seven registered tools, **not selected by production `run_seed_draft`** | Existing/off-plan pricing, area rents, rental/pricing/pipeline comparables, land sales |
| Dashboard news summary | `news.service.fetch_news_summary` → `news.agent.summarize_articles` → lazy summary agent | Structured `NewsSummaryDraft`; temperature 0.1; one request; deterministic fallback on error | `news.repository` PostgreSQL headlines; empty-input response does not invoke model |
| CRM owner import schema mapping | `crm.imports` → `crm.ai._llm_mapping` | Direct HTTP OpenRouter JSON response; headers only; heuristic fallback | CRM parsing/identity rules and owning import repositories; no autonomous tools |
| CRM enquiry extraction | `crm.inbound_imports.process_inbound_import` → `crm.ai._ai_extract` | Direct HTTP JSON extraction; deterministic extraction first; redacted input; empty fallback | Owning CRM PostgreSQL workflows and matching capabilities; no autonomous tools |
| CRM header mapping | `crm.inbound_imports.preview_inbound_import` → `crm.ai._ai_header_mapping` | Direct HTTP JSON; conservative validated header mapping | Supplied headers and campaign context; no autonomous tools |

Workspace tool set: `get_current_plot`, `get_area_market_data`,
`rank_pricing_comparables`, `rank_pipeline_comparables`, `get_plot_land_sales`,
`show_transactions`, `show_analytics`, `update_prices`, `update_unit_mix`,
`replace_unit_mix`, `update_assumptions`, `update_payment_plan`.
The show tools return UI instructions; chat orchestration calls
`research.fetch_chat_research`. Mutation tools propose `pending_action` events;
the frontend owns approval and the live workbook. They do not persist arbitrary
server mutations. This distinction must remain visible in traces and tests.

No additional model invocation was found in frontend or Holocron source searches.
Holocron remains a separate ingestion runtime, not an agent framework.

## Data ownership and important limitations

Chat authentication, active membership/subscription and token quota use existing
route dependencies. Conversation ownership is checked before streaming. Evaluation
must enter the authenticated HTTP application, without dependency overrides or
private repository reads. Evaluation conversations may be deleted via the same
API; token usage remains accounted for, just as in normal application use.

The three market chat tools currently reach only `ch_transactions`. They do not
reach registered rents, listings or supply tables. `get_market_pulse` and area
rankings preserve historical non-sales inclusion. Pulse aliases raw area and
price/area as sqft without conversion in its query. These are existing risks to
characterize, not behavior to silently fix in an evaluation project.

Other public application operations exist but are **not registered chat tools**:
`analytics.charts.{sales_chart,rental_chart,project_chart,custom_chart}`,
`transaction.service.{fetch_sales_transactions,fetch_rental_contracts}`,
`listings.service.{list_listings_from_clickhouse,listing_analytics_from_clickhouse}`,
`supply.service.{list_supply_catalogue_projects,get_supply_catalogue_project}`,
and `crm.reports.get_property_report`. Do not enable tools merely to pass tests.
CRM reports require an authorized lead context; a building name alone is not that
context.

Feasibility research reads `ch_transactions`, `ch_projects`, `ch_rent_contracts`,
`ch_units` and `ch_buildings`; plot evidence/geometry reads transactions and
`ch_gis_land_plots`; project/area operations add geographic and project facts.
Listings query modules read Property Finder inventory and supply modules read
Reelly inventory/project facts. Model calls go to OpenRouter; auth goes through
GoTrue. Redis caches and object storage are infrastructure, not additional LLMs.
PostgreSQL holds conversations/messages, token usage, organizations/subscriptions,
CRM imports/contacts/leads and saved feasibility studies under owning repositories.

## Canonical benchmark and execution matrix

The checked-in dataset preserves the user's exact 15 questions. Placeholders are
literal templates, not inferred entities. Unbound cases can later be run as
clarification tests; bound variants require explicitly supplied parameter values
and separate identity/fingerprints. There is no current chat-side entity resolver
that supplies those missing values automatically.

Every question enters the **same market chat route**. The table below describes
source-derived capability gaps, **not observed execution paths**. Actual selected
tools, arguments, queries, intermediate data and answers remain pending execution.

| ID | Requested behavior | Source-derived gap to investigate during execution |
| --- | --- | --- |
| 1 | JVC sales price brackets and shares | No bedroom/property/price-bracket filter in pulse |
| 2 | Business Bay building rankings, 2BR, last quarter | Area rank tool cannot rank buildings or restrict bedrooms/calendar quarter |
| 3 | Downtown 1BR interquartile range | No quartile output or bedroom filter |
| 4 | JLT new/renewed rents | No rental-contract tool |
| 5 | Marina multi-year rent normalization | No rental records/annualization tool |
| 6 | Monthly studio rents, six complete months | No rental trend tool |
| 7 | Dubai South delivery concentration | No developer/supply tool |
| 8 | JVC missing/overdue completion dates | No project-delivery status tool |
| 9 | Dubai Hills listing counts/asking prices | No listings tool |
| 10 | Marina listing age at capture | No listing age/capture tool |
| 11 | JVC listing yield with rental evidence | No listing-to-rent evidence operation reachable from chat |
| 12 | JLT building rental appraisal | Unresolved building; no rental/listing tool or report tool |
| 13 | Downtown seller competition | Unresolved building; no listing/comparable-report tool |
| 14 | Business Bay monthly multi-source report | Pulse can provide partial aggregate context only |
| 15 | Three-project off-plan comparison | Unresolved project names; similar-project tool lacks payment/progress data |

## Existing tests, observability and uncovered behavior

`tests/agents/test_chat_tools.py` freezes exactly three tools and their schemas.
`test_feasibility_tools.py` freezes workspace tools. `test_hbu_generation.py`
checks real routing choices, request limits and deterministic plot constraints
with mocked provider responses. Streaming tests cover missing conversations,
provider failure, usage/save ordering, invalid feasibility history and completion.
Unit tests cover OpenRouter service-tier compatibility, CRM redaction/extraction,
import identity/mapping, news fallback, listing/supply policies and query rules.
Contracts freeze OpenAPI, models and stored JSON; architecture tests enforce
acyclic imports and domain ownership.

Real-service integration suites use isolated PostgreSQL/ClickHouse databases.
`tests/integration/clickhouse/test_chat_capabilities.py` executes real pulse,
ranking, similar-project and chart SQL and explicitly preserves non-sales pulse
behavior. Such tests establish query contracts, not natural-language answer
quality. Existing Playwright `chat.spec.ts` tests conversation CRUD and mocked
SSE/artifact rendering; feasibility tests cover proposed edits and saved studies.

`app/main.py` configures Logfire/Pydantic AI/FastAPI instrumentation. There is no
benchmark dataset, experiment workflow, quality evaluator, quality baseline or
regression gate. Direct CRM HTTP model calls are not Pydantic AI spans. Token
accounting exists for market chat; do not assume that coverage extends to every
AI invocation. Cost and routed-provider identity are not uniformly captured.

## Integration decision and implementation sequence

1. Preserve canonical inputs and produce a source-derived capability inventory.
   Keep evaluation orchestration in `backend/scripts/evaluation`, outside domain
   modules. Generate tool declarations, callable edges, source/table references,
   model configuration and source fingerprints from code. Label unresolved dynamic
   calls and distinguish static reachability from observed execution. No parallel
   manually maintained tool registry.
2. With execution approval, run all 15 through local authenticated HTTP, collecting
   local OpenTelemetry/Pydantic AI evidence. Preserve exact production prompts,
   reasoning settings, streaming and authorization. Do not substitute direct
   `agent.run` for the streaming path. Record date/time, dataset digest, code SHA,
   configured/resolved model, prompt/tool fingerprints, warehouse snapshot label,
   errors, completion, latency and usage. Inspect each result before finalizing
   evaluators. Missing prerequisites and unresolved references remain explicit.
3. Add opt-in infrastructure observability. Prefer native Pydantic AI OpenTelemetry
   and LangSmith's OTLP ingestion over replacing agents or decorating domains with
   LangSmith APIs. Reuse one tracing configuration rather than double-instrumenting
   with Logfire. Small infrastructure spans should capture database system,
   operation/query fingerprint, source tables, row count, latency and status.
   Add explicit public-operation spans only where needed to explain the real path.
   Direct CRM provider calls need equivalent metadata-only spans, including fallback
   behavior. Preserve dependency direction and streaming cancellation behavior.
4. Finalize evaluator strategy **after the observed runs**. Separate transport and
   streaming contracts, tool failures, evidence-source/argument checks, reference
   value checks, and semantic/human review. A completed stream is not a correct
   answer. Do not award factual correctness without a trustworthy oracle. Missing
   references mean unassessed, not pass. Numeric tolerances/record expectations
   belong to curated reference metadata; do not duplicate production business SQL.
   Judge grounding/completeness only where deterministic evidence cannot establish
   quality; version the rubric and judge model. A judge is not an oracle for market
   facts. Human review handles ambiguous scope and unsupported requests.
5. Add local persisted results and explicit LangSmith dataset/experiment publishing.
   Use content-addressed dataset versions and stable example IDs. The SDK supports
   local evaluation without upload and evaluating existing experiments without
   rerunning models. Keep raw evidence locally by default; publish only reviewed,
   sanitized inputs/results. Comparison requires matching dataset/parameters,
   reference version and data/date context; otherwise report incomparable. Track
   per-case regressions and unassessed coverage rather than one misleading score.
6. Establish a real baseline, run targeted then broad checks, inspect diffs and
   commit coherent stages. Add deterministic offline CI checks without model keys;
   live/model runs are explicit cost-bearing workflows, not automatic pull-request
   jobs with production credentials. New questions append dataset examples.

## Privacy, single-trace debugging and operational tradeoffs

Default remote telemetry must exclude prompts, answers, tool arguments/results,
SQL text/parameters, user/org IDs, auth headers, error messages/stack contents and
CRM context. A field-name denylist alone is insufficient for free text and nested
content. Use allowlisted metadata at the exporter boundary, including exception
and resource/event handling. Do not assume LangSmith SDK input hiding also filters
arbitrary OpenTelemetry attributes. Hash code/prompts/query templates for version
identity; do not hash low-entropy PII as a substitute for removing it.

Full evidence is needed for grounding and numerical debugging. Keep it in explicit
private local artifacts (restricted permissions, ignored by Git), with separate
sanitized-fixture mode for remote content. Production/staging/local projects must
be separated and export disabled unless configured. Sampling affects operational
observability, never whether an offline benchmark case is considered evaluated.
A user must be able to follow root → model → tool → operation → database/provider
and see where an error occurred; metadata-only remote views link to local evidence
by opaque run ID, not secret filesystem paths or auth context.

Relative time questions cannot have an eternal numerical baseline on mutable
warehouse data. Record date/time and a declared data snapshot; use isolated seeded
integration data for deterministic SQL assertions. Do not alter `today()` or model
prompts silently to fake reproducibility. Provider cost is unknown unless returned
or derived from versioned, explicit pricing; unknown is not zero.

## Verification plan and frontend preservation

- Validate canonical dataset identity, stable case IDs, explicit parameter binding
  and refusal to invent/partially bind placeholders.
- Verify inventory updates when actual registrations/call paths change, separates
  inactive declarations, and reports uncertainty rather than inventing edges.
- Test privacy at the export boundary with nested tool payloads, SQL parameters,
  exception messages/events and adversarial PII; disabled export makes no requests.
- Test real nested spans and parent IDs with controlled Pydantic AI responses;
  cancellation/error paths must retain existing SSE and persistence semantics.
- Test evaluators against deliberately wrong evidence, date/filter errors and
  missing references, once trace-driven evaluator requirements are established.
- Test comparison rejects changed datasets/parameters/data contexts and detects
  per-case regression despite successful transport.
- Run `just test-backend` targeted then full; `just lint-backend`; isolated
  database suites where instrumentation touches those clients; frontend tests
  and build; relevant existing Playwright chat/feasibility/guard flows. Do not
  make all model questions browser tests. No UI change or API schema change is
  currently justified, so client regeneration is unnecessary unless scope changes.
- Smoke-test LangSmith ingestion/dataset/experiment links only with configured
  credentials and allowed sanitized content. Report absent credentials as a
  verification gap, never as successful integration.

## Current official guidance consulted (2026-09-28)

- [Pydantic AI tracing](https://docs.langchain.com/langsmith/trace-with-pydantic-ai)
- [OpenTelemetry ingestion and attribute mapping](https://docs.langchain.com/langsmith/trace-with-opentelemetry)
- [Evaluation SDK](https://docs.langchain.com/langsmith/evaluate-llm-application)
- [Local evaluation without upload](https://docs.langchain.com/langsmith/local)
- [Evaluate existing experiments](https://docs.langchain.com/langsmith/evaluate-existing-experiment)
- [Mask inputs and outputs](https://docs.langchain.com/langsmith/mask-inputs-outputs)
- [Compare experiments](https://docs.langchain.com/langsmith/compare-experiment-results)

These APIs inform the direction; verify compatibility against installed SDKs
before implementing. No evaluation quality result is claimed by this document.

## Implemented discovery commands

- `just ai-benchmark`: print validated canonical cases and dataset SHA-256.
- `just ai-inventory`: print generated static source evidence as JSON. No app
  import, database access, provider call or telemetry export is performed.
- `just test-evaluation`: offline dataset/inventory tests. These also run in the
  default `just test-backend` suite.

`Case.bind()` preserves an unbound question exactly. Explicit bindings must supply
all and only its declared parameters with nonempty concrete values. Case IDs can
extend beyond 15; dataset digests change with content, independent of JSON layout.
The inventory fingerprints actual prompt literals/declarations and code, lists
registered tools and source signatures, follows resolvable module-level calls to
public capabilities/query functions, and records unresolved calls separately.
Direct HTTP model endpoints/configuration references are included. It is not yet
a runtime trace viewer, a compiled tool-schema inventory or an evaluation runner.

The remaining execution, instrumentation, evaluator, LangSmith and regression
stages above are pending. No model-quality baseline has been established.

Discovery checkpoint verification: 292 backend tests passed in the default run;
three workbook parity tests initially skipped because Bun was absent from PATH,
then all three passed with the installed Bun runtime (295 verified in total,
including nine new discovery tests). All 68 frontend unit tests passed with the
installed Node 20.19.6/Bun paths; the first attempt with system Node 18 failed at
Vite startup. Backend Ruff checks and formatting checks passed. No production
runtime code changed. Database integration suites, frontend build and Playwright
were not rerun for this read-only tooling/documentation checkpoint. Live model
execution, remote tracing and quality evaluation remain unverified and pending.
