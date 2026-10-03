# Broker workflow assistant

This follow-on is based on PR #13 (`f6f9377`). It preserves authenticated MCP,
turn accounting and market release gates. It does not alter canonical ingestion,
coverage, publication or Claude's databases. Market questions remain supported;
the broker operations use the existing CRM services and stored candidates.

## Working flow

1. Ask for your enquiries or an identified client brief. `mine` means assigned to
   you, plus self-created enquiries that remain unassigned. Reassignment revokes
   the creator's access. Organization scope requires current owner membership.
   Counts distinguish enquiries from distinct stored contact IDs; they are not
   an inferred deduplication of real people.
2. Request properties for a buy/rent enquiry, or clients for a sell/let property
   enquiry. Existing matching supplies candidates. Every populated requirement
   is checked; unknown/unsupported requirements stay under review, not suitable.
   Optional additional constraints intersect the stored brief and persist across
   tools in the turn. Inclusive/strict budgets preserve equality and cents.
   Rankings are not conversion probabilities. Candidate scans are bounded and
   explicitly not exhaustive; reverse refresh considers at most 25 authorized
   qualified enquiries.
3. Generate a presentation, comparison, seller evidence pack or draft quotation
   from selected authorized property match IDs. Chat displays the same immutable
   structured snapshot used by the PDF worker. References, versions, validity,
   units, evidence dates and missing information are retained. Seller packs reuse
   linked CRM property reports for recorded comparables only; their assumed
   selling costs, agent signals and unsupported valuations are excluded.
4. Review a daily follow-up summary, viewing brief or draft message. A note/task
   request creates a persisted proposal. Only the authenticated **Confirm action**
   button applies it, atomically and idempotently after checking current access
   and the enquiry version. Nothing sends messages, contacts clients or changes
   their workflow status automatically.

Current-interest confirmation requires explicit `confirmed_data.current_interest`
and `interest_confirmed_at`. It describes that recorded time, not a guarantee.
A disclosed 30-day threshold marks ageing evidence; a new note does not refresh
old interest. Open enquiries, stale records and unknown intent remain distinct.
Do-not-contact/withdrawn consent prevents outreach drafts.

## Quotation and media boundaries

Quotations currently use AED recorded asking prices. No FX conversion, assumed
fees, discounts, payment plans or availability is introduced. Charges use Decimal
arithmetic and half-up cent rounding, with separate known/estimated subtotals.
A missing price or charge prevents a complete total. Alternative properties are
never summed into one quotation; duplicate charge labels are rejected.

Chat charges require an unambiguous current broker message, for example:

```text
Brokerage: 2%; Administration (estimate): AED 500.50
```

The server checks the actual user message, not model assertions or tool output.
To remove the unknown-charge placeholder, explicitly supply `Charges complete: yes`
only after all applicable charges are supplied. REST creation fields are explicit
broker inputs. No approved organization fee schedule is currently configured.

Approved media enters through authenticated `POST /api/v1/crm/broker/media`, with
an authorized enquiry/match, `kind=image|floor_plan`, `approved_for_client=true`
and a PNG/JPEG file. Inputs are limited to 4 MiB/16 megapixels, decoded and
re-encoded without metadata. Use returned IDs in document creation. Remote URLs,
SVG/HTML, arbitrary object keys and filesystem paths are not accepted. The renderer
never fetches source URLs. Media approval/upload is currently API-only; the chat
preview shows property facts but does not display media. Approved media is embedded
in the downloadable PDF.

Documents use scalar property allowlists, excluding internal notes, owner/broker
contact fields, source descriptions and unrelated client data. Brokerage branding
comes from the authenticated organization's name. Downloads and media access
require current organization/enquiry authorization; object keys are never public
permissions. The included embedded font rejects unsupported glyphs rather than
silently corrupting text; Arabic and other unsupported scripts need a reviewed
font/shaping extension before such documents can be generated.

## Durable operation and data handoff

Apply application migration `c7a941ef2b30` through the normal migration workflow.
It adds document jobs, approved media metadata and action proposals only; no
canonical warehouse schema changes are required.

Configure `BROKER_DOCUMENT_STORAGE_BUCKET` as a **separate private bucket**, using
existing object-storage credentials/endpoint settings. Public bucket policies must
be disabled. Give the runtime access only to its CRM prefixes, and configure
retention/backup according to the enterprise's policy. An absent or reused public
media bucket fails closed; no fallback writes to public storage occur.

Run `just broker-documents-worker` as a supervised application worker, or
`just broker-documents-worker --once` for at most one queued job. PostgreSQL owns
status and immutable input; workers claim with `FOR UPDATE SKIP LOCKED`, a 90-second
lease, a 60-second execution limit and at most three claims after interruptions.
Claim tokens fence late workers; a worker crash leaves a reclaimable job. Explicit
render/storage failures are persisted, not reported as completed. Retrying a failed
request requires a new document idempotency key. Request retries with the same key
return the original snapshot; changed input with the same key conflicts.

The worker and private bucket must be provisioned before enabling PDF generation
for users. This PR performs no production migration, deployment or provisioning.
Chat uses bounded status polling; a document is downloadable only after completion.

Claude's `acquire_market_release(context)` handoff from PR #13 remains unchanged:
every market query must be pinned to immutable source versions, with authoritative
source/period coverage and concurrent-turn isolation. This expansion does not
fabricate release coverage or enable unsupported market yields. Stored CRM match
snapshots have their own recorded dates and are not promoted to authoritative
canonical releases.

## Demonstration and verification

The connected fixture enters through the real authenticated MCP protocol, reads
an authorized two-bedroom client, rejects listing candidates at/above the strict
AED 1.2m ceiling, and selects the AED 1.1m listing. It approves a synthetic image,
queues quotation version 2, renders a PDF, and downloads it through the actual
protected API route. An independent PDF parser verifies the same reference,
property facts, AED 22,000 brokerage, AED 500.50 estimated charge and AED 1,122,000
known subtotal as the persisted chat preview. A missing transfer charge leaves the
complete total unavailable. Private notes/contacts/source URLs are absent.

The PostgreSQL/private-object-storage test separately applies the real migration,
reclaims interrupted leases, fences an old worker, generates/downloads the PDF,
and verifies anonymous object access is denied. Other fixtures cover assignment,
owner scope, exact client/enquiry counts, explicit confirmation/idempotency,
strict matching and frozen requirements in viewing briefs/drafts.

Representative q201–q214 inputs and expectations extend the existing evaluation
runner; q01–q15 remain unchanged. Deterministic fixture passes are not model-quality
passes. See `EVALUATION.md` for targeted live results, spending and check outcomes.
