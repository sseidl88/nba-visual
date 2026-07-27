from datetime import datetime, timedelta
import requests
import json
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--league", default="wnba", choices=["wnba", "nba"])
args   = parser.parse_args()
LEAGUE = args.league

_SPORT  = "basketball"
_BASE   = f"https://site.api.espn.com/apis/site/v2/sports/{_SPORT}/{LEAGUE}"
_BASE2  = f"https://site.api.espn.com/apis/v2/sports/{_SPORT}/{LEAGUE}"

SCOREBOARD    = f"{_BASE}/scoreboard"
SUMMARY       = f"{_BASE}/summary"
TEAMS_URL     = f"{_BASE}/teams"
STANDINGS_URL = f"{_BASE2}/standings"
DATA_DIR      = "docs/data" if LEAGUE == "wnba" else "docs/data/nba"

print(f"Running {LEAGUE.upper()} stats → {DATA_DIR}")


def safe_get(url, **params):
    r = requests.get(url, params=params or None, timeout=30)
    return r


def parse_box_score(summary_json):
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
            ft_idx  = col("FT")

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

                ftm, fta = 0, 0
                if ft_idx is not None and ft_idx < len(stats):
                    ft_str = stats[ft_idx]
                    if ft_str and ft_str != "--" and "-" in str(ft_str):
                        try:
                            parts = str(ft_str).split("-")
                            ftm, fta = int(parts[0]), int(parts[1])
                        except (ValueError, IndexError):
                            pass

                records.append({
                    "_id": aid, "PLAYER_NAME": name,
                    "TEAM_ABBREVIATION": abbrev,
                    "PTS": pts, "PLUS_MINUS": pm,
                    "AST": ast, "REB": reb, "BLK": blk,
                    "FGM": fgm, "FGA": fga, "FTM": ftm, "FTA": fta,
                })
            break
    return records


now       = datetime.now()
yesterday = now - timedelta(days=1)
date_str  = yesterday.strftime("%Y-%m-%d")


# ── yesterday's top scorers + game scores ────────────────────────────────────

yest_resp   = safe_get(SCOREBOARD, dates=yesterday.strftime("%Y%m%d"))
yest_events = yest_resp.json().get("events", []) if yest_resp.ok else []

all_yesterday = []
for event in yest_events:
    r = safe_get(SUMMARY, event=event["id"])
    if r.ok:
        all_yesterday.extend(parse_box_score(r.json()))

if not all_yesterday:
    print(f"No {LEAGUE.upper()} games found for {date_str}")

top_scorers = [
    {**{k: v for k, v in p.items() if k != "_id"}, "id": p["_id"]}
    for p in sorted(all_yesterday, key=lambda x: x["PTS"], reverse=True)
]

# Parse final scores from yesterday's events
game_scores = {"date": date_str, "games": []}
for event in yest_events:
    comp        = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home and away:
        try:
            game_scores["games"].append({
                "home":       home.get("team", {}).get("abbreviation", ""),
                "home_score": int(home.get("score", 0) or 0),
                "away":       away.get("team", {}).get("abbreviation", ""),
                "away_score": int(away.get("score", 0) or 0),
            })
        except (ValueError, TypeError):
            pass


# ── aggregate last 14 days for PPG / trending / daily leaders ────────────────

totals             = {}   # athlete_id → season totals + split halves
daily_leaders      = {}   # "YYYY-MM-DD" → {PLAYER_NAME, TEAM_ABBREVIATION, pts}
team_daily_leaders = {}   # "YYYY-MM-DD" → {"TEAM": {PLAYER_NAME, pts, TEAM_ABBREVIATION, date}}
player_games       = {}   # athlete_id → [{date, opp, pts, ast, reb, blk, fgm, fga}]
MAX_GAMES  = 90
game_calls = 0

for offset in range(1, 31):
    if game_calls >= MAX_GAMES:
        break
    is_7d     = offset <= 7
    is_14d    = offset <= 14
    is_recent = is_7d    # used by trending logic
    d     = (now - timedelta(days=offset)).strftime("%Y%m%d")
    d_key = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
    r = safe_get(SCOREBOARD, dates=d)
    if not r.ok:
        continue
    for event in r.json().get("events", []):
        if game_calls >= MAX_GAMES:
            break
        comp        = event.get("competitions", [{}])[0]
        event_teams = {c.get("team", {}).get("abbreviation", "") for c in comp.get("competitors", [])}
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
                    "id": p["_id"],
                    # 30-day totals
                    "pts": 0, "ast": 0, "reb": 0, "blk": 0, "fgm": 0, "fga": 0, "ftm": 0, "fta": 0, "games": 0,
                    # 14-day totals
                    "d14_pts": 0, "d14_ast": 0, "d14_reb": 0, "d14_blk": 0, "d14_fgm": 0, "d14_fga": 0, "d14_ftm": 0, "d14_fta": 0, "d14_games": 0,
                    # 7-day totals (recent, for trending)
                    "r_pts": 0, "r_ast": 0, "r_reb": 0, "r_blk": 0, "r_fgm": 0, "r_fga": 0, "r_games": 0,
                    # older 14-day half (days 8-14, for trending baseline)
                    "o_pts": 0, "o_ast": 0, "o_reb": 0, "o_blk": 0, "o_fgm": 0, "o_fga": 0, "o_games": 0,
                }
            for stat, key in [("PTS","pts"),("AST","ast"),("REB","reb"),("BLK","blk"),("FGM","fgm"),("FGA","fga"),("FTM","ftm"),("FTA","fta")]:
                totals[aid][key] += p[stat]
            totals[aid]["games"] += 1
            if is_14d:
                for stat, key in [("PTS","pts"),("AST","ast"),("REB","reb"),("BLK","blk"),("FGM","fgm"),("FGA","fga"),("FTM","ftm"),("FTA","fta")]:
                    totals[aid][f"d14_{key}"] += p[stat]
                totals[aid]["d14_games"] += 1
            pfx = "r_" if is_7d else ("o_" if offset <= 14 else None)
            if pfx:
                for stat, key in [("PTS","pts"),("AST","ast"),("REB","reb"),("BLK","blk"),("FGM","fgm"),("FGA","fga")]:
                    totals[aid][f"{pfx}{key}"] += p[stat]
                totals[aid][f"{pfx}games"] += 1
            if d_key not in daily_leaders or p["PTS"] > daily_leaders[d_key]["pts"]:
                daily_leaders[d_key] = {
                    "PLAYER_NAME": p["PLAYER_NAME"],
                    "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"],
                    "pts": p["PTS"],
                }
            tm_abbr = p["TEAM_ABBREVIATION"]
            if d_key not in team_daily_leaders:
                team_daily_leaders[d_key] = {}
            if (tm_abbr not in team_daily_leaders[d_key] or
                    p["PTS"] > team_daily_leaders[d_key][tm_abbr]["pts"]):
                team_daily_leaders[d_key][tm_abbr] = {
                    "PLAYER_NAME": p["PLAYER_NAME"],
                    "TEAM_ABBREVIATION": tm_abbr,
                    "pts": p["PTS"],
                    "date": d_key,
                }
            opp = next((t for t in event_teams if t != p["TEAM_ABBREVIATION"]), "")
            if aid not in player_games:
                player_games[aid] = []
            player_games[aid].append({
                "date": d_key, "opp": opp,
                "pts": p["PTS"], "ast": p["AST"], "reb": p["REB"], "blk": p["BLK"],
                "fgm": p["FGM"], "fga": p["FGA"], "fta": p["FTA"],
            })

for games in player_games.values():
    games.sort(key=lambda g: g["date"], reverse=True)


def ts_pct(pts, fga, fta):
    denom = 2 * (fga + 0.44 * fta)
    return round(pts / denom * 100, 1) if denom > 0 else 0

def window_stats(v, pfx="", g_key="games"):
    g = v[g_key]
    if g == 0:
        return None
    p   = pfx
    fga = v[f"{p}fga"]
    fta = v.get(f"{p}fta", 0)
    pts = v[f"{p}pts"]
    return {
        "PPG":    round(pts / g, 1),
        "APG":    round(v[f"{p}ast"] / g, 1),
        "RPG":    round(v[f"{p}reb"] / g, 1),
        "BPG":    round(v[f"{p}blk"] / g, 1),
        "FG_PCT": round(v[f"{p}fgm"] / fga * 100, 1) if fga > 0 else 0,
        "TS_PCT": ts_pct(pts, fga, fta),
        "games":  g,
    }

ppg_rows = sorted(
    [
        {
            "_id": kid,
            "PLAYER_NAME": v["PLAYER_NAME"],
            "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
            "id": v["id"],
            "w30": window_stats(v, "", "games"),
            "w14": window_stats(v, "d14_", "d14_games"),
            "w7":  window_stats(v, "r_",  "r_games"),
        }
        for kid, v in totals.items() if v["games"] > 0
    ],
    key=lambda x: (x["w14"] or x["w30"] or {}).get("PPG", 0),
    reverse=True,
)

def flatten_window(p, w):
    s = p[w] or {}
    return {
        "PLAYER_NAME": p["PLAYER_NAME"], "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"], "id": p["_id"],
        "PPG": s.get("PPG", 0), "APG": s.get("APG", 0), "RPG": s.get("RPG", 0),
        "BPG": s.get("BPG", 0), "FG_PCT": s.get("FG_PCT", 0), "TS_PCT": s.get("TS_PCT", 0),
        "games": s.get("games", 0),
        "w7": p["w7"], "w14": p["w14"], "w30": p["w30"],
    }

season_ppg = [flatten_window(p, "w14") for p in ppg_rows if p["w14"]]


# ── identify rookies + injury status from team rosters ───────────────────────

rookie_ids    = set()
injury_status = {}   # player_id → "questionable" | "out" | "ir"

def _parse_status(a):
    """Return normalized injury status string, or empty string if active."""
    raw = a.get("status", {})
    if isinstance(raw, dict):
        type_s = raw.get("type", "").lower()
        name_s = raw.get("name", "").lower()
    elif isinstance(raw, str):
        type_s = name_s = raw.lower()
    else:
        type_s = name_s = ""

    # Trust the explicit active flag — return immediately
    if type_s == "active" or name_s == "active":
        return ""

    combined = f"{type_s} {name_s}"
    if any(k in combined for k in ("injur", "reserve")):
        return "ir"
    if "out" in combined:
        return "out"
    if any(k in combined for k in ("question", "day-to-day", "day to day", "doubtful")):
        return "questionable"

    # Only fall back to injuries array if main status was ambiguous (non-active, non-empty)
    if type_s and type_s != "active":
        injuries = a.get("injuries", [])
        if injuries:
            inj = injuries[0]
            s = (inj.get("status") or inj.get("type") or "").lower()
            if any(k in s for k in ("injur", "reserve")):
                return "ir"
            if "out" in s:
                return "out"
            if any(k in s for k in ("question", "day-to-day", "doubtful")):
                return "questionable"
    return ""

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
            if athletes_raw and "items" in (athletes_raw[0] if athletes_raw else {}):
                athletes_flat = [a for grp in athletes_raw for a in grp.get("items", [])]
            else:
                athletes_flat = athletes_raw
            for a in athletes_flat:
                pid = str(a.get("id", ""))
                if a.get("experience", {}).get("years", -1) == 0:
                    rookie_ids.add(pid)
                if pid:
                    status = _parse_status(a)
                    if status:
                        injury_status[pid] = status
    print(f"Found {len(rookie_ids)} rookies, {len(injury_status)} non-active players")
except Exception as e:
    print(f"Roster error: {e}")

rookie_ppg = [
    {
        "PLAYER_NAME":       v["PLAYER_NAME"],
        "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
        "id":     v["id"],
        "PPG":    round(v["d14_pts"] / v["d14_games"], 1),
        "APG":    round(v["d14_ast"] / v["d14_games"], 1),
        "RPG":    round(v["d14_reb"] / v["d14_games"], 1),
        "BPG":    round(v["d14_blk"] / v["d14_games"], 1),
        "FG_PCT": round(v["d14_fgm"] / v["d14_fga"] * 100, 1) if v["d14_fga"] > 0 else 0,
        "TS_PCT": ts_pct(v["d14_pts"], v["d14_fga"], v["d14_fta"]),
    }
    for kid, v in sorted(totals.items(), key=lambda kv: kv[1]["d14_pts"] / max(kv[1]["d14_games"], 1), reverse=True)
    if kid in rookie_ids and v["d14_games"] > 0
]


# ── trending players ─────────────────────────────────────────────────────────

def per_game_stats(v, pfx="", g_key=None):
    g_key = g_key or f"{pfx}games"
    g   = v[g_key]
    fga = v[f"{pfx}fga"]
    if g == 0:
        return None
    return {
        "PPG":    round(v[f"{pfx}pts"] / g, 1),
        "APG":    round(v[f"{pfx}ast"] / g, 1),
        "RPG":    round(v[f"{pfx}reb"] / g, 1),
        "BPG":    round(v[f"{pfx}blk"] / g, 1),
        "FG_PCT": round(v[f"{pfx}fgm"] / fga * 100, 1) if fga > 0 else 0.0,
    }

def composite_score(recent, baseline):
    return (
        (recent["PPG"]    - baseline["PPG"])    / 15  +
        (recent["APG"]    - baseline["APG"])    / 5   +
        (recent["RPG"]    - baseline["RPG"])    / 6   +
        (recent["BPG"]    - baseline["BPG"])    / 1.5 +
        (recent["FG_PCT"] - baseline["FG_PCT"]) / 20
    )

trend_candidates = []
for kid, v in totals.items():
    if v["r_games"] < 1 or v["games"] < 3:
        continue
    recent = per_game_stats(v, "r_")
    avg    = per_game_stats(v)
    if not recent or not avg:
        continue
    delta = {k: round(recent[k] - avg[k], 1) for k in recent}
    score = composite_score(recent, avg)
    trend_candidates.append({
        "score":             score,
        "PLAYER_NAME":       v["PLAYER_NAME"],
        "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
        "id":                v["id"],
        "recent_games":      v["r_games"],
        "recent":            recent,
        "avg":               avg,
        "delta":             delta,
    })

trend_candidates.sort(key=lambda x: x["score"], reverse=True)

def strip_score(entry):
    return {k: v for k, v in entry.items() if k != "score"}

trending_up   = strip_score(trend_candidates[0])  if trend_candidates else {}
trending_down = strip_score(trend_candidates[-1]) if trend_candidates else {}


# ── per-team insights (trending + streak per team) ────────────────────────────

all_teams     = {v["TEAM_ABBREVIATION"] for v in totals.values()}
team_insights = {}

for tm in all_teams:
    tc = [c for c in trend_candidates if c["TEAM_ABBREVIATION"] == tm]

    tm_history = sorted(
        [team_daily_leaders[d][tm] for d in team_daily_leaders if tm in team_daily_leaders[d]],
        key=lambda x: x["date"],
        reverse=True,
    )

    tm_streak = 0
    tm_champ  = {}
    if tm_history:
        cn = tm_history[0]["PLAYER_NAME"]
        for entry in tm_history:
            if entry["PLAYER_NAME"] == cn:
                tm_streak += 1
            else:
                break
        tm_champ = {**tm_history[0], "streak": tm_streak}

    team_insights[tm] = {
        "trending_up":       strip_score(tc[0])  if tc else {},
        "trending_down":     strip_score(tc[-1]) if tc else {},
        "top_scorer_streak": {"current": tm_champ, "history": tm_history[:10]},
    }

print(f"Built per-team insights for {len(team_insights)} teams")


# ── top scorer streak ─────────────────────────────────────────────────────────

scorer_history = sorted(
    [{"date": k, **v} for k, v in daily_leaders.items() if v["pts"] > 0],
    key=lambda x: x["date"],
    reverse=True,
)

streak = 0
champ  = {}
if scorer_history:
    champ_name = scorer_history[0]["PLAYER_NAME"]
    for entry in scorer_history:
        if entry["PLAYER_NAME"] == champ_name:
            streak += 1
        else:
            break
    champ = {**scorer_history[0], "streak": streak}

top_scorer_streak = {
    "current": champ,
    "history": scorer_history[:10],
}
print(f"Top scorer streak: {champ.get('PLAYER_NAME','?')} × {streak} nights")


# ── team standings ────────────────────────────────────────────────────────────

standings = []
try:
    sr = safe_get(STANDINGS_URL)
    if sr.ok:
        for conf in sr.json().get("children", []):
            conf_name = conf.get("name", "")
            for entry in conf.get("standings", {}).get("entries", []):
                team      = entry.get("team", {})
                stats_map = {s["name"]: s for s in entry.get("stats", [])}
                streak_raw = stats_map.get("streak", {}).get("displayValue", "")
                standings.append({
                    "team":       team.get("abbreviation", ""),
                    "name":       team.get("displayName", ""),
                    "conference": conf_name,
                    "wins":       int(stats_map.get("wins",       {}).get("value", 0)),
                    "losses":     int(stats_map.get("losses",     {}).get("value", 0)),
                    "pct":        round(float(stats_map.get("winPercent", {}).get("value", 0)), 3),
                    "gb":         stats_map.get("gamesBehind", {}).get("displayValue", "—"),
                    "streak":     streak_raw,
                })
    standings.sort(key=lambda x: (x["conference"], -x["wins"], x["losses"]))
    print(f"Fetched {len(standings)} standings entries")
except Exception as e:
    print(f"Standings error: {e}")


# ── write output ─────────────────────────────────────────────────────────────

os.makedirs(DATA_DIR, exist_ok=True)

outputs = {
    f"top_scorers_{date_str}.json": top_scorers,
    "season_ppg.json":              season_ppg,
    "rookie_ppg.json":              rookie_ppg,
    "trending_up.json":             trending_up,
    "trending_down.json":           trending_down,
    "top_scorer_streak.json":       top_scorer_streak,
    "game_scores.json":             game_scores,
    "player_games.json":            player_games,
    "standings.json":               standings,
    "team_insights.json":           team_insights,
    "injury_status.json":           injury_status,
    "meta.json":                    {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
}

for filename, data in outputs.items():
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    count = len(data) if isinstance(data, (list, dict)) else 1
    print(f"Wrote {count} records → {path}")
