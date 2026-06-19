"""US Open Pool 2026 — Live Scoring Leaderboard (Shinnecock Hills), linked to ESPN."""
import streamlit as st
import pandas as pd
import requests
import re
import unicodedata
import os
from datetime import datetime, timezone

st.set_page_config(page_title="US Open Pool 2026", page_icon="⛳", layout="centered")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=180_000, key="datarefresh")
except ImportError:
    pass

DIR = os.path.dirname(os.path.abspath(__file__))
ROSTER_PATH = os.path.join(DIR, "rosters.csv")

# US Open cut = low 60 and ties (USGA), vs top 70 at the PGA Championship.
CUT_TOP_N = 60

# The 21 amateurs bundled into the $0.25 Amateur Pod — tagged "(a)" on the leaderboard.
AMATEUR_POD = [
    "Jackson Koivun", "Preston Stout", "Ethan Fang", "Arni Sveinsson", "Ryder Cowan",
    "Miles Russell", "Mason Howell", "Eric Lee", "Logan Reilly", "Jackson Herrington",
    "Bryan Lee", "Mateo Pulcini", "Jackson Ormond", "Chase Kyes", "Matt Robles",
    "Marek Fleming", "Vaughn Harber", "Hamilton Coleman", "Brandon Holtz",
    "Guiseppe Puebla", "Jack Schoenberg",
]


# === SCORING (identical rubric to the entry sheet) ===
def points_for_position(pos, status=None):
    if status and status.upper() in ("CUT", "MC", "WD", "DQ"):
        return 0
    if pos is None:
        return 0
    table = {1: 90, 2: 65, 3: 60, 4: 55, 5: 50, 6: 45, 7: 40, 8: 35, 9: 30, 10: 25}
    if pos in table:
        return table[pos]
    if 11 <= pos <= 15: return 20
    if 16 <= pos <= 20: return 15
    if 21 <= pos <= 25: return 10
    if 26 <= pos <= 30: return 5
    if pos >= 31: return 2
    return 0


# === NAME NORMALIZATION ===
# Nordic/special letters that ASCII-NFKD drops instead of transliterating
# (e.g. ESPN's "Niklas Nørgaard", "Ludvig Åberg").
_TRANSLIT = str.maketrans({
    "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "å": "a", "Å": "a",
    "ð": "d", "Ð": "d", "þ": "th", "Þ": "th", "ł": "l", "Ł": "l",
})

def norm(name):
    s = name.translate(_TRANSLIT)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

ALIASES = {
    "rasmus hojgaard": "rasmus hjgaard",
    "nicolai hojgaard": "nicolai hjgaard",
    "niklas noorgaard": "niklas norgaard",
    "niklas norgaard moller": "niklas norgaard",
    "sungjae im": "sung jae im",
    "im sungjae": "sung jae im",
    "johnny keefer": "john keefer",
    "cameron cam smith": "cameron smith",
    "fitzpatrick alax": "alex fitzpatrick",
    "jacob bridgemen": "jacob bridgeman",
    "dtlan wu": "dylan wu",
    "aaron rai": "aaron rai",
    "tommy fleetwood": "tommy fleetwood",
    "ludvig aberg": "ludvig aberg",
    "adrien dumont de chassart": "adrien dumont de chassart",
    "angel hidalgo portillo": "angel hidalgo",
    "hennie du plessis": "hennie du plessis",
}

def resolve_name(name):
    n = norm(name)
    return ALIASES.get(n, n)


AMATEUR_NORMS = {resolve_name(n) for n in AMATEUR_POD}


# === FORMAT HELPERS ===
def _fmt_golf_score(v):
    if pd.isna(v): return "-"
    n = int(v)
    if n == 999: return "-"
    if n == 998: return "CUT"
    if n == 0: return "E"
    if n > 0: return f"+{n}"
    return str(n)

def _fmt_own_pct(v):
    if pd.isna(v): return "-"
    return f"{int(v)}%"

def score_to_int(score_str):
    s = str(score_str).strip()
    if s == "E": return 0
    if s in ("-", "", "None"): return None
    try: return int(s)
    except ValueError: return None

def force_numeric_cols(df):
    for col in ["Score", "Points", "Pool Pts", "Own %", "Pts/$"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(999).astype(int)
    if "Thru" in df.columns:
        df["Thru"] = pd.to_numeric(df["Thru"], errors="coerce").astype("Int64")
    return df


def golf_dataframe(df, height=None, key=None, on_select=None, highlight_rows=None, **kwargs):
    display = df.copy()
    display = display[[c for c in display.columns if not c.startswith("_")]]
    for col in ["Score", "Points", "Pool Pts", "Own %", "Pts/$"]:
        if col in display.columns:
            display[col] = pd.to_numeric(display[col], errors="coerce").astype("Int64")

    if "tee_time" in display.columns and "Thru" in display.columns:
        tee_map = {}
        for idx, row in display.iterrows():
            tt = row.get("tee_time", "")
            thru = row.get("Thru")
            if tt and (pd.isna(thru) or thru is None or thru == 0):
                tee_map[idx] = tt
        display = display.drop(columns=["tee_time"])
    else:
        tee_map = {}
        if "tee_time" in display.columns:
            display = display.drop(columns=["tee_time"])

    if "Thru" in display.columns:
        def _thru_to_int(v):
            if pd.isna(v) or v is None: return 0
            try:
                n = int(v)
                return 19 if n >= 18 else n
            except (ValueError, TypeError): return 0
        display["Thru"] = display["Thru"].apply(_thru_to_int).astype("Int64")

    if tee_map:
        for idx, tee_str in tee_map.items():
            if idx in display.index and "Thru" in display.columns:
                m = re.search(r'T(\d{1,2}):(\d{2})\s*(AM|PM)', tee_str)
                if m:
                    hr = int(m.group(1)); mn = int(m.group(2)); ap = m.group(3)
                    if ap == 'PM' and hr != 12: hr += 12
                    if ap == 'AM' and hr == 12: hr = 0
                    display.at[idx, "Thru"] = int(20 + hr + mn / 60.0)

    if "Today" in display.columns:
        def _today_to_int(v):
            s = str(v).strip()
            if s.startswith("T") and ("AM" in s or "PM" in s): return 999
            n = score_to_int(s)
            return n if n is not None else 999
        display["Today"] = display["Today"].apply(_today_to_int).astype(int)

    if "_proj_mc" in display.columns and "Today" in display.columns:
        mc_mask = display["_proj_mc"].fillna(False)
        display.loc[mc_mask, "Today"] = 998

    if "_proj_mc" in display.columns:
        proj_mc_mask = display["_proj_mc"].fillna(False)
        if "Golfer" in display.columns:
            display.loc[proj_mc_mask, "Golfer"] = display.loc[proj_mc_mask, "Golfer"] + "  (MC)"
        display = display.drop(columns=["_proj_mc"])

    if "Score" in display.columns:
        display["Score"] = display["Score"].replace(999, pd.NA).astype("Int64")
    if "Today" in display.columns:
        display["Today"] = display["Today"].astype("Int64")

    _thru_tee_display = {}
    if tee_map:
        for idx, tee_str in tee_map.items():
            _thru_tee_display[idx] = tee_str

    if "Thru" in display.columns:
        def _thru_display(idx, val):
            if idx in _thru_tee_display: return _thru_tee_display[idx]
            if pd.isna(val): return "-"
            n = int(val)
            if n == 0: return "-"
            if n == 19: return "F"
            if n >= 20: return "-"
            return str(n)
        display["Thru"] = [_thru_display(idx, display.at[idx, "Thru"]) for idx in display.index]

    fmt = {}
    for col in display.columns:
        if col in ("Score", "Today"): fmt[col] = _fmt_golf_score
        elif col == "Own %": fmt[col] = _fmt_own_pct

    styled = display.style.format(fmt, na_rep="-", precision=0)

    if highlight_rows is not None:
        flags = list(highlight_rows)
        def _hl(row):
            on = row.name < len(flags) and flags[row.name]
            css = "background-color: #ffe08a; font-weight: 700" if on else ""
            return [css] * len(row)
        styled = styled.apply(_hl, axis=1)

    kw = {**kwargs}
    if height: kw["height"] = height
    if on_select is not None:
        kw["key"] = key
        kw["on_select"] = on_select
        kw["selection_mode"] = "single-row"
    st.dataframe(styled, **kw)


# === FETCH LIVE LEADERBOARD ===
@st.cache_data(ttl=180)
def fetch_leaderboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return None, str(e), None

    golfers = []
    try:
        events = data.get("events", [])
        if not events:
            return None, "No events found in ESPN data", None

        event = None
        for ev in events:
            nl = ev.get("name", "").lower()
            if "open" in nl or "usga" in nl:
                event = ev
                break
        if event is None:
            event = events[0]

        event_name = event.get("name", "Unknown Event")
        competitions = event.get("competitions", [])
        if not competitions:
            return None, f"No competitions in event: {event_name}", None

        comp_obj = competitions[0]
        competitors = comp_obj.get("competitors", [])

        # Choose which round to show as "Today" from competition status.
        # A SUSPENDED round is reported as state="post"/completed=False but is
        # still in progress — stay on the current period in that case. Only
        # advance to the next round once the current one is genuinely complete.
        comp_status = comp_obj.get("status", {}) or {}
        comp_status_type = comp_status.get("type", {}) or {}
        status_period = comp_status.get("period", 1) or 1
        status_name = (comp_status_type.get("name", "") or "").upper()
        if status_name == "STATUS_SUSPENDED":
            target_period = status_period
        elif comp_status_type.get("completed") or comp_status_type.get("state") == "post":
            target_period = status_period + 1
        else:
            target_period = status_period

        raw_golfers = []
        for idx, comp in enumerate(competitors):
            athlete = comp.get("athlete", {})
            name = athlete.get("displayName", "Unknown")
            order = comp.get("order", idx + 1)
            score_raw = comp.get("score", "-")
            score_display = str(score_raw) if score_raw else "-"

            status_info = comp.get("status", {})
            status_type = status_info.get("type", {}).get("name", "") if isinstance(status_info, dict) else ""
            status = status_type.upper() if status_type.upper() in ("CUT", "MC", "WD", "DQ") else None

            thru = None
            tee_time_str = ""
            linescores = comp.get("linescores", [])

            # In R3+, ESPN may not flag missed-cut players; detect via linescores:
            # anyone who made the cut has an entry for period >= 3.
            if status is None and target_period >= 3:
                has_post_cut_round = any(rd.get("period", 0) >= 3 for rd in linescores)
                if not has_post_cut_round:
                    status = "MC"

            current_round = None
            for rd in linescores:
                if rd.get("period") == target_period:
                    current_round = rd
                    break
            if current_round is None and linescores:
                current_round = linescores[-1]

            if current_round:
                hole_scores = current_round.get("linescores", [])
                if hole_scores:
                    thru = min(len(hole_scores), 18)
                else:
                    stats = current_round.get("statistics", {})
                    cats = stats.get("categories", []) if stats else []
                    for cat in cats:
                        for s in cat.get("stats", []):
                            dv = s.get("displayValue", "")
                            if any(tz in dv for tz in ("AM", "PM", "PDT", "PST", "EDT", "EST")):
                                try:
                                    cleaned = dv
                                    for tz in (" PDT ", " PST ", " EDT ", " EST ", " CDT ", " CST "):
                                        cleaned = cleaned.replace(tz, " ")
                                    dt = __import__("datetime").datetime.strptime(cleaned, "%a %b %d %H:%M:%S %Y")
                                    h = dt.hour
                                    ampm = "AM" if h < 12 else "PM"
                                    if h > 12: h -= 12
                                    if h == 0: h = 12
                                    tee_time_str = f"T{h}:{dt.minute:02d} {ampm}"
                                except Exception:
                                    pass

            today = tee_time_str if tee_time_str else "-"
            if current_round:
                today_val = current_round.get("displayValue", "-")
                if today_val and today_val != "-":
                    today = today_val

            raw_golfers.append({
                "name": name, "name_norm": resolve_name(name),
                "order": order, "status": status, "score": score_display,
                "today": today, "thru": thru, "tee_time": tee_time_str,
            })

        active = [g for g in raw_golfers if g["status"] is None]
        inactive = [g for g in raw_golfers if g["status"] is not None]

        pos = 1
        i = 0
        while i < len(active):
            j = i
            while j < len(active) and active[j]["score"] == active[i]["score"]:
                j += 1
            tied = j - i > 1
            for k in range(i, j):
                active[k]["pos_int"] = pos
                active[k]["pos_str"] = f"T{pos:02d}" if tied else f"{pos:02d}"
            pos = j + 1
            i = j

        # "In play" = still has golf to play right now (on the course or yet to tee
        # off today) and not eliminated -> a participant's remaining scoring ammo.
        FINAL_ROUND = 4
        tournament_over = target_period > FINAL_ROUND

        for g in active:
            thru = g["thru"]
            in_play = (not tournament_over) and (thru is None or thru < 18)
            golfers.append({
                "name": g["name"], "name_norm": g["name_norm"],
                "pos_str": g["pos_str"], "pos_int": g["pos_int"],
                "status": None, "score": g["score"], "today": g["today"],
                "thru": g["thru"], "tee_time": g.get("tee_time", ""),
                "points": points_for_position(g["pos_int"], None),
                "proj_mc": False, "in_play": in_play,
            })

        for g in inactive:
            golfers.append({
                "name": g["name"], "name_norm": g["name_norm"],
                "pos_str": g["status"] or "-", "pos_int": None,
                "status": g["status"], "score": g["score"],
                "today": g.get("today", "-"), "thru": g["thru"],
                "tee_time": g.get("tee_time", ""),
                "points": 0, "proj_mc": True, "in_play": False,
            })
    except Exception as e:
        return None, f"Parse error: {e}", None

    # Projected cut line — only meaningful before R3 starts. Once in R3+ the cut
    # is locked: any golfer still active (not MC-flagged) HAS made the cut.
    projected_cut = None
    if target_period <= 2:
        active_scores = []
        for g in golfers:
            if g.get("status") in ("CUT", "MC", "WD", "DQ"):
                continue
            s = score_to_int(g["score"])
            if s is not None:
                active_scores.append(s)
        active_scores.sort()
        if len(active_scores) >= CUT_TOP_N:
            projected_cut = active_scores[CUT_TOP_N - 1]
            for g in golfers:
                if g.get("status"):
                    continue
                s = score_to_int(g["score"])
                if s is not None and s > projected_cut:
                    g["proj_mc"] = True
                    g["points"] = 0

    return golfers, event_name, projected_cut


# === LOAD ROSTERS ===
@st.cache_data(ttl=300)
def load_rosters():
    df = pd.read_csv(ROSTER_PATH, encoding="utf-8")
    df["Golfer_Norm"] = df["Golfer"].apply(resolve_name)
    return df


# === OPTIONAL SEASON STANDINGS ===
# Drop prior-major finals here as CSVs with columns [Participant, Points] named
# e.g. masters_final.csv, pga_final.csv — they'll roll up into season standings.
def load_prior_finals():
    # Not cached: files are tiny, and caching risks serving a stale empty result
    # from a build that predated the CSVs.
    finals, diag = {}, []
    for fname, label in [("masters_final.csv", "Masters"), ("pga_final.csv", "PGA")]:
        path = os.path.join(DIR, fname)
        if not os.path.exists(path):
            diag.append(f"{fname}: not found")
            continue
        try:
            d = pd.read_csv(path, encoding="utf-8")
            pts_col = next((c for c in d.columns if c.lower().endswith("points") or c.lower() == "points"), None)
            if "Participant" in d.columns and pts_col:
                finals[label] = dict(zip(d["Participant"], pd.to_numeric(d[pts_col], errors="coerce").fillna(0)))
                diag.append(f"{fname}: {len(finals[label])} rows")
            else:
                diag.append(f"{fname}: missing Participant/Points columns ({list(d.columns)})")
        except Exception as e:
            diag.append(f"{fname}: error {e}")
    return finals, diag


# === COMPUTE SCORES ===
def compute_pool_scores(rosters, golfers_live):
    live_lookup = {g["name_norm"]: g for g in golfers_live}
    live_names = list(live_lookup.keys())

    def best_match(roster_norm):
        if roster_norm in live_lookup:
            return live_lookup[roster_norm]
        roster_parts = set(roster_norm.split())
        for ln in live_names:
            if len(roster_parts & set(ln.split())) >= 2:
                return live_lookup[ln]
        for ln in live_names:
            if roster_norm.split()[-1] == ln.split()[-1] and len(roster_norm.split()[-1]) > 3:
                return live_lookup[ln]
        for ln in live_names:
            r_parts = roster_norm.split(); l_parts = ln.split()
            if len(r_parts) >= 2 and len(l_parts) >= 2:
                if r_parts[0] == l_parts[0] and r_parts[-1][:3] == l_parts[-1][:3]:
                    return live_lookup[ln]
        return None

    participant_scores = []
    participant_details = {}
    participant_to_live = {}   # participant -> set of live golfer name_norms they roster
    live_to_participants = {}  # live golfer name_norm -> set of participants who roster them

    for participant, group in rosters.groupby("Participant"):
        total_pts = 0
        golfer_details = []
        live_set = set()
        for _, row in group.iterrows():
            match = best_match(row["Golfer_Norm"])
            if match:
                pts = match["points"]
                live_set.add(match["name_norm"])
                live_to_participants.setdefault(match["name_norm"], set()).add(participant)
                golfer_details.append({
                    "Golfer": row["Golfer"], "Price": f"${row['Price']:.2f}",
                    "Position": match["pos_str"], "_pos_sort": match["pos_int"] or 999,
                    "_proj_mc": match.get("proj_mc", False),
                    "_in_play": match.get("in_play", False),
                    "Score": score_to_int(match["score"]),
                    "Today": match.get("today", "-"), "Thru": match["thru"],
                    "tee_time": match.get("tee_time", ""), "Points": pts,
                })
            else:
                golfer_details.append({
                    "Golfer": row["Golfer"], "Price": f"${row['Price']:.2f}",
                    "Position": "-", "_pos_sort": 999, "_proj_mc": True, "_in_play": False,
                    "Score": score_to_int("-"), "Today": "-", "Thru": None,
                    "tee_time": "", "Points": 0,
                })
            total_pts += golfer_details[-1]["Points"]

        participant_to_live[participant] = live_set
        making_cut = sum(1 for g in golfer_details if not g.get("_proj_mc", False))
        live = sum(1 for g in golfer_details if g.get("_in_play", False))
        participant_scores.append({
            "Participant": participant, "Points": total_pts,
            "Golfers": len(group), "Making Cut": making_cut, "Live": live,
        })
        participant_details[participant] = sorted(
            golfer_details, key=lambda x: (-x["Points"], x["Score"] if x["Score"] is not None else 999, x["_pos_sort"]))

    df_scores = pd.DataFrame(participant_scores).sort_values(
        ["Points", "Making Cut"], ascending=False).reset_index(drop=True)

    ranks = []
    pos = 1; i = 0
    pts_list = df_scores["Points"].tolist()
    while i < len(pts_list):
        j = i
        while j < len(pts_list) and pts_list[j] == pts_list[i]:
            j += 1
        tied = j - i > 1
        for k in range(i, j):
            ranks.append(f"T{pos}" if tied else str(pos))
        pos = j + 1
        i = j
    df_scores.insert(0, "Rank", ranks)
    return df_scores, participant_details, participant_to_live, live_to_participants


# === FEDEX CUP SEASON STANDINGS ===
def _competition_ranks(participants, score_map):
    """Standard competition ranking (ties share the lower number, next rank skips)."""
    order = sorted(participants, key=lambda p: -score_map.get(p, 0))
    ranks = {}
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and score_map.get(order[j], 0) == score_map.get(order[i], 0):
            j += 1
        for k in range(i, j):
            ranks[order[k]] = i + 1   # competition rank = (# strictly above) + 1
        i = j
    return ranks


def render_fedex_cup(df_scores):
    finals, diag = load_prior_finals()
    st.markdown("### 🏆 FedEx Cup Season Standings")
    if not finals:
        st.warning("Season standings data not loaded yet. Diagnostics: " + "; ".join(diag))
        return
    M = finals.get("Masters", {})
    P = finals.get("PGA", {})
    us = df_scores.set_index("Participant")["Points"].to_dict()
    all_p = set(us) | set(M) | set(P)

    prior_total = {p: int(M.get(p, 0)) + int(P.get(p, 0)) for p in all_p}   # season pre-US Open
    total = {p: prior_total[p] + int(us.get(p, 0)) for p in all_p}
    before_rank = _competition_ranks(all_p, prior_total)
    after_rank = _competition_ranks(all_p, total)

    def move_str(p):
        # New to the season (only entered the US Open) -> NEW; otherwise rank delta
        if p not in M and p not in P:
            return "🆕 NEW"
        delta = before_rank[p] - after_rank[p]   # +ve = climbed
        if delta > 0:
            return f"▲ {delta}"
        if delta < 0:
            return f"▼ {-delta}"
        return "—"

    order = sorted(all_p, key=lambda p: (-total[p], after_rank[p]))
    rows = []
    for p in order:
        rows.append({
            "Rank": after_rank[p],
            "Move": move_str(p),
            "Participant": p,
            "Masters": int(M[p]) if p in M else pd.NA,
            "PGA": int(P[p]) if p in P else pd.NA,
            "US Open": int(us[p]) if p in us else pd.NA,
            "Total": total[p],
        })
    season_df = pd.DataFrame(rows)
    # Display rank with ties shown as "T"
    counts = season_df["Rank"].value_counts()
    season_df["Rank"] = season_df["Rank"].apply(lambda r: f"T{r}" if counts.get(r, 0) > 1 else str(r))
    for c in ["Masters", "PGA", "US Open", "Total"]:
        season_df[c] = season_df[c].astype("Int64")

    labels = " + ".join(list(finals.keys()) + ["US Open (live)"])
    st.caption(f"Combined points across {labels} 2026. **Move** = season-rank change from the US Open "
               "(vs. Masters + PGA only). The US Open column and movement update live.")

    def _color_move_col(col):
        out = []
        for val in col:
            s = str(val)
            if s.startswith("▲"): out.append("color: #1a7f37; font-weight: 700")
            elif s.startswith("▼"): out.append("color: #b91c1c; font-weight: 700")
            elif "NEW" in s: out.append("color: #6b21a8; font-weight: 700")
            else: out.append("color: #9aa0a6")
        return out
    try:
        styled = season_df.style.apply(_color_move_col, subset=["Move"]).format(na_rep="–", precision=0)
        st.dataframe(styled, use_container_width=True, hide_index=True,
                     height=min(760, 35 * min(len(season_df), 21) + 38))
    except Exception:
        # Fallback if Styler isn't supported in this environment
        st.dataframe(season_df, use_container_width=True, hide_index=True,
                     height=min(760, 35 * min(len(season_df), 21) + 38))
    st.caption("Dash = did not enter that tournament. Masters & PGA are final; US Open updates live.")


# === RIVALRY MODE (head-to-head "The Diff") ===
def _fmt_thru_cell(t):
    if t is None or (isinstance(t, float) and pd.isna(t)):
        return "—"
    t = int(t)
    return "F" if t >= 18 else str(t)


def render_rivalry(df_scores, participant_details):
    st.markdown("### ⚔️ Rivalry Mode — Head-to-Head")
    st.caption("Shared golfers cancel out — only each side's UNIQUE golfers move the margin. "
               "⛳ = still in play (live ammo). Root for your column, against theirs.")

    plist = df_scores["Participant"].tolist()
    pts_map = df_scores.set_index("Participant")["Points"].to_dict()
    rank_map = df_scores.set_index("Participant")["Rank"].to_dict()

    c1, c2 = st.columns(2)
    you = c1.selectbox("You", plist, index=0, key="rival_you")
    opp = c2.selectbox("Opponent", plist, index=min(1, len(plist) - 1), key="rival_opp")
    if you == opp:
        st.info("Pick two different participants to compare.")
        return

    def nmap(name):
        return {resolve_name(g["Golfer"]): g for g in participant_details.get(name, [])}
    you_map, opp_map = nmap(you), nmap(opp)
    shared = set(you_map) & set(opp_map)
    you_uniq = [you_map[n] for n in (set(you_map) - set(opp_map))]
    opp_uniq = [opp_map[n] for n in (set(opp_map) - set(you_map))]

    you_uniq_pts = sum(g["Points"] for g in you_uniq)
    opp_uniq_pts = sum(g["Points"] for g in opp_uniq)
    you_live = sum(1 for g in you_uniq if g.get("_in_play"))
    opp_live = sum(1 for g in opp_uniq if g.get("_in_play"))
    margin = pts_map[you] - pts_map[opp]
    leader = you if margin > 0 else (opp if margin < 0 else "Tied")

    m1, m2, m3 = st.columns(3)
    m1.metric(f"{you}  (#{rank_map[you]})", f"{pts_map[you]} pts")
    m2.metric("Margin", f"{margin:+d}", f"{leader} leads" if margin != 0 else "dead even",
              delta_color="normal" if margin >= 0 else "inverse")
    m3.metric(f"{opp}  (#{rank_map[opp]})", f"{pts_map[opp]} pts")

    st.caption(f"They share **{len(shared)}** golfers (identical points for both — they don't move the margin). "
               f"Unique ammo still live → **{you}: {you_live}**  ·  **{opp}: {opp_live}**.")

    def side_df(uniq):
        rows = [{
            "Golfer": g["Golfer"] + ("  ⛳" if g.get("_in_play") else ""),
            "Pos": g["Position"],
            "Score": _fmt_golf_score(g["Score"]),
            "Thru": _fmt_thru_cell(g["Thru"]),
            "Pts": g["Points"],
        } for g in uniq]
        if not rows:
            return pd.DataFrame(columns=["Golfer", "Pos", "Score", "Thru", "Pts"])
        return pd.DataFrame(rows).sort_values("Pts", ascending=False).reset_index(drop=True)

    l, r = st.columns(2)
    l.markdown(f"**{you}'s edge** — {len(you_uniq)} unique · **{you_uniq_pts} pts**")
    l.dataframe(side_df(you_uniq), use_container_width=True, hide_index=True, height=360)
    r.markdown(f"**{opp}'s edge** — {len(opp_uniq)} unique · **{opp_uniq_pts} pts**")
    r.dataframe(side_df(opp_uniq), use_container_width=True, hide_index=True, height=360)


# === MAIN ===
def main():
    st.markdown("# ⛳ US Open Pool 2026")
    st.caption("Shinnecock Hills Golf Club")

    rosters = load_rosters()
    n_participants = rosters["Participant"].nunique()
    st.markdown(f"##### Live Scoring Leaderboard — {n_participants} Participants")

    result = fetch_leaderboard()
    if result is None or result[0] is None:
        st.error(f"Could not fetch leaderboard: {result[1] if result else 'Unknown error'}")
        st.info("The leaderboard will appear once tournament data is available from ESPN.")
        return
    golfers_live, event_info, projected_cut = result

    cut_str = ""
    if projected_cut is not None:
        cut_display = "E" if projected_cut == 0 else (f"+{projected_cut}" if projected_cut > 0 else str(projected_cut))
        cut_count = sum(1 for g in golfers_live if not g.get("status") and score_to_int(g["score"]) is not None and score_to_int(g["score"]) <= projected_cut)
        cut_str = f" | Projected cut: **{cut_display}** (top {CUT_TOP_N} + ties = {cut_count} golfers)"

    st.caption(f"**{event_info}** | Updated: {datetime.now(timezone.utc).strftime('%I:%M %p UTC')} | Auto-refreshes every 3 min{cut_str}")

    df_scores, participant_details, participant_to_live, live_to_participants = compute_pool_scores(rosters, golfers_live)

    # ---- Cross-highlight selection state ----
    ss = st.session_state
    ss.setdefault("hl_type", None)    # "participant" or "golfer"
    ss.setdefault("hl_value", None)

    def _sel_rows(key):
        s = ss.get(key)
        if not s:
            return []
        sel = getattr(s, "selection", None)
        if sel is None and isinstance(s, dict):
            sel = s.get("selection", {})
        rows = getattr(sel, "rows", None)
        if rows is None and isinstance(sel, dict):
            rows = sel.get("rows", [])
        return rows or []

    def on_pool_select():
        rows = _sel_rows("pool_tbl")
        if rows:
            ss.hl_type = "participant"
            ss.hl_value = ss.get("pool_pos_to_participant", [])[rows[0]]

    def on_field_select():
        rows = _sel_rows("field_tbl")
        if rows:
            ss.hl_type = "golfer"
            ss.hl_value = ss.get("field_pos_to_golfernorm", [])[rows[0]]

    # Resolve the active highlight into participant- and golfer-sets for this render
    hl_participants, hl_golfernorms, hl_label = set(), set(), None
    if ss.hl_type == "participant" and ss.hl_value in participant_to_live:
        hl_participants = {ss.hl_value}
        hl_golfernorms = participant_to_live[ss.hl_value]
        hl_label = (f"⛳ **{ss.hl_value}**'s golfers are highlighted in the field table below "
                    f"({len(hl_golfernorms)} matched to the field).")
    elif ss.hl_type == "golfer" and ss.hl_value:
        hl_golfernorms = {ss.hl_value}
        hl_participants = live_to_participants.get(ss.hl_value, set())
        gname = next((g["name"] for g in golfers_live if g["name_norm"] == ss.hl_value), ss.hl_value)
        hl_label = (f"👥 **{gname}** is rostered by **{len(hl_participants)}** participants — "
                    f"highlighted in the pool leaderboard.")

    # PODIUM
    if len(df_scores) >= 3:
        st.markdown("### Podium")
        cols = st.columns(3)
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, col in enumerate(cols):
            row = df_scores.iloc[i]
            col.metric(label=f"{medals[i]} {row['Participant']}", value=f"{row['Points']} pts", delta=f"{row['Golfers']} golfers")
    st.markdown("")

    # POOL LEADERBOARD + ROSTER DETAIL
    st.markdown("### 📊 Full Pool Leaderboard")
    st.caption("👉 **Click a participant row** to highlight their golfers in the field table below. "
               "**Click a golfer** in the field table to highlight everyone who rostered them here.")
    st.caption("**Live** = golfers still on the course or yet to tee off today — i.e. how much scoring "
               "ammo a participant still has in play right now.")

    if ss.hl_type:
        c1, c2 = st.columns([5, 1])
        c1.info(hl_label)
        if c2.button("✖ Clear", use_container_width=True):
            ss.hl_type, ss.hl_value = None, None
            st.rerun()

    # Map displayed row position -> participant (for the click callback)
    ss["pool_pos_to_participant"] = df_scores["Participant"].tolist()

    def _style_pool(row):
        on = row["Participant"] in hl_participants
        css = "background-color: #ffe08a; font-weight: 700" if on else ""
        return [css] * len(row)

    pool_styled = df_scores.style.apply(_style_pool, axis=1)
    st.dataframe(
        pool_styled, use_container_width=True,
        height=min(700, 35 * min(len(df_scores), 20) + 38), hide_index=True,
        key="pool_tbl", on_select=on_pool_select, selection_mode="single-row",
    )

    participant_list = df_scores["Participant"].tolist()
    selected = st.selectbox("🔍 Or search a participant to view their full roster:",
                            ["-- Show All --"] + participant_list)

    if selected and selected != "-- Show All --" and selected in participant_details:
        st.markdown("---")
        detail_df = pd.DataFrame(participant_details[selected]).drop(columns=["_pos_sort"], errors="ignore")
        detail_df = force_numeric_cols(detail_df)
        total = detail_df["Points"].sum()
        rank_row = df_scores[df_scores["Participant"] == selected]
        rank_str = rank_row["Rank"].values[0] if len(rank_row) > 0 else "?"
        st.markdown(f"### 🔎 {selected}")
        st.markdown(f"**Rank {rank_str}** — {len(detail_df)} golfers — **{total} points**")
        golf_dataframe(detail_df, use_container_width=True, hide_index=True)

    # RIVALRY MODE (head-to-head)
    st.markdown("---")
    try:
        render_rivalry(df_scores, participant_details)
    except Exception as e:
        st.error(f"Rivalry Mode failed to render: {e}")

    # TOURNAMENT LEADERBOARD + OWNERSHIP
    st.markdown("---")
    st.markdown("### ⛳ US Open Leaderboard & Ownership (Full Field)")
    if projected_cut is not None:
        cut_display = "E" if projected_cut == 0 else (f"+{projected_cut}" if projected_cut > 0 else str(projected_cut))
        over_display = "E" if projected_cut + 1 == 0 else (f"+{projected_cut + 1}" if projected_cut + 1 > 0 else str(projected_cut + 1))
        st.caption(f"Projected cut: {cut_display} (top {CUT_TOP_N} + ties). Golfers at {over_display} or worse are projected to miss the cut and score 0 pool points.")
    top_golfers = sorted(golfers_live, key=lambda x: (x["pos_int"] if x["pos_int"] else 999))

    ownership_exact = rosters.groupby("Golfer_Norm")["Participant"].nunique().to_dict()
    roster_norms_by_participant = rosters.groupby("Participant")["Golfer_Norm"].apply(set).to_dict()

    def count_owners(gn):
        count = 0
        gp = set(gn.split())
        for participant, golfer_norms in roster_norms_by_participant.items():
            for rn in golfer_norms:
                if rn == gn or len(set(rn.split()) & gp) >= 2:
                    count += 1
                    break
        return count

    combined_rows = []
    for g in top_golfers:
        gn = g["name_norm"]
        count = ownership_exact.get(gn, 0)
        if count == 0:
            count = count_owners(gn)
        combined_rows.append({
            "#": g["pos_int"] if g["pos_int"] else 999,
            "_proj_mc": g.get("proj_mc", False),
            "Pos": g["pos_str"], "Golfer": g["name"],
            "Score": score_to_int(g["score"]), "Today": g.get("today", "-"),
            "Thru": g["thru"], "tee_time": g.get("tee_time", ""),
            "Pool Pts": g["points"],
            "Rostered": f"{count}/{n_participants}",
            "Own %": round(count / n_participants * 100),
        })
    combined_df = pd.DataFrame(combined_rows).sort_values(["#"]).drop(columns=["#"]).reset_index(drop=True)
    combined_df = force_numeric_cols(combined_df)

    # Map displayed row position -> live golfer norm (for the click callback) and
    # build the per-row highlight mask from the active participant's golfers.
    # NOTE: compute these from the CLEAN names first so matching is unaffected.
    field_norms_in_order = [resolve_name(g) for g in combined_df["Golfer"].tolist()]
    ss["field_pos_to_golfernorm"] = field_norms_in_order
    field_highlight = [n in hl_golfernorms for n in field_norms_in_order]
    # Tag Amateur Pod players with "(a)" — display only, after matching is set.
    combined_df["Golfer"] = [f"{g} (a)" if n in AMATEUR_NORMS else g
                             for g, n in zip(combined_df["Golfer"].tolist(), field_norms_in_order)]
    st.caption("Amateurs (Amateur Pod) are marked **(a)**.")
    golf_dataframe(combined_df, use_container_width=True, hide_index=True,
                   key="field_tbl", on_select=on_field_select, highlight_rows=field_highlight)

    # BEST VALUE PICKS
    st.markdown("### 💰 Best Value Picks (Points per Dollar)")
    roster_price_lookup = rosters.drop_duplicates("Golfer_Norm").set_index("Golfer_Norm")["Price"].to_dict()
    all_roster_norms = set(roster_price_lookup.keys())
    value_picks = []
    seen = set()
    for g in golfers_live:
        if g["points"] <= 0: continue
        gn = g["name_norm"]
        price = roster_price_lookup.get(gn)
        if price is None:
            gp = set(gn.split())
            for rn in all_roster_norms:
                if len(set(rn.split()) & gp) >= 2:
                    price = roster_price_lookup[rn]
                    break
        if price and price > 0 and g["name"] not in seen:
            value_picks.append({
                "Golfer": g["name"], "Score": score_to_int(g["score"]),
                "Pool Pts": g["points"], "Price": f"${price:.2f}",
                "Pts/$": round(g["points"] / price, 1),
            })
            seen.add(g["name"])
    if value_picks:
        value_picks.sort(key=lambda x: x["Pts/$"], reverse=True)
        vp_df = force_numeric_cols(pd.DataFrame(value_picks[:12]))
        golf_dataframe(vp_df, use_container_width=True, hide_index=True)

    # FEDEX CUP SEASON STANDINGS (Masters + PGA + live US Open) — bottom of page
    st.markdown("---")
    try:
        render_fedex_cup(df_scores)
    except Exception as e:
        st.error(f"FedEx Cup standings failed to render: {e}")

    st.markdown("---")
    st.caption("US Open Pool 2026 | Scoring: W=90, 2nd=65, 3rd=60, 4th=55, 5th=50, 6-10=45-25, 11-15=20, 16-20=15, 21-25=10, 26-30=5, 31+=2, MC=0")
    st.caption("Data: ESPN | Built with Streamlit | Auto-refreshes every 3 minutes")


if __name__ == "__main__":
    main()
