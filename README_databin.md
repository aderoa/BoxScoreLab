# data.bin regeneration

`data.bin` powers Draft Roulette (and other BoxScoreLab games). It is rebuilt
from the `nba-boxscores` database so the current season stays fresh.

## Files
- `scripts/build_databin.py` — the generator (stdlib only). Rebuilds BOTH data.bin and salaries.json.
- `data_history.bin` — FROZEN seasons <= 2024 (built once; never changes).
- `positions.csv` — your Sheet2 export (PLAYER + POSITION columns). Authoritative for positions.
- `salaries_sheet.csv` — your Sheet1 export (PLAYER, TEAM, and a per-season salary column).
  Column "2026" = the 2025-26 salary. Authoritative for who's eligible in the current season.
- `data.bin` — OUTPUT: the box-score blob the games load.
- `salaries.json` — OUTPUT: the salary file that gates which player-seasons appear on the wheel.

## One-time setup
1. Build the frozen history blob once from your current full data.bin:
   ```
   python scripts/build_databin.py --freeze-history data.bin --history data_history.bin
   ```
   Commit `data_history.bin`. (It holds 1947–2024 and never needs rebuilding.)
2. Export Sheet2 (PLAYER + POSITION) as `positions.csv` and commit it.
3. Export Sheet1 (PLAYER, TEAM, season-salary columns) as `salaries_sheet.csv` and commit it.
   Re-export both whenever they change (new rookies, position fixes, updated salaries).

   IMPORTANT: a current-season player only appears on the wheel if they have a salary
   entry for that season. The salary column header must match --salary-col-header
   (currently "2026" for the 2025-26 season). Next season, bump --salary-season,
   --salary-col-header, and --season-cap in the workflow.

## Regenerate (manual)
```
python scripts/build_databin.py \
  --history data_history.bin \
  --positions positions.csv \
  --salaries-sheet salaries_sheet.csv --salaries-out salaries.json \
  --salary-season 2025 --salary-col-header "2026" --season-cap 154647000 \
  --recent-from 2025 --out data.bin
```
This pulls 2025 + 2026 (and any later season) fresh from the database, maps NBA.com
names -> HoopsHype via the committed `player_names.json` / `player_names_context.json`,
and resolves each position as: sheet > carried-forward > stat-inferred (rookies only).

## Regenerate (automatic)
`.github/workflows/build-databin.yml` runs daily (13:30 UTC) and on demand, committing
`data.bin` only when it changed.

## Position priority
1. `positions.csv` (your sheet) — wins whenever the player is listed.
2. Carried-forward from `data_history.bin` — for players not in the sheet.
3. Stat-profile inference — only for brand-new players in neither.
