# Calendar visibility by organization role

## Goal

Implement the requested calendar view in the existing CRM:

| Signed-in person | Events they can read |
| --- | --- |
| Owner / organization admin | Events for every member of their organization, including people outside teams |
| Manager (team supervisor) | Their own events and events for members of the team(s) they supervise |
| Agent (team agent or ordinary member) | Their own events only |

The server must decide this for every request. A URL parameter, hidden UI control, or user ID supplied by the browser must never grant visibility.

## Assumptions to confirm with the client

1. “Meetings” means calendar appointments/events of all current kinds (`viewing`, `call`, `follow_up`, `deal_date`, and `deadline`). There is no separate meetings table or meeting event kind. `meet` is the Google Meet option on an event.
2. Organization admins should receive the same organization-wide read view as owners. This matches their existing CRM administration scope.
3. Shared events are read-only for other people. Each user can continue to edit, reschedule, complete, and delete only their own events.
4. Treat events marked `private` or `confidential` as busy blocks for other viewers. The client must decide whether `default` events are also shared with full details; the proposal below shares their details within the allowed role scope.

If the client means only events with guests or a Google Meet link, narrow the event set after confirming that requirement. Do not infer “meeting” from the `meet` boolean: that would omit ordinary scheduled appointments.

## What the project does today

- `CrmCalendarEvent` is stored in `crm_calendar_events` with both `organization_id` and the owning `user_id`. Its existing owner/date index already supports bounded per-user calendar reads. See [`calendar_models.py`](../backend/app/crm/calendar_models.py) and migration [`f2b4d6e8a0c1_add_crm_calendar.py`](../backend/migrations/versions/f2b4d6e8a0c1_add_crm_calendar.py).
- `GET /api/v1/crm/calendar/events` calls `calendar_service.list_events` for the authenticated user and organization only. `GET /calendar/events/{id}` uses `_own_event` and also allows only the event owner. Calendar writes use `_own_event` too. See [`router.py`](../backend/app/crm/router.py) and [`calendar_service.py`](../backend/app/crm/calendar_service.py).
- Organization membership roles are `owner` and `member`. A manager is represented by `OrganizationTeamMember.role == "supervisor"`; agents have team role `agent`. A person may be a supervisor in one team and an agent in another. See [`organization/models.py`](../backend/app/organization/models.py).
- [`assignment.load_scope`](../backend/app/crm/assignment.py) already derives the authenticated member's organization-admin status, supervised teams, and members of those teams. Reuse this authorization source instead of creating a second role system.
- Google Calendar connections and encrypted refresh tokens are per `(organization_id, user_id)`. The OAuth state is bound to the same user and organization. Connecting Google Calendar currently connects the signed-in person's calendar, not a shared organization calendar.
- `calendar_service.list_events` performs Google sync and pending Google writes for that one user before returning events. Calling it once per visible team member would make a manager/owner page trigger many provider calls and could cause slow loads or rate limits.
- Event responses contain sensitive details (title, description, guest emails, location, Google Meet URL, and linked record). The existing `visibility` field is not currently used to redact cross-user event reads because cross-user reads do not exist yet.
- The frontend calendar uses the typed `crm.events.list/get` wrappers and the same list helper feeds Home counters. `EventPanel.svelte` currently always offers edit, reschedule, done, and delete controls. Any added shared-view response must update these callers and make shared events read-only in the UI; backend write checks remain mandatory.
- Chat's [`connector_tools.py`](../backend/app/chat/connector_tools.py) uses `calendar_service.events_between` for the signed-in user's calendar. Keep this connector own-only; do not broaden it as part of the UI calendar change.

## Recommended implementation

### 1. Derive the readable user IDs on the backend

In the calendar event-list route, get `user_id` and `organization_id` only from `AuthContext`, then call `assignment.load_scope(db, organization_id, user_id)`.

- If `scope.organization_admin` is true, load **all** `OrganizationMembership.user_id` values for this organization. Do not rely only on `scope.team_members`: an organization member may not belong to any team.
- Otherwise, start with the signed-in user's ID. If they supervise one or more teams, add the user IDs in `scope.team_members` for those supervised teams. This gives a manager their own events plus their supervised teams' members' events. It does not include their other, non-supervised teams.
- If neither condition applies, the set contains only the signed-in user's ID.

Use the existing membership repository (`organization.repository.list_memberships`) for the admin population and the existing assignment scope for team membership. The resulting IDs are server-derived and organization-scoped.

### 2. Query stored events without syncing every person's Google account

Add a role-scoped read path that selects stored `CrmCalendarEvent` rows with all of these predicates:

```text
organization_id = authenticated organization
user_id IN server-derived readable user IDs
event date overlaps the requested bounded range (including existing repeat/reschedule rules)
done = false (preserve current calendar behavior)
```

Keep the current maximum range validation. Do not accept an arbitrary `user_id`, `team_id`, or role/scope from the browser. Do not call Google with another person's refresh token. Preserve the existing event ordering, recurring occurrence expansion, and moved-slot history.

The current user's Google sync can remain as it is, but do not call `list_events` once per visible user. For other users' connected Google calendars, choose one freshness policy before shipping:

- **Recommended for role visibility:** return the last locally synchronized copy and show its last-sync/staleness status; synchronize each connection through a bounded scheduled job using its stored Google sync token.
- If no scheduled sync is available, clearly disclose that other users' Google events may be stale until those users open/sync their own calendar. The architecture notes that the HTTP app does not have a durable general-purpose worker, so do not disguise an unawaited request task as durable sync.

The existing per-user Google connection UI can stay unchanged. A manager/owner should not see or use another person's connection credentials, and disconnect remains scoped to the current user.

### 3. Apply privacy before serializing events

Return the event owner ID and display name (currently `agent` is hard-coded to `"You"`) so the calendar can identify whose event is being shown. The server should also communicate whether this viewer may edit the event, or otherwise provide an equivalent typed ownership marker.

For the event owner, keep the current full response. For another viewer:

- For `private` or `confidential`, return only a busy block (date/time, end, all-day, and busy/free status). Replace the title with a generic label such as `Busy`; remove description, guest list, location, Meet link, linked lead/listing/record information, and other identifying details.
- For `default` and `public`, use the client-approved sharing rule. The recommendation here is full event detail for members who are already in the viewer's authorized role scope.
- Before exposing a linked lead or record to someone other than its event owner, verify that the viewer may currently see that CRM record using the existing assignment visibility rules. If not, omit the linked record fields while retaining the event if policy allows.

Do not treat Google guest permissions as CRM authorization. They describe what event invitees can do, not which CRM roles can read the event.

### 4. Scope event detail reads and keep writes owner-only

Change `GET /calendar/events/{event_id}` to find the event only when both its organization is the authenticated organization and its owner ID is in the server-derived readable set. Return 404 for missing, cross-organization, and out-of-scope events, consistent with `_own_event`'s existing non-disclosure behavior.

Keep `_own_event` on create-related linked-resource checks and all mutation routes (edit, move, complete, delete). A manager/owner who can see another person's event must not be able to change it. If shared event editing is later requested, it needs a separate policy and careful handling of which user's Google connection receives the write.

### 5. Update the existing frontend consumers

- Keep using the existing typed API wrapper and TanStack Query keys. The server should return the role-scoped list from the same `/calendar/events` endpoint, so calendar navigation and Home's week counters naturally use it.
- Add the required owner/display and editability fields to the backend response schema and frontend `CalendarEvent` type/client. Regenerate the generated API client if the repo's client workflow covers this schema.
- Label shared events with the owner's name. Preserve the current event type/color and date presentation.
- In `EventPanel.svelte`, show event details according to the response policy. Show Edit, Reschedule, Mark done, and Delete only for the event owner. This is usability only; backend writes must still reject non-owner attempts.
- Keep Google connect/disconnect controls for the signed-in user's own account; they do not represent the shared team view.
- If privacy redaction is server-side, the UI must never receive the hidden data in the first place. Do not fetch broad data and hide it in Svelte.

## Files and existing tests the change reaches

Expected backend touch points:

- `backend/app/crm/router.py` — derive scope for event list and detail; leave writes owner-only.
- `backend/app/crm/calendar_service.py` — bounded multi-owner stored-event read and viewer-aware response serialization; keep Google push/sync ownership intact.
- `backend/app/crm/calendar_models.py` — response fields only if needed; no new event table is required for role visibility.
- `backend/app/organization/repository.py` / existing `assignment.py` — reuse membership and team scope helpers rather than duplicating role lookup.

Expected frontend touch points:

- `frontend/src/lib/crm/api/types.ts` and `frontend/src/lib/crm/api/backend.ts` — typed response fields and API mapping, if required.
- `frontend/src/lib/crm/api/index.ts` — update the description that currently promises a signed-in user's own calendar.
- `frontend/src/lib/crm/components/panels/EventPanel.svelte` plus calendar event display components — label shared events and hide other users' mutation controls.
- `frontend/src/routes/crm/calendar/+page.svelte` — only if a last-sync indicator or role-specific explanatory copy is needed.

Existing relevant checks are `backend/tests/api/test_crm_calendar_email_routes.py`, `backend/tests/unit/test_crm_calendar_oauth.py`, `backend/tests/integration/postgres/test_crm_calendar_sync.py`, `frontend/tests/unit/crm-calendar.test.ts`, and `e2e/guards/crm-calendar-email.spec.ts`. Add focused visibility tests before implementing this behavior; do not weaken the current OAuth ownership and sync tests.

## Required authorization tests

Use at least two organizations and multiple users/teams. Verify both list and detail endpoints:

1. Owner and organization admin see all same-organization events, including members with no team, but never another organization's events.
2. Manager sees own events and all events from supervised team(s), including another supervised team's users if the manager supervises both; manager does not see unsupervised teams or members with no team.
3. A manager who is also an agent on a different team does not gain that other team's events unless they supervise it.
4. Agent sees only their own events.
5. Supplying or guessing another user, team, organization, or event ID cannot extend access; unauthorized event detail returns 404.
6. Another user's private/confidential event exposes only the approved busy-block fields; owner still receives full detail.
7. Owner/manager write attempts against another person's event still fail, including direct API calls that bypass UI controls.
8. Listing a shared calendar does not call Google sync or pending-event push for each other user. Each Google OAuth connection and sync remains bound to its owner.
9. Chat calendar tools still return only the signed-in user's events.

## Deployment and rollout notes

- No new calendar table or data migration is required for role visibility; event rows already carry organization and owner IDs. Add a migration only if product decisions require a new persisted sharing policy or synchronization status.
- Google Calendar API/OAuth credentials, redirect URI, token encryption key, and consent configuration are already required for the existing connect option. They do not need to be shared with managers.
- If the client expects other people's Google changes to appear promptly, deployment needs an actual durable scheduled sync mechanism and monitoring. The current page-load sync is per-user and is not a safe team-wide freshness mechanism.
- Keep organization ID predicates on all reads even though membership/user ID sets are scoped. Revisit indexes only after query plans and realistic organization data show a need; the existing `(organization_id, user_id, event_date)` index is a useful starting point.

## Suggested build order

1. Confirm the assumptions above: what “meeting” includes, organization-admin behavior, private/default sharing, and acceptable Google sync freshness.
2. Implement backend-derived visibility IDs and scoped list/detail reads; retain owner-only writes.
3. Add response redaction and event owner/editability metadata.
4. Add authorization/privacy/provider-isolation tests.
5. Update the calendar and Home event consumers, then test owner, manager, and agent UI flows.
6. Configure and monitor scheduled Google sync if near-real-time team visibility is required.
