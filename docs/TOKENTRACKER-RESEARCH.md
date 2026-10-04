# TokenTracker time-window and model-history research

Inspected official source commit `17247d9d0c9e40eb958b03e638fc4a3978b52a83` on 2026-10-04 UTC. No authenticated account endpoint, local queue, session or token was accessed. This investigation used the official source and the previously authorized public snapshot of Perfecto's user ID only.

| Surface | Window / parameters | Access and completeness |
| --- | --- | --- |
| Public leaderboard profile | `user_id`, `period=week/month/total`, `tz`, `tz_offset_minutes`; no caller `from/to`, cursor or offset | `total` maps to 365 calendar days. Dense heatmap exposes models only within that window; favorite model is period-scoped. No earlier-history pagination. |
| Public cumulative SVG | User ID and theme | Leaderboard cumulative token snapshot and provider/tool shares; no per-model cumulative history. |
| Client date picker | Day/week/month/custom; `total` defaults to last 24 local months | A client presentation range, not an anonymous all-time endpoint. |
| Client local model route | `from`, `to`, source/device/timezone filters | Aggregates installed client's queue rows, not public user-ID history. Completeness would depend on local queue history; not read here. |
| Cloud account model route | `from`, `to`, device/timezone; start clamped to at most 1,095 days before end | Verifies JWT, derives account identity from it. A public user ID cannot replace authorization. No pagination token; aggregates one inclusive date interval. Multiple disjoint windows could only be combined after authorized login and verified history coverage. |
| Database model RPC | User ID, device, timestamp bounds, local-day bounds | `account_model_breakdown_compact` folds all source/model/tier rows for the interval. EXECUTE revoked from PUBLIC, anon and authenticated; granted to project_admin only. Not a public bypass. |

The public community-models function returns platform-wide community Top Models, not a single user’s model history; it cannot supply Perfecto’s all-time list. The profile `view=badges` shortcut is verified-owner-only and returns badges, not model totals. All-time Top 5 remains unavailable in public data. We do not label the 365-day heatmap, client 24-month preset, favorite model or provider shares as all time. No private route was tried without authorization and no blocked network route was bypassed.

## Source evidence

All links are pinned to the inspected source commit, so line references remain stable.

- [Client total preset: date-range.ts lines 83–86](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/src/lib/date-range.ts#L83-L86).
- [Client switches between local and cloud model fetchers, including from/to](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/src/hooks/use-usage-model-breakdown.ts#L113-L133).
- [Local model fetch](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/src/lib/api.ts#L631-L645) and [cloud model fetch](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/src/lib/api.ts#L989-L1006).
- [Local queue aggregation and inclusive date filter](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/src/lib/local-api.js#L2515-L2530).
- [Public profile window](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-leaderboard-profile.ts#L642-L664), [accepted query parameters](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-leaderboard-profile.ts#L753-L757), [fixed heatmap window](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-leaderboard-profile.ts#L872-L879).
- [Embed cumulative/provider columns](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-embed-svg.ts#L300-L310).
- [Account required from/to and range clamp](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-account-model-breakdown.ts#L667-L683), [JWT enforcement](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-account-model-breakdown.ts#L704-L705), [server-side aggregation without a cursor](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/dashboard/edge-patches/tokentracker-account-model-breakdown.ts#L605-L640).
- [Database inclusive local-day filter and restricted EXECUTE](https://github.com/xiufengsun/TokenTracker/blob/17247d9d0c9e40eb958b03e638fc4a3978b52a83/migrations/20260918043000_fold-account-model-breakdown-aggregation.sql#L60-L72).

## Published AI snapshot

Rolling inclusive UTC window 2026-09-05–2026-10-04: 20,772,897,628 tokens across 11 models, daily mean 692,429,920.9333333. Only Top 5 names/counts and 30 daily total values are stored in this repository. Daily model dictionaries and remaining model details stay local. The cumulative 59.53B official display is rounded and separately captured. No exact cumulative sum or cumulative-model reconciliation is claimed.
