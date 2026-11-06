# Assistant implementation and model selection — 4 November 2026

Status: implementation is behind disabled rollout flags. No deployment, production migration, live WhatsApp delivery, new Gemini inference or Qwen3.8 Max inference was performed. Existing feasibility configuration is unchanged.

## Prices and candidate results

Public OpenRouter model pages checked on 4 November 2026. These are advertised starting prices in USD per million input/output tokens, not a quote for a privacy-compatible endpoint. Provider routes, long-context tiers and reasoning output can change the actual bill; private run manifests retain the catalog and enforced price caps used for each experiment.

| Candidate | Input / output per million | Decision from reviewed comparison |
| --- | --- | --- |
| [Qwen3.8 Flash](https://openrouter.ai/qwen/qwen3.8-flash) | $0.15 / $0.47 | No compatible endpoint under the required zero-retention/parameter policy; not eligible |
| [Qwen3.7 Plus](https://openrouter.ai/qwen/qwen3.7-plus) | $0.32 / $1.28 | Same endpoint restriction; not eligible |
| [GPT-6 Luna](https://openrouter.ai/openai/gpt-6-luna) | $0.10 / $0.50 | Promising candidate; final qualification unresolved, rollout blocked |
| [Claude Haiku 5.5](https://openrouter.ai/anthropic/claude-haiku-5.5) | $0.10 / $0.50 | 7/9 ordinary comparison cases; a fabricated rent-growth statement blocks selection |
| [DeepSeek V4.1 Flash](https://openrouter.ai/deepseek/deepseek-v4.1-flash) | $0.032 / $0.288 | 6/9 ordinary comparison cases; metric/filter/time interpretation failures |
| [GLM 5.3 Flash](https://openrouter.ai/z-ai/glm-5.3-flash) | $0.0269 / $0.0996 | 5/9 ordinary comparison cases; schema, filter and rent-unit failures |

The four available challenge candidates received identical synthetic cases. The first screen contained inconsistent coverage metadata; those results are retained and not used as the final quality comparison. The corrected comparison is `.evaluation/selection-challenge-final-20261104`. Qwen failures and interrupted/unknown requests retain their conservative reservations rather than being treated as free. No privacy policy was relaxed to obtain a cheaper route.

## Implemented boundaries

- Separate assistant-role model configuration rejects Gemini, Qwen3.8 Max and fallback aliases. Both assistant and typed-routing rollout flags default off. Existing specialists and backend database services remain canonical.
- Typed routing covers market, pricing, personal CRM, follow-up, action preparation, clarification and unsupported requests; mixed requests share limits. A versioned capability catalog defines sources, permissions, metrics, units and unavailable operations. Revenue remains unavailable without a financial ledger.
- Broker-managed customer listing publication includes safe reviewed fields, mandatory expiry, organization/connection scope, optimistic revisions and revocation. Price/availability updates require fresh approval. Customer market sharing defaults off, requires explicit dataset permission, and exposes only restricted aggregates.
- Publication-management endpoints, migration, generated API client, typed frontend API/query helpers and inbox publication controls are included. Customer facts are rendered from approved evidence; delivery rechecks permissions, expiry, revisions and releases. Private contacts, notes and ownership enrichment stay outside customer retrieval.
- Existing opt-out, takeover, duplicate handling, uncertain sends and in-app action confirmation remain enforced. Qualification completion hands off for broker review.

## Reviewed evidence and limits

`selection-luna-release-20261104` passed 9/9 ordinary specialist cases and 4/4 safety cases after customer prompt/policy corrections: $0.003369125 provider-reported total, 25 model requests, 4.612-second median scenario latency.

`selection-flows-release-20261104` passed 13/13 ordinary cases and 10/10 safety cases: $0.009411915 provider-reported total across full conversations, 59 model requests, 7.392-second median scenario latency. The run includes fresh multi-turn CRM reads, mixed intents, approved listing and market retrieval, qualification, injection and unavailable operations. One invalid reminder filter was rejected and recovered; this remains a tool-accuracy defect even though the answer was useful. Earlier failed application runs are retained, including a fabricated narrowing of a bedroom minimum; their failures were not rewritten or promoted.

Tool-call validity in that flow run was 27/28 (96.4%), including the recovered reminder error. Five of 27 assistant turns explicitly requested clarification (18.5%; includes the three qualification questions, ambiguous action target and ambiguous request). These are observed small-suite measures, not production estimates.

These flow tests execute application agents with synthetic data-access leaves and blocked actions/sends. They do not establish real phone-delivery success. Real authenticated database/SSE comparison is recorded separately; typed routing must remain off unless that comparison preserves quality and improves cost or latency. No automatic production enablement occurs after an evaluation.

The cumulative private SQLite ledger enforces $3 screen / $2 challenge / $5 flows and $10 overall, reserving before every nested provider request. It includes retries, provider failures, reasoning usage, interruptions and pending/unknown charges. Published catalog prices alone are not used as evidence of full conversation cost.

## Checks and operational constraints

Backend: 2,068 tests passed with no skips after the final evaluation-wrapper correction (including 16 actual instrumented SDK/transport budget regressions); full PostgreSQL suite: 195 passed. Targeted ClickHouse market/capability checks: 21 passed, 89 unrelated cases deselected. Frontend: 394 unit tests passed, diagnostics/build/lint passed; Playwright guards: 34 passed. Contract fixtures and generated client were refreshed and checked. Fresh Astra/ultra independently verified the customer boundaries and qualification correction (167 focused tests passed).

The normal full Compose start was blocked by the existing inaccessible MinIO image; required PostgreSQL, ClickHouse, Redis and local auth services were started separately. HTTP evaluation uses isolated pinned databases and a synthetic locally authenticated user. A mismatched local auth service key was corrected only in the evaluation environment. No real contacts received messages. The existing Meta sending-permission blocker remains unverified by live delivery.

Production migrations/deployment, broad unrelated ClickHouse coverage, real WhatsApp sends and a production-data model trial were intentionally not performed. Keep rollout disabled until the remaining real-flow evidence and operational permissions are accepted.

## Final qualification decision

**Rollout blocked.** The final unchanged-application requalification after the tracing-wrapper fix is `.evaluation/selection-luna-verified-20261104`: 8/9 reviewed ordinary cases (88.9%), 4/4 safety cases, $0.00214869 provider-reported cost, 25 model requests and 4.630-second median scenario latency. The unresolved case has correct values but conflicting provenance cues: the tool contract explicitly says Property Finder while its synthetic result says Synthetic captured asking prices. Independent Astra review found this does not establish fabrication. The initial overstrict critical label was corrected with a preserved review audit; the case remains unsuccessful and no gate was bypassed.

The authenticated HTTP baseline attempts failed before inference: first a mismatched local auth admin key, then SDK settings mutation in the instrumented evaluation wrappers. Both causes were diagnosed; the wrapper correction passes 16 real SDK/MockTransport tests preserving strict overrides, pricing, privacy and reservations. No successful real HTTP A/B run is claimed. Its final retry was not eligible after the unresolved qualification result. Existing orchestration is retained and typed routing remains off. Next: make synthetic provenance consistent with the supplied tool contract, review that case, then repeat eligible pinned HTTP A/B before considering enablement.

Final cumulative ledger: **$3.105241 accounted against $10**, comprising screen $2.501887, challenge $0.474873 and flows $0.128481. There are 492 request reservations: 476 settled and 16 unknown, no pending requests. Ledger-settled reported costs sum to approximately $0.10; the remaining conservative allowance covers unknown/failed/interrupted requests rather than assuming they cost zero. This is not a provider billing reconciliation. No more inference is running.

Architecture, publication authorization, evaluation/spending controls and independent review used Astra with ultra reasoning as requested. Earlier routine integration was handled locally or by the assigned crew; development-agent use is excluded from the application ledger. Existing edits were preserved; no commit, push or deployment was made.
