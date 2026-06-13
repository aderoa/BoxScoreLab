# data.bin regeneration

`data.bin` powers Draft Roulette (and other BoxScoreLab games). It is rebuilt
from the `nba-boxscores` database so the current season stays fresh.

## Files
- `scripts/build_databin.py` — the generator (stdlib only).
- `data_history.bin` — FROZEN seasons <= 2024 (built once; never changes).
- `positions.csv` — your Sheet2 export (PLAYER + POSITION columns). Authoritative for positions.
- `data.bin` — the OUTPUT the games load.

## One-time setup
1. Build the frozen history blob once from your current full data.bin:
   ```
   python scripts/build_databin.py --freeze-history data.bin --history data_history.bin
   ```
   Commit `data_history.bin`. (It holds 1947–2024 and never needs rebuilding.)
2. Export Sheet2 (the one with PLAYER + POSITION) as `positions.csv` and commit it.
   Re-export whenever positions change (e.g. new rookies, position corrections).

## Regenerate (manual)
```
python scripts/build_databin.py --history data_history.bin --positions positions.csv --out data.bin
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
