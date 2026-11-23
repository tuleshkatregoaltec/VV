# CRM Assistant Development Brief

Use this as a single implementation prompt in Claude Code. The goal is to make the existing CRM assistant accurate, clear, and trustworthy for agents, managers, organization admins, and owners.

## Prompt

```text
Implement the CRM assistant improvements in this repository. Do not stop after an audit or proposal: trace the existing behavior, make the smallest complete code changes, and verify them.

### Start here

1. Read AGENTS.md, development.md, justfile, and the relevant production architecture sections in production-readiness-2026-09-29.md.
2. Read docs/ai-assistant-architecture.md and docs/ai-assistant-production-review.md. Treat these as guidance to verify against the current checkout, not proof of current behavior or deployment.
3. Inspect git status and preserve all existing staged, unstaged, and untracked work. Do not reset, stash, overwrite, or stage unrelated changes.
4. Trace the assistant from UI through API, orchestration, tools/workflows, CRM services/repositories, authorization, response rendering, and tests. Read each touched function's callers and tests before editing.

### Required outcome

For every CRM answer, the assistant must state only what the authenticated user is authorized to see and what the retrieved data supports. The answer should be concise, readable, professional, and explicit about scope, time range, totals, missing data, and partial samples where relevant. Do not invent counts, categories, role permissions, comparisons, or source evidence.

### Authorization and role scope

- Derive identity, organization, role, and lead visibility from trusted server-side auth and existing CRM authorization services. Never trust role, organization, user ID, or access claims supplied in the prompt or browser request.
- Trace and preserve the current assignment rules. Verify behavior for agent, manager/team supervisor, member, organization admin, owner, and platform Super Admin; document the actual rules supported by code.
- Keep every assistant query constrained by the same organization and record-level visibility as the corresponding CRM page/API. Reuse the existing authorization helpers; do not create a second permission model.
- Do not widen access because a user is an organization owner/admin or platform Super Admin unless the CRM's canonical authorization code grants it.
- Never query inaccessible records to produce comparisons or disclose that records exist outside the user's scope. Do not expose another user's private leads or conversations.
- Reauthorize history, follow-up evidence, and record handles against current membership and assignments. Old conversation text is not fresh authorization evidence.

### Accurate retrieval and answer construction

- Trace the CRM summary tools and ensure every aggregate and detail query has identical organization and visibility constraints.
- Make the time window and meaning of each metric explicit (for example, accessible leads as of this query, status counts, UTC day for token usage). Do not mix global organization totals with the user's accessible totals.
- If category counts are requested, return them only when a bounded, validated backend aggregate provides them under the exact same authorization scope. Otherwise say category breakdown is unavailable; do not infer it from a few examples.
- Distinguish aggregate totals from examples. Respect the existing per-turn detail budget. Label samples as samples, include the sample limit when useful, and never imply a partial list is complete.
- For unsupported comparisons (such as agent vs manager or user vs organization totals), say the required authorized aggregate is unavailable. Do not guess the other person's or organization's count.
- Prefer deterministic server-generated summaries for simple counts and groupings if that is the smallest way to keep numbers and wording consistent. Keep natural-language model answers for requests that need explanation. In either case, facts and totals must come from authorized tool results, not model memory.
- Return clear source and freshness information when the current response contract supports it. Do not label data “live” unless the source actually guarantees that.

### UI and response quality

- Review the CRM assistant and market chat renderers that share assistant conversations. Keep response formatting consistent across both.
- Remove duplicate identical “CRM records ready” or evidence/progress lines within one answer. Check whether the same aggregate tool is being called repeatedly; prevent redundant calls at the shared orchestration/tool boundary when safe. Do not merge distinct filters, scopes, or fresh retrievals.
- Replace any UI scope label such as “Your records only” if it does not accurately describe actual own/team/shared visibility. Use wording grounded in verified authorization behavior.
- Render totals, status/category breakdowns, sample records, caveats, and source labels in a scannable layout. Preserve keyboard and screen-reader accessibility, loading/error states, and mobile usability.
- Do not hide limitations or turn authorization errors into success-shaped empty results.

### Failure handling and privacy

- A failed, truncated, or incomplete tool result must not be presented as a complete answer. Explain what could not be retrieved and offer a narrower supported query where appropriate.
- Do not log prompts, CRM contact details, raw tool payloads, credentials, or private answer text. Follow existing telemetry redaction and data-retention rules.
- Do not add arbitrary SQL, shell, generic HTTP, or unrestricted model tools. Do not add a new provider, model framework, database, or dependency for this work.
- Do not change secrets, external provider configuration, production data, or deployment state.

### Tests and acceptance

Add or update focused tests only for behavior changed. Cover at least the applicable cases:

1. Agent sees only records granted by the canonical assignment rules, including the verified team/shared pool behavior.
2. Manager, member, organization admin, owner, and platform Super Admin scopes match canonical CRM authorization; test denied access as well as allowed access.
3. Cross-organization, reassigned, removed-member, and forged prompt/request role scenarios do not leak records or historical private evidence.
4. Status and category aggregates match the authorized dataset; absent categories are represented accurately, not guessed.
5. Detail/sample limits are respected and partial results are explicitly identified.
6. Unsupported broader comparisons do not trigger privileged queries or fabricated counts.
7. Duplicate identical evidence/progress entries are absent, while distinct queries remain distinct.
8. Tool failures, truncation, and empty results render differently and truthfully.

Use the narrowest relevant commands documented by justfile/development.md. Do not claim checks passed unless they were run. Do not weaken existing tests or authorization to make a test pass. If a required behavior cannot be established from current code, state the exact uncertainty and choose the fail-closed behavior.

### Done when

- The end-to-end data path and role behavior are documented in the handoff with file references.
- Assistant answers cannot exceed the authenticated user's CRM scope and clearly distinguish totals, breakdowns, samples, and unavailable information.
- The duplicate evidence display is fixed at its root cause without collapsing distinct queries.
- Relevant focused tests/checks pass, and skipped checks are listed plainly.
- The final handoff names changed files, verified role behavior, test commands/results, remaining limitations, and any production decision still needed.
```

## Existing references

- [Assistant architecture](ai-assistant-architecture.md)
- [Assistant production review and security boundaries](ai-assistant-production-review.md)
- [Production architecture and launch gates](../production-readiness-2026-09-29.md)
