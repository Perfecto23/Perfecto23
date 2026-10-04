# Profile maintenance

The README is native editable Markdown with contiguous HTML `details` and local SVG `picture` resources. The generator owns only the `AUTO:AI`, `AUTO:PROJECTS` and `AUTO:ACTIVITY` regions. Other prose and all five technology categories are preserved.

## Rebuild and validate

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate.py
python3 scripts/refresh.py
```

Offline rendering retains saved capture times. To reproduce the current snapshot without a later UTC stale label, pass `--as-of 2026-10-04`. Later rendering truthfully marks older captures and a window that does not include the requested date. `--fetch` requests only documented public sources; it never logs into TokenTracker. Failed/empty/incomplete sources keep valid last-good data. Provider-error SVGs cannot replace valid cards. Independent AI `Total` and `30d` freshness are stored in `sources/source-status.json` and displayed separately.

Approved raw inputs can be passed using `--profile-json local-inputs/profile.json` or `--bundle-json local-inputs/bundle.json --expected-sha256 HASH`. `local-inputs/` is ignored. Imports validate daily/model sums before retaining only the publishable summary. Never add a raw profile, Library bundle or authenticated client export to Git. Raw source responses remain in memory during fetching.

## Data definitions

- AI rolling window: UTC today and preceding 29 calendar dates, all 30 rows required. Totals and average include every model; only the five largest models are retained for display. Percentages use the full total, not displayed-row sums. Daily heatmap stores total tokens only. Window-end day is partial; missing dates cannot be silently filled.
- Cumulative AI headline: separate official embed capture, rounded provider display; current 59.53B is not the 365-day profile total. Estimated cost is not actual payment. Full all-time model history is not anonymously available; see [source research](docs/TOKENTRACKER-RESEARCH.md).
- Contributed projects: public merged authored organization-upstream projects, deduplicated, excluding personal/self/company/fork repositories. README shows names only; no PR numbers, descriptions or achievement history.
- Activity Graph: preceding 365 complete UTC days, excluding today. GitHub calendar events may contain anonymous private contributions and are not commit counts. Current window 2025-10-04–2026-10-03: 3,053 events, 250 active days.
- Streak, readme-stats, language/summary cards and overview retain their official provider definitions. Their counters have different time windows and inclusion rules; never combine them into one scope. Canonical stats rank B− and original deployment A+ are separate provider snapshots.
- Original trophy provider was unavailable; source-generated public milestones retain that module's place. Snake refreshes from the existing output branch and retains animation keyframes while applying purple/cyan theme colors.

Sources: [original profile README](https://github.com/Perfecto23/Perfecto23/blob/master/README.md), [Readme Stats](https://github.com/anuraghazra/github-readme-stats), [Streak Stats](https://github.com/DenverCoder1/github-readme-streak-stats), [Profile Summary Cards](https://github.com/vn7n24fzkq/github-profile-summary-cards), [TokenTracker](https://www.tokentracker.cc/u/b6f3aece-2e2d-4764-91aa-963aa814aca0). Individual image source URLs/capture times are in public manifests.

## Themes and Typora

Fixed dark/light SVGs use purple, indigo and cyan; language colors and technology brand colors stay intact. GitHub picture markup selects the fixed variants; adaptive fallback uses internal CSS and `prefers-color-scheme`. Actual Typora Github and Night themes were visually checked locally. After external regeneration while Night is active, newly loaded adaptive images can briefly use light state until Night is reselected. No global settings were changed. `preview/README-Typora.md` is a generated fixed-dark local alternative; it contains the same prose/modules and remains dark across refreshes. Main README keeps both palettes. The unpublished new README has not been verified on the GitHub website. Local QA screenshots and raw data stay outside this repository.

## CI

PRs and `profile/**` branch pushes run read-only tests, resource validation and deterministic offline rendering. Actions are pinned to verified commit SHAs. The daily refresh job has only `contents: write` and runs on the default branch for schedule or explicit dispatch. It commits only an allowlist of generated resources and public summaries. Raw profiles, Library bundles, QA screenshots and credentials are ignored and never staged by CI. Only the built-in repository token is used; no added secrets or security settings. Independent failed sources retain their bytes and timestamps, successful sources can still update, and the run reports partial failure after safe commits. Scheduled refresh is not enabled by this draft PR before merge. The existing snake output workflow remains separate and now uses pinned actions.
