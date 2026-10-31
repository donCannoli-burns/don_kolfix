# Don Report v1 — canonical observation address and independent sources

**Implementation stage:** core schema, human CLI read-only probes, KoLFix off-by-default controls, and an explicit host-side immutable JSON receipt writer. No automatic relay hooks, Excavator replacement, Philter/CONSUME execution, market scrapes, change notifications, or login callbacks.

## Formal namespace

```text
donstate:v1:<numeric-player-id>:<KoL-rollover-YYYYMMDD>:<lifetime-ascensions>:<domain>:<type>/<numeric-ID>:<metric>
```

Examples, where 12345 is a **fixture**, not a real player:

```text
donstate:v1:12345:20261030:32:inventory:item/13:quantity
donstate:v1:12345:20261030:32:economy:item/13:estimated_meat
donstate:v1:12345:20261030:32:skills:skill/456:current
donstate:v1:12345:20261030:32:organs:organ/1:liver_used
donstate:v1:12345:20261030:32:relay:relay/1:capture_enabled
```

Canonical node identity **does not contain a source name**; each independently sourced claim stores its own `source`, `evidence`, `id`, timestamp, scope and receipt ID, allowing multiple sources to observe the same node without overwriting each other. `projectReports()` detects disagreement as `conflict`, not last-writer-wins.

States: `observed` (bounded typed actual reading), `known_unknown` (specific fact couldn't be established), `ignored` (operator policy), `unobserved` (no report), and `conflict` (irreconcilable claims). None is a Don State workflow `finished` flag. A value is only permitted with `observed`; negative absence claims require actual coverage.

Sources: `accountval`, `philter`, `greenbox`, `consume`, `chit`, `excavator`, `watersheep`, `custom_ash`. Domain and metric names use `[a-z][a-z0-9_]*` up to 40 characters. Subject uses `type/positiveID`. No arbitrary paths, account page HTML, personal messages, tokens, URLs, secrets, or unknown source names.

## JSON record and path

```json
{
  "schema": "don-report-v1",
  "id": "philter0001",
  "address": "donstate:v1:12345:20261030:32:inventory:item/13:quantity",
  "scope": {"playerId": "12345", "day": "20261030", "life": 32},
  "node": {"domain": "inventory", "subject": "item/13", "metric": "quantity"},
  "source": "philter",
  "state": "observed",
  "evidence": "cached",
  "value": 2,
  "observedAt": "2026-10-30T20:45:00-05:00",
  "reason": null,
  "receiptId": null
}
```

Given an explicit KoLmafia **data directory** root, independent records live at:

```text
<root>/d_data/d_<source>/<player>/<rollover>/life-<ascensions>/<receipt-id>.json
```

For an Xpra installation this could resolve to `.../kolmafia-xpra/data/d_data/d_accountval/12345/20261030/life-32/accountval0001.json`. The canonical index is an **in-memory projection** of validated source records, never a file another script is permitted to overwrite. This is separate from the existing Don State Engine v0.2/v0.3 `don_Data/state-engine/` journals.

## KoLFix pref governance

Explicit `kolfix reportInit` (not normal startup) initializes all of these **OFF**:

- `donReport_collectionEnabled`, `donReport_relayCaptureEnabled`, `donReport_recordEnabled`
- `donReport_diffEnabled`, `donReport_printChanges`, `donReport_notifyDiff`
- `donReport_source_accountval`, `..._philter`, `..._greenbox`, `..._consume`, `..._chit`, `..._excavator`, `..._watersheep`, `..._custom_ash`

`kolfix reportStatus` and `kolfix reportVerify` are read-only. These toggles **never themselves authorize network access, Kmail, file writes, gameplay or relay override registration**. A producer must still implement and receive an explicit operator-approved host adapter. `kolfix session` now ignores both `donState_*` and `donReport_*` keys during session restore.

## Operator-invoked Don Report commands

Once locally rebuilt and installed, use the **separate** bundled script:

```text
call kolfix/don_report.js help
call kolfix/don_report.js skills_current --quiet
call kolfix/don_report.js organ_state --print
call kolfix/don_report.js relay_state
call kolfix/don_report.js spading_state
call kolfix/don_report.js item_value 1000000
call kolfix/don_report.js item_new --diff
```

The command name `don_report` can later be defined using KoLmafia's alias mechanism, but don't set an alias until the local script path is verified. The CLI parses only known report commands and options; it **never delegates to executable cleanup/consumption scripts**. Currently `skills_current` reads available skills, `organ_state` reads cached organ use, and `relay_state` / `spading_state` show current hook policy. `item_value` returns a known-unknown without making a market request; `item_new` returns a known-unknown without a verified prior inventory receipt. `--diff` currently reports a missing baseline, not a fabricated difference. `--quiet` suppresses node-by-node printing but not the summary.

## Explicit host JSON recording (not hooked into live scripts)

To test the receipt writer with a **synthetic** file:

```bash
python3 tools/don-report-store.py --root /path/to/kolmafia/data --input /path/to/fixture.json --plan
```

`--plan` validates JSON and prints a proposed path without creating directories. `--write` is a separate explicitly invoked mutation, requiring that the root already exists. The Linux host writer uses per-scope `flock`, fsync, atomic no-clobber hard-link publication and exact-readback verification. It refuses symlinked record directories, mismatched same-ID data, unknown sources, unsafe values and malformed identities. Do not point the writer at a live profile without first reviewing the input and confirming the specific root/path. It **does not** yet provide a journal queue, record rotation, or a bridge from ASH/TS scripts; those still need separate approval and runtime tests.

## Integration ownership and safety

| Fork | Intended read-only owner | Mutation boundary |
| --- | --- | --- |
| `don_accountval.ash` | `item_value` and valuation | Price fetches require explicit authorization; actual sold profit is different |
| `don_philter` | `item_new`, inventory deltas | Never call cleanup planner/executor from a report |
| `don_greenbox` | `skills_current`, item/skill/familiar ownership | Must not Kmail/upload a profile during a report |
| `consume.ash` | `organ_state`, consumption plans | No consumption, crafting, or `cli_execute` in a report |
| `don_ChIT` | Relay cache observations, UI toggles | Preserve ChIT's `charpane.ash`; opt-in capture only |
| `excavator` | Passive spading events | Existing `spadingScript=excavator.js` stays untouched |
| `watersheep` | Advisory inference | Never turns model predictions into observed player state |
| `custom_ash` | Typed plugin facts | Same scope, privacy and privilege restrictions |

The same address is used by all producers; no producer owns the current canonical truth. A timestamp alone cannot prove freshness, and preferences are not server receipts.

## Deployment gates

1. Run pinned contract/host tests, KoLFix lint and typecheck, and fresh local build; verify installed `don_report.js` can execute read-only.
2. Verify ASH fork adapters individually in a test KoLmafia profile, without installing relay hooks or running cleanup/consumption.
3. Implement a guarded, explicitly activated ingestion bridge to the host writer; never write directly from ASH via destructively overwriting `buffer_to_file`.
4. Add verified previous/current receipt comparison before enabling `--diff` notifications, and operator authorization for market/network probes.
5. Map evidence to SVG node colors only after separating source evidence status from workflow flag codes.
