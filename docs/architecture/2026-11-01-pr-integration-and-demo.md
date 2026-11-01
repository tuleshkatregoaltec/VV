# PR integration and enterprise assistant demo

The enterprise preview is an interactive **sample-data demonstration**, not an enabled
mail, calendar or WhatsApp integration. The user confirmed that provider registrations,
credentials, callbacks and KMS do not exist yet, and requested a presentation-ready
preview. Supabase authentication is separate and unchanged. PR #50 remains draft until
its real connectors satisfy the production architecture and can be qualified.

## Present the demo

Run `just demo-assistant` and open <http://localhost:5173/demo/assistant>.
Only the frontend is needed: no backend, database, provider credentials or model calls.
The authenticated CRM sidebar also has **Connectors → Open enterprise demo**.
The standalone preview requires no login and displays only fictional sample records.
Only its exact public route is allowlisted; neighboring routes and real CRM remain guarded.

1. Start with the sample portal enquiry. Review its extracted fields and approve the lead.
2. Request a viewing through Sara's private WhatsApp assistant.
3. See the 15:00 calendar conflict and choose 16:30 or 17:30, explicitly in Dubai time.
4. Review the proposed booking, independently choose an invitation and customer reply,
   and edit the exact reply before approving in the demo.
5. Inspect the simulated receipts and the separate customer inbox. Restart to repeat.

Manage the connection cards to preview Gmail/Outlook, Google/Microsoft Calendar and
both WhatsApp modes. Disconnecting a sample account blocks advancement. Changing an
approved time invalidates the sample approval. Presenter mode reduces introductory
chrome; light/dark appearances and narrow screens are supported. Reload or Restart
clears the in-memory scenario. Nothing is stored, sent, invited or booked externally.
The fixed November 2026 calendar belongs to the fictional scenario.

## Reconciliation decisions

| PR / source | Integration decision |
| --- | --- |
| #51 | Retain reviewed analytics project aliases and host startup fixes. |
| #52 → #53 → #54 | Retain the current property-first matcher, broker exclusions, durable imports, source revisions, tenant caches, admission and database audit. |
| #13 → #25 | Superseded assistant code is reconciled with the 31 October shared-workflow implementation. Record ancestry without restoring the old PDF pipeline, MCP implementation or separate conversation state. File generation remains disabled. |
| #50 through `9f0130e` | Integrate distinct CRM matching, company-inventory and recent-seller improvements; preserve newer owner-import policy and tenant caching where they conflict. |
| #50 connector/assistant prototypes | **Not merged.** Local JSON email persistence, a duplicate CRM assistant, preliminary Google Calendar and WhatsApp demo paths do not satisfy the production connector plan. |
| `3b8561b` review snapshot | Preserve the shared assistant, scoped retrieval, persisted action approval, accounting and output guards; supply missing reliability and integration fixes. |

The company-inventory DTO is not a PostgreSQL listing store: current inventory is read
from bounded warehouse queries. Only the organization-selected broker is persisted.
Its source-selection table receives the existing transactional audit and truncate guards.
Company lookups preserve latest availability, broker filters, parameter binding and annual
rental prices. Private assistant authorization remains independent of general CRM visibility.
The existing ownership assessment and exact-name protections also apply to recent-seller
owner-key retrieval. Empty matching GETs stay read-only.

Recently-sold Inbox synchronization is currently an explicit maintenance operation via
`backend/scripts/crm/sync_recently_sold_inbox.py`, not an HTTP-upload side effect. The
synchronous prototype's automatic import/rematch hooks are not carried into the fenced
worker. Production scheduling, realistic capacity and recovery must be qualified separately.

## AI chat reliability and schema

Buffered responses now send SSE comments every 15 seconds. Comments contain no private
model output. Closing the HTTP stream cancels and awaits nested work and admission
settlement before releasing the request session. The frontend requires an explicit `done`
or `error`; premature EOF produces an error instead of manufacturing completion.

The independent CRM and chat migration heads are joined by `e1f5b2c7a940`, followed by
the retained company-source and recent-seller index migrations. Unshipped duplicate-chat
migrations from #50 are omitted; the company-source predecessor is corrected to the
joined chain. Existing deployed migration files from the reviewed CRM/chat stacks are
unchanged. OpenAPI, generated frontend types and contract snapshots are refreshed together.
Only disposable databases were migrated in verification; no app/production migration ran.
The AI usage-ledger cutover and durable-import worker rollout still require their documented
controlled release sequence.

## Verification

- Canonical `just check-all`: 1,698 backend tests and 374 frontend tests passed, no skips.
- Disposable PostgreSQL: 136 passed, including the joined migrations, assistant authorization,
  CRM fencing, current assignment, source selection and audit boundaries.
- Disposable ClickHouse: 110 passed, including current broker inventory, latest availability,
  annual rent conversion and literal injection inputs.
- Analytics alias tests with local ClickHouse enabled: all 9 passed, no skips.
- Demo/chat browser checks: 9 passed, including zero application API requests from the public
  demo journey, exact edited replies, separate invitation approval, customer/private separation,
  reconnect gating, reset, new approval after a time change, 375/768/1024/1440px, both themes,
  and interrupted/heartbeat chat responses.
- Holocron full check: lint/type checks passed; 591 tests passed, **34 optional integration
  tests skipped**, with one existing collection warning. Skips are not passes.
- Full mocked route-guard browser suite: all 30 passed, including the 9 demo/chat checks
  above, CRM/Market theme parity, grouped navigation, source disclosure and queued imports.
- Backend/frontend lint, zero-error/zero-warning Svelte diagnostics, canonical client
  regeneration and frontend production build passed. Browser runtime libraries were
  extracted under `/tmp`; no system install.

Passing source and sample tests is not provider qualification. Real OAuth consent, encrypted
server grants, single-use callbacks, scoped durable intake, phone-possession linking,
customer/agent isolation, booking conflict rechecks and uncertain-delivery reconciliation
remain required before enabling production connectors. No live model comparison, external
send, booking, deployment or security-certification claim is made.
