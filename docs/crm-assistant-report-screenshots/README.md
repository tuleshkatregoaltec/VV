# Screenshots for crm-assistant-current-state-report.pdf

**None of these is a live application capture.** Each is the real CRM Assistant frontend
(this repository, local Vite dev server on 127.0.0.1, 26 Nov 2026) with every API response
mocked in Playwright from the synthetic evaluation fixture (`crm_fixture.py`: Palm Crescent
Realty, `@example.test`). All other network requests were blocked. No real customer data,
credentials or shared databases were used.

| File | Role | Scenario | Where the shown content comes from |
| --- | --- | --- | --- |
| 01-interface-empty-owner.png | Owner | Empty CRM Assistant page | Mocked API (UI only) |
| 02-owner-lead-summary.png | Owner | Leads by status (crm001) | Recorded live-model answer, run 20261126T101605Z |
| 03-owner-team-change-proposal.png | Owner | Move agent between teams (crm132) | Real server proposal on a disposable synthetic DB |
| 04-manager-assign-proposal.png | Manager | Assign a lead (crm095) | Real server proposal + recorded live-model answer |
| 05-manager-assign-confirmed.png | Manager | After Confirm (crm095) | Real confirm_action result |
| 06-manager-stale-confirmation-failed.png | Manager | Lead changed before Confirm (crm177) | Real confirm_action result (snapshot recheck failed) |
| 07-agent-email-proposal.png | Agent | Email a lead (crm116) | Real server proposal (Brevo not configured) |
| 08-agent-email-not-connected.png | Agent | After Confirm (crm116) | Real confirm_action result (not connected) |
| 09-agent-bulk-contact-refusal.png | Agent | Bulk contact request (crm197) | Real input_refusal text; reload artificially delayed 2.5 s to capture it |
| 10-agent-refusal-after-refresh.png | Agent | Same, after the post-stream reload | Mocked empty message list (server saves nothing on refusal) |

Action timestamps were set at render time so cards are not shown as expired.
