# Bayut listings

This is an access-gated active-listings collector. It gathers the listing cards
rendered by Bayut search pages and writes both page-level evidence and
deduplicated listing records. It does not solve CAPTCHAs, rotate identities, or
attempt to bypass access controls.

Start with a single search path and page to verify normal permitted access:

```yaml
source_config:
  search_paths:
    - /for-sale/property/dubai/
  start_page: 1
  max_pages_per_search: 1
  request_pause_seconds: 3
  storage_state_path: /path/to/permitted-browser-state.json
```

The collector raises `BayutAccessBlockedError` if it receives a CAPTCHA page;
that is a deliberate terminal result for the run. A browser state file must be
obtained through an authorised normal session and is not a bypass mechanism.

Raw output:

- `bayut_listing_search_pages.jsonl`: request URL, final URL, status, card
  count, and complete HTML evidence for every fetched page.
- `bayut_listing_properties.jsonl`: deduplicated listing IDs, URLs, title,
  parsed price/size where visible, and complete card text.

`start_page` is a manual resume cursor. A run is not coverage-certified: a
future planner must first enumerate the permitted Dubai community paths and
verify pagination/result limits before claiming a full-site inventory.
