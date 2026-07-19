from datetime import datetime, timedelta
import requests
import json
import os

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
TEAMS_URL  = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams"


def safe_get(url, **params):
    r = requests.get(url, params=params or None, timeout=30)
    return r


def parse_box_score(summary_json):
    """Return per-player records from a game summary response."""
    records = []
    for team in summary_json.get("boxscore", {}).get("players", []):
        abbrev = team.get("team", {}).get("abbreviation", "")
        for group in team.get("statistics", []):
            names = group.get("names", group.get("labels", []))
            if "PTS" not in names:
                continue

            def col(stat):
                return names.index(stat) if stat in names else None

            pts_idx = col("PTS")
            pm_idx  = col("+/-")
            ast_idx = col("AST")
            reb_idx = col("REB")
            blk_idx = col("BLK")
            fg_idx  = col("FG")

            for ath_data in group.get("athletes", []):
                stats = ath_data.get("stats", [])
                ath   = ath_data.get("athlete", {})
                name  = ath.get("displayName", "")
                aid   = str(ath.get("id", ""))
                if not name:
                    continue

                def stat_int(i):
                    if i is None or i >= len(stats):
                        return 0
                    try:
                        return int(float(stats[i])) if stats[i] not in ("--", "") else 0
                    except (ValueError, TypeError):
                        return 0

                pts = stat_int(pts_idx)
                ast = stat_int(ast_idx)
                reb = stat_int(reb_idx)
                blk = stat_int(blk_idx)

                pm = None
                if pm_idx is not None and pm_idx < len(stats):
                    try:
                        raw = stats[pm_idx]
                        pm = int(float(raw)) if raw not in ("--", "") else None
                    except (ValueError, TypeError):
                        pm = None

                fgm, fga = 0, 0
                if fg_idx is not None and fg_idx < len(stats):
                    fg_str = stats[fg_idx]
                    if fg_str and fg_str != "--" and "-" in str(fg_str):
                        try:
                            parts = str(fg_str).split("-")
                            fgm, fga = int(parts[0]), int(parts[1])
                        except (ValueError, IndexError):
                            pass

                records.append({
                    "_id": aid, "PLAYER_NAME": name,
                    "TEAM_ABBREVIATION": abbrev,
                    "PTS": pts, "PLUS_MINUS": pm,
                    "AST": ast, "REB": reb, "BLK": blk,
                    "FGM": fgm, "FGA": fga,
                })
            break  # only first group containing PTS
    return records


now       = datetime.now()
yesterday = now - timedelta(days=1)
date_str  = yesterday.strftime("%Y-%m-%d")


# ── yesterday's top scorers ──────────────────────────────────────────────────

yest_resp   = safe_get(SCOREBOARD, dates=yesterday.strftime("%Y%m%d"))
yest_events = yest_resp.json().get("events", []) if yest_resp.ok else []

all_yesterday = []
for event in yest_events:
    r = safe_get(SUMMARY, event=event["id"])
    if r.ok:
        all_yesterday.extend(parse_box_score(r.json()))

if not all_yesterday:
    print(f"No WNBA games found for {date_str}")

top_scorers = [
    {k: v for k, v in p.items() if k != "_id"}
    for p in sorted(all_yesterday, key=lambda x: x["PTS"], reverse=True)[:10]
]


# ── aggregate last 14 days for PPG ──────────────────────────────────────────

totals    = {}   # athlete_id → {name, team, pts, games}
MAX_GAMES = 40   # cap total box score fetches to stay within CI time limits
game_calls = 0

for offset in range(1, 15):
    if game_calls >= MAX_GAMES:
        break
    d = (now - timedelta(days=offset)).strftime("%Y%m%d")
    r = safe_get(SCOREBOARD, dates=d)
    if not r.ok:
        continue
    for event in r.json().get("events", []):
        if game_calls >= MAX_GAMES:
            break
        gr = safe_get(SUMMARY, event=event["id"])
        if not gr.ok:
            continue
        game_calls += 1
        for p in parse_box_score(gr.json()):
            aid = p["_id"] or p["PLAYER_NAME"]
            if aid not in totals:
                totals[aid] = {
                    "PLAYER_NAME": p["PLAYER_NAME"],
                    "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"],
                    "pts": 0, "ast": 0, "reb": 0, "blk": 0,
                    "fgm": 0, "fga": 0, "games": 0,
                }
            totals[aid]["pts"]   += p["PTS"]
            totals[aid]["ast"]   += p["AST"]
            totals[aid]["reb"]   += p["REB"]
            totals[aid]["blk"]   += p["BLK"]
            totals[aid]["fgm"]   += p["FGM"]
            totals[aid]["fga"]   += p["FGA"]
            totals[aid]["games"] += 1

ppg_rows = sorted(
    [
        {"_id": kid,
         "PLAYER_NAME": v["PLAYER_NAME"],
         "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
         "PPG": round(v["pts"] / v["games"], 1)}
        for kid, v in totals.items() if v["games"] > 0
    ],
    key=lambda x: x["PPG"],
    reverse=True,
)

season_ppg = [{"PLAYER_NAME": p["PLAYER_NAME"], "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"], "PPG": p["PPG"]} for p in ppg_rows[:10]]


# ── identify rookies from team rosters ───────────────────────────────────────

rookie_ids = set()
try:
    tr = safe_get(TEAMS_URL)
    if tr.ok:
        leagues = tr.json().get("sports", [{}])[0].get("leagues", [{}])[0]
        for team_entry in leagues.get("teams", []):
            tid = team_entry.get("team", {}).get("id")
            if not tid:
                continue
            rr = safe_get(f"{TEAMS_URL}/{tid}/roster")
            if not rr.ok:
                continue
            athletes_raw = rr.json().get("athletes", [])
            # Roster may group players by position: [{items: [...]}, ...]
            if athletes_raw and "items" in (athletes_raw[0] if athletes_raw else {}):
                athletes_flat = [a for grp in athletes_raw for a in grp.get("items", [])]
            else:
                athletes_flat = athletes_raw
            for a in athletes_flat:
                if a.get("experience", {}).get("years", -1) == 0:
                    rookie_ids.add(str(a.get("id", "")))
    print(f"Found {len(rookie_ids)} rookies across all rosters")
except Exception as e:
    print(f"Rookie detection error: {e}")

rookie_ppg = [
    {
        "PLAYER_NAME":     v["PLAYER_NAME"],
        "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
        "PPG":  round(v["pts"] / v["games"], 1),
        "APG":  round(v["ast"] / v["games"], 1),
        "RPG":  round(v["reb"] / v["games"], 1),
        "BPG":  round(v["blk"] / v["games"], 1),
        "FG_PCT": round(v["fgm"] / v["fga"] * 100, 1) if v["fga"] > 0 else 0,
    }
    for kid, v in sorted(totals.items(), key=lambda kv: kv[1]["pts"] / max(kv[1]["games"], 1), reverse=True)
    if kid in rookie_ids and v["games"] > 0
][:10]


# ── write output ─────────────────────────────────────────────────────────────

os.makedirs("docs/data", exist_ok=True)

outputs = {
    f"top_scorers_{date_str}.json": top_scorers,
    "season_ppg.json":              season_ppg,
    "rookie_ppg.json":              rookie_ppg,
}

for filename, data in outputs.items():
    path = os.path.join("docs", "data", filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(data)} records → {path}")
