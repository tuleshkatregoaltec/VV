# DLD lease date correction (2026-10-07)

## What was wrong

DLD publishes lease dates without a time of day. The rents load `2026-06-14T17-37-27Z` ran on a
machine set to UK time; the bronze loader passed naive datetimes to the ClickHouse client, which
read them in the machine's timezone. In UK summer time every midnight was stored as 23:00 the
evening before, so leases starting 30 March – 25 October 2026 in that load were one day early.
No other DLD load is affected (every other rents load stores midnight; DLD sales registration
hours show no seasonal shift).

## What was changed

- Loader: `holocron/platform/bronze.py` stores a time without an offset as written, in any machine
  timezone (`2084bb1`).
- Data: in `dld_od_rents_bronze`, run `2026-06-14T17-37-27Z` (428,460 leases), registration, start
  and end dates were moved forward by the UK clock offset at that instant (one hour in UK summer
  time, none otherwise). Result: 178,502 start dates and 185,588 end dates one day later, 203,041
  registration times one hour later (515 registration dates changed day). Nothing else changed.
  Done by copying the run with corrected dates under a temporary run id, deleting the originals and
  restoring the run id; the table total was unchanged (10,493,181).
- Market layer: a DXBI lease takes the DLD area its own location text ends with ("District 7,
  Jumeirah Park, Al Thanyah Fifth") before the learned community mapping (`9cd8960`).
- Rentals release `cb1de168e186` published with all 11 checks passing and one accepted failure,
  recorded in the ledger: `days_lost` on 11 Apr 2026 by registration date (352 → 69), because the
  DXBI leases on that Saturday now pair with their DLD records and take DLD's registration date
  (`4af44f7`).

## Verification

| | Start on the 1st | Start on the last day | End on the last day |
|---|---:|---:|---:|
| Moved leases, as stored before | 2.4% | 27.5% | 3.2% |
| Moved leases, corrected | 27.5% | 2.4% | 27.5% |
| Other DLD loads, Apr – Oct 2025 | 25.1% | 2.3% | 25.2% |

DXBInteract agrees with the corrected dates: of moved leases matching a DXBI lease (same contract
amount, start and end) on only one version, 59,355 match the corrected dates and 895 the old ones
(98.5%).

Effect of the new release against `51e25927b1d5`: 11,038 leases counted twice (DLD with the wrong
date and DXBI) are counted once (10,334,201 → 10,323,163 served); DXBI–DLD pairs 1,133,227 →
1,267,606; DXBI-only leases 17,120 → 6,089; leases move to their correct month (March 2026 −16,290,
June +7,588; the 2026 total changes only by the 11,038 duplicates). The Analytics API matches the
served tables on 63 of 63 recomputed figures.

## Date decisions (2026-10-07)

- A rental counts in the month its lease starts.
- A sale is dated by its transaction date: DXBI's where DXBI lists the sale, otherwise DLD's.

## Not changed

- About 3,200 leases where DXBI shows a start one day earlier than DLD (DXBI's own dates match its
  website; the product shows DXBI's date for these leases).
- DXBI sales loaded from DXBI's CSV export in August 2026: about a third differ from DXBInteract's
  list by a day in either direction, which is not a timezone shift; a re-scrape of August fixes it.
