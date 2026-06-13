#!/usr/bin/env python3
"""
build_databin.py — regenerate BoxScoreLab's data.bin from the nba-boxscores database.

WHAT IT DOES
  1. Loads a frozen HISTORICAL blob (data_history.bin) — the seasons that never
     change (1947 .. HISTORY_THROUGH). This is built ONCE and reused, so we don't
     re-pull 78 years of game files every run.
  2. Pulls recent seasons (HISTORY_THROUGH+1 .. current) fresh from the database
     NDJSON every run, so the current season stays up to date.
  3. Maps NBA.com player names -> HoopsHype names via player_names.json +
     player_names_context.json (the (name|year|team) overrides for duplicate names).
  4. Assigns each player a position with this PRIORITY:
        (a) positions.csv (your sheet, cols PLAYER + POSITION) — authoritative
        (b) carried-forward position from the historical blob
        (c) stat-profile inference (rebounds/assists/blocks) — rookies only
  5. Packs into the exact 22-column row format the engine reads and gzips to data.bin.

USAGE
  python build_databin.py
      --history   data_history.bin          (frozen pre-2025 blob; required)
      --positions positions.csv             (optional; sheet export, cols S+AG)
      --out       data.bin                  (output; default ./data.bin)
      --recent-from 2025                     (first END-year to pull fresh; default 2025)
      --repo aderoa/nba-boxscores            (database repo)

  To (re)build the frozen history blob from an existing full data.bin, run with
  --freeze-history <existing data.bin>  which writes data_history.bin containing
  only seasons <= HISTORY_THROUGH, then exits.

NOTES
  - Run from anywhere; it fetches the database over HTTPS (raw.githubusercontent.com).
  - Re-running is idempotent: output is rebuilt from history + fresh recent, never appended.
  - Requires only the Python standard library.
"""
import argparse, gzip, json, sys, urllib.request, collections, os

# ---- format constants (must match eng_consts.js G{} and the blob's p[]) ----
POS = ["C", "PF", "PG", "SF", "SG"]                 # position index order in blob['p']
POS_IDX = {p: i for i, p in enumerate(POS)}
# 22-column row order:
G = dict(TM=0, OP=1, PS=2, MN=3, PT=4, FM=5, FA=6, PM=7, PA=8, FT=9, TA=10,
         OR=11, DR=12, RB=13, AS=14, ST=15, BK=16, TO=17, PF=18, TY=19, SY=20, GY=21)
HISTORY_THROUGH = 2024   # END-year. History blob holds <=2024; we pull >=2025 fresh.

# HoopsHype team abbreviation -> full nickname (as stored in blob['t']).
# Modern franchises only; historical teams already live in the frozen history blob.
ABBR_NICK = {
 "ATL":"Hawks","BOS":"Celtics","BKN":"Nets","CHA":"Hornets","CHI":"Bulls","CLE":"Cavaliers",
 "DAL":"Mavericks","DEN":"Nuggets","DET":"Pistons","GSW":"Warriors","HOU":"Rockets","IND":"Pacers",
 "LAC":"Clippers","LAL":"Lakers","MEM":"Grizzlies","MIA":"Heat","MIL":"Bucks","MIN":"Timberwolves",
 "NOP":"Pelicans","NYK":"Knicks","OKC":"Thunder","ORL":"Magic","PHI":"76ers","PHX":"Suns",
 "POR":"Trail Blazers","SAC":"Kings","SAS":"Spurs","TOR":"Raptors","UTA":"Jazz","WAS":"Wizards"}

RAW = "https://raw.githubusercontent.com/{repo}/main/data/"

def log(*a): print("[build_databin]", *a, flush=True)

def load_blob(path):
    with open(path, "rb") as f:
        return json.loads(gzip.decompress(f.read()))

def save_blob(obj, path):
    out = json.dumps(obj, separators=(",", ":")).encode()
    with open(path, "wb") as f:
        f.write(gzip.compress(out, 6))
    return len(out)

def fetch_json(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())

def fetch_lines(url):
    try:
        with urllib.request.urlopen(url) as r:
            return [l for l in r.read().decode().splitlines() if l.strip()]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None      # season not present (e.g. future year)
        raise

# ---------- position inference (fallback for rookies w/ no sheet/history pos) ----------
def infer_pos(rows):
    mn = sum(r[G["MN"]] for r in rows) or 1
    reb = sum(r[G["RB"]] for r in rows); ast = sum(r[G["AS"]] for r in rows)
    blk = sum(r[G["BK"]] for r in rows); tpa = sum(r[G["PA"]] for r in rows)
    rpm = reb/mn*36; apm = ast/mn*36; bpm = blk/mn*36; tppm = tpa/mn*36
    if rpm >= 9 or bpm >= 1.6: return POS_IDX["C"]
    if rpm >= 6.5:             return POS_IDX["PF"]
    if apm >= 5.5:             return POS_IDX["PG"]
    if apm >= 3.5 and rpm < 5: return POS_IDX["PG"]
    if tppm >= 4 and rpm < 5:  return POS_IDX["SG"]
    return POS_IDX["SF"]

def sheet_positions(path):
    """Read positions.csv. Expects a header row with PLAYER and POSITION columns
    (your Sheet2 export: PLAYER in col S=18, POSITION in col AG=32, but we locate
    them by header name so column drift doesn't break it)."""
    import csv
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows: return out
    hdr = [h.strip().upper() for h in rows[0]]
    # This is a multi-block sheet: "PLAYER" can appear in several columns. The
    # POSITION column pairs with the nearest PLAYER column to its LEFT. Find
    # POSITION, then the closest preceding PLAYER. Fall back to fixed S(18)/AG(32).
    player_cols = [i for i, h in enumerate(hdr) if h == "PLAYER"]
    pos_cols    = [i for i, h in enumerate(hdr) if h == "POSITION"]
    if pos_cols and player_cols:
        cp = pos_cols[0]
        left = [c for c in player_cols if c < cp]
        ci = max(left) if left else player_cols[0]
    else:
        ci, cp = 18, 32
    def to_idx(v):
        v = (v or "").strip().upper()
        if v in POS_IDX: return POS_IDX[v]
        if v == "G": return POS_IDX["PG"]
        if v == "F": return POS_IDX["SF"]
        return None
    for r in rows[1:]:
        if len(r) <= max(ci, cp): continue
        nm = r[ci].strip(); pv = to_idx(r[cp])
        if nm and pv is not None: out[nm] = pv
    return out

# ---------------------------- main pipeline ----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="data_history.bin")
    ap.add_argument("--positions", default=None)
    ap.add_argument("--out", default="data.bin")
    ap.add_argument("--recent-from", type=int, default=HISTORY_THROUGH + 1)
    ap.add_argument("--repo", default="aderoa/nba-boxscores")
    ap.add_argument("--freeze-history", default=None,
                    help="Build data_history.bin (seasons <= HISTORY_THROUGH) from this full data.bin, then exit.")
    args = ap.parse_args()
    base = RAW.format(repo=args.repo)

    # --- one-time: freeze history from an existing full blob ---
    if args.freeze_history:
        full = load_blob(args.freeze_history)
        D = {}
        for name, rows in full["d"].items():
            keep = [r for r in rows if r[G["SY"]] <= HISTORY_THROUGH]
            if keep: D[name] = keep
        hist = {"t": full["t"], "p": full["p"], "d": D}
        n = save_blob(hist, args.history)
        log(f"froze history (<= {HISTORY_THROUGH}) -> {args.history}: {len(D)} players, {n/1e6:.0f} MB raw")
        return

    # --- load frozen history ---
    if not os.path.exists(args.history):
        log(f"ERROR: {args.history} not found. Build it once with --freeze-history <full data.bin>.")
        sys.exit(1)
    hist = load_blob(args.history)
    T = list(hist["t"]); P = hist["p"]; D = {k: list(v) for k, v in hist["d"].items()}
    log(f"history: {len(D)} players (seasons <= {HISTORY_THROUGH})")
    if P != POS:
        log(f"WARNING: history position order {P} != expected {POS}")

    nick_idx = {n: i for i, n in enumerate(T)}
    for ab, nick in ABBR_NICK.items():
        if nick not in nick_idx:
            nick_idx[nick] = len(T); T.append(nick)

    # --- name maps from the database ---
    pn  = fetch_json(base + "player_names.json")
    ctx = fetch_json(base + "player_names_context.json")
    log(f"name maps: {len(pn)} mappings, {len(ctx)} context overrides")

    def hh_name(nb, yr, tm):
        k = f"{nb}|{yr}|{tm}"
        if k in ctx: return ctx[k]
        return pn.get(nb, nb)

    # --- carried-forward positions from history (mode across a player's rows) ---
    carried = {}
    for nm, rows in D.items():
        c = collections.Counter(r[G["PS"]] for r in rows)
        carried[nm] = c.most_common(1)[0][0]

    # --- pull recent seasons fresh ---
    added = collections.defaultdict(list)
    yr = args.recent_from
    while True:
        lines = fetch_lines(f"{base}{yr}/boxscores.ndjson")
        if lines is None:
            log(f"season {yr}: not present — stopping")
            break
        log(f"season {yr}: {len(lines)} game-rows")
        for l in lines:
            r = json.loads(l)
            nb = r.get("name"); tm = r.get("team"); op = r.get("opp"); sy = r.get("sy", yr)
            name = hh_name(nb, str(sy), tm)
            tn = ABBR_NICK.get(tm); on = ABBR_NICK.get(op)
            if not tn or not on:
                continue
            row = [0] * 22
            row[G["TM"]] = nick_idx[tn]; row[G["OP"]] = nick_idx[on]
            row[G["MN"]] = int(r.get("min", 0) or 0)
            row[G["PT"]] = int(r.get("pts", 0) or 0)
            row[G["FM"]] = int(r.get("fgm", 0) or 0); row[G["FA"]] = int(r.get("fga", 0) or 0)
            row[G["PM"]] = int(r.get("tpm", 0) or 0); row[G["PA"]] = int(r.get("tpa", 0) or 0)
            row[G["FT"]] = int(r.get("ftm", 0) or 0); row[G["TA"]] = int(r.get("fta", 0) or 0)
            row[G["OR"]] = int(r.get("oreb", 0) or 0); row[G["DR"]] = int(r.get("dreb", 0) or 0)
            row[G["RB"]] = int(r.get("reb", 0) or 0); row[G["AS"]] = int(r.get("ast", 0) or 0)
            row[G["ST"]] = int(r.get("stl", 0) or 0); row[G["BK"]] = int(r.get("blk", 0) or 0)
            row[G["TO"]] = int(r.get("tov", 0) or 0); row[G["PF"]] = int(r.get("pf", 0) or 0)
            row[G["TY"]] = 0; row[G["SY"]] = sy; row[G["GY"]] = sy - 1
            added[name].append(row)
        yr += 1

    log(f"recent: {sum(len(v) for v in added.values())} rows for {len(added)} players")

    # --- merge recent into the player table ---
    new_players = 0
    for name, rows in added.items():
        if name in D: D[name].extend(rows)
        else: D[name] = rows; new_players += 1
    log(f"new players introduced by recent seasons: {new_players}")

    # --- POSITION resolution: sheet > carried > inferred ---
    sheet = sheet_positions(args.positions) if args.positions else {}
    if args.positions: log(f"sheet positions: {len(sheet)} players")
    src = collections.Counter()
    for name, rows in D.items():
        if name in sheet:
            ps = sheet[name]; src["sheet"] += 1
        elif name in carried:
            ps = carried[name]; src["carried"] += 1
        else:
            ps = infer_pos(rows); src["inferred"] += 1
        for r in rows: r[G["PS"]] = ps
    log(f"position sources: {dict(src)}")

    # --- pack ---
    n = save_blob({"t": T, "p": P, "d": D}, args.out)
    maxsy = max((r[G["SY"]] for rows in D.values() for r in rows[-1:]), default=0)
    log(f"wrote {args.out}: {len(D)} players, max season {maxsy}, {os.path.getsize(args.out)/1e6:.1f} MB gz")

if __name__ == "__main__":
    main()
