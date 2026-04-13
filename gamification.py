"""
Gamification engine — points, streaks, achievements, leaderboard.

Points weighting (by design):
  - Logging meals / staying active  →  majority of XP
  - Weight loss milestones          →  small bonus (honest, not primary driver)
  - Streaks                         →  multiplied over time
  - AI interaction                  →  rewards engagement
"""

from datetime import date, timedelta
from database import get_db

# ──────────────────────────────────────────────
# Achievement catalogue
# ──────────────────────────────────────────────

ACHIEVEMENTS = {
    # Logging milestones
    "first_log":     {"name": "First Step",       "icon": "⭐", "desc": "Logged your very first meal",             "points": 50},
    "meals_10":      {"name": "Getting Into It",  "icon": "📋", "desc": "Logged 10 meals total",                  "points": 75},
    "meals_50":      {"name": "Committed",         "icon": "📊", "desc": "Logged 50 meals total",                  "points": 150},
    "meals_100":     {"name": "Data Lover",        "icon": "🗂️", "desc": "Logged 100 meals total",                 "points": 300},
    "meals_250":     {"name": "Obsessed (Nice)",   "icon": "🏅", "desc": "Logged 250 meals total",                 "points": 500},

    # Streaks
    "streak_3":      {"name": "On a Roll",         "icon": "🔥", "desc": "3-day activity streak",                  "points": 75},
    "streak_7":      {"name": "On Fire",           "icon": "🔥", "desc": "7-day activity streak",                  "points": 200},
    "streak_14":     {"name": "Two Weeks Strong",  "icon": "💥", "desc": "14-day activity streak",                 "points": 350},
    "streak_30":     {"name": "Unstoppable",       "icon": "⚡", "desc": "30-day activity streak",                 "points": 750},

    # Calorie target adherence
    "on_target_3":   {"name": "Precision",         "icon": "🎯", "desc": "Hit your calorie target 3 days",         "points": 100},
    "on_target_7":   {"name": "Sharp Shooter",     "icon": "🎯", "desc": "Hit your calorie target 7 days",         "points": 300},
    "on_target_14":  {"name": "Laser Focused",     "icon": "🔬", "desc": "Hit your calorie target 14 days",        "points": 600},

    # Meal variety
    "full_day":      {"name": "Full Day",          "icon": "🌈", "desc": "Logged breakfast, lunch, dinner & snack in one day", "points": 75},
    "full_day_7":    {"name": "Balanced Week",     "icon": "📅", "desc": "Full day logging 7 different days",      "points": 200},

    # Weight logging engagement
    "weight_logs_7":  {"name": "Scale Tracker",   "icon": "⚖️", "desc": "Logged weight 7 times",                  "points": 100},
    "weight_logs_30": {"name": "Weight Watcher",  "icon": "📏", "desc": "Logged weight 30 times",                 "points": 300},

    # Weight loss (small bonus — honest about difficulty)
    "weight_loss_1":  {"name": "First Kilo",       "icon": "📉", "desc": "Lost 1 kg from your starting weight",    "points": 150},
    "weight_loss_3":  {"name": "Progress!",        "icon": "💪", "desc": "Lost 3 kg from your starting weight",    "points": 300},
    "weight_loss_5":  {"name": "Halfway Hero",     "icon": "🌟", "desc": "Lost 5 kg from your starting weight",    "points": 500},
    "weight_loss_10": {"name": "Transformation",  "icon": "🏆", "desc": "Lost 10 kg from your starting weight",   "points": 1000},

    # AI coach interaction
    "chat_5":        {"name": "Curious",           "icon": "💬", "desc": "Asked your coach 5 questions",           "points": 50},
    "chat_25":       {"name": "Engaged",           "icon": "🗣️", "desc": "Asked your coach 25 questions",          "points": 150},
    "chat_100":      {"name": "Coach's Favourite", "icon": "🤝", "desc": "Asked your coach 100 questions",         "points": 400},
}

# ──────────────────────────────────────────────
# Levels (XP thresholds)
# ──────────────────────────────────────────────

LEVELS = [
    (0,      "Bronze",   "#CD7F32", "🥉"),
    (500,    "Silver",   "#8E8E93", "🥈"),
    (1500,   "Gold",     "#FFD700", "🥇"),
    (4000,   "Platinum", "#5AC8FA", "💎"),
    (10000,  "Diamond",  "#AF52DE", "👑"),
]


def get_level(points: int) -> dict:
    level = LEVELS[0]
    for entry in LEVELS:
        if points >= entry[0]:
            level = entry
    next_threshold = None
    for entry in LEVELS:
        if points < entry[0]:
            next_threshold = entry[0]
            break
    return {
        "name": level[1], "color": level[2], "icon": level[3],
        "next": next_threshold,
        "progress": _level_progress(points, level[0], next_threshold),
    }


def _level_progress(pts, current_min, next_min):
    if next_min is None:
        return 100
    span = next_min - current_min
    earned = pts - current_min
    return min(100, round(earned / span * 100)) if span else 100


# ──────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────

def _ensure_row(user_id: int):
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO user_points (user_id) VALUES (?)", (user_id,))


def _add_points(user_id: int, pts: int):
    _ensure_row(user_id)
    with get_db() as db:
        db.execute(
            "UPDATE user_points SET total_points = total_points + ? WHERE user_id = ?",
            (pts, user_id),
        )


def _grant(user_id: int, key: str) -> dict | None:
    """Try to grant achievement. Returns achievement data if newly granted, else None."""
    if key not in ACHIEVEMENTS:
        return None
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO achievements (user_id, achievement_key) VALUES (?, ?)",
                (user_id, key),
            )
        _add_points(user_id, ACHIEVEMENTS[key]["points"])
        return ACHIEVEMENTS[key]
    except Exception:
        return None  # Already earned (UNIQUE constraint)


def _update_streak(user_id: int) -> int:
    """Advance streak if first activity today. Returns new streak count."""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _ensure_row(user_id)

    with get_db() as db:
        row = db.execute(
            "SELECT last_activity_date, current_streak, longest_streak FROM user_points WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if not row or row["last_activity_date"] == today:
        return row["current_streak"] if row else 1

    new_streak = (row["current_streak"] or 0) + 1 if row["last_activity_date"] == yesterday else 1
    new_longest = max(new_streak, row["longest_streak"] or 0)

    with get_db() as db:
        db.execute(
            "UPDATE user_points SET current_streak=?, longest_streak=?, last_activity_date=? WHERE user_id=?",
            (new_streak, new_longest, today, user_id),
        )
    return new_streak


def _check_streak_achievements(user_id: int, streak: int) -> list:
    earned = []
    for threshold, key in [(3, "streak_3"), (7, "streak_7"), (14, "streak_14"), (30, "streak_30")]:
        if streak >= threshold:
            a = _grant(user_id, key)
            if a:
                earned.append(a)
    return earned


def _check_meal_count_achievements(user_id: int, total: int) -> list:
    earned = []
    for threshold, key in [(1, "first_log"), (10, "meals_10"), (50, "meals_50"), (100, "meals_100"), (250, "meals_250")]:
        if total >= threshold:
            a = _grant(user_id, key)
            if a:
                earned.append(a)
    return earned


# ──────────────────────────────────────────────
# Public trigger functions (called from app.py)
# ──────────────────────────────────────────────

def process_meal_logged(user_id: int) -> dict:
    _ensure_row(user_id)
    today = date.today().isoformat()

    _add_points(user_id, 10)
    streak = _update_streak(user_id)
    earned = []

    with get_db() as db:
        total_meals = db.execute(
            "SELECT COUNT(*) as c FROM food_logs WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        meal_types_today = {r["meal_type"] for r in db.execute(
            "SELECT DISTINCT meal_type FROM food_logs WHERE user_id = ? AND date = ?",
            (user_id, today),
        ).fetchall()}
        full_day_count = db.execute(
            """SELECT COUNT(DISTINCT date) as c FROM (
               SELECT date FROM food_logs WHERE user_id = ?
               GROUP BY date
               HAVING COUNT(DISTINCT meal_type) >= 4
            )""",
            (user_id,),
        ).fetchone()["c"]

    earned += _check_meal_count_achievements(user_id, total_meals)
    earned += _check_streak_achievements(user_id, streak)

    if {"breakfast", "lunch", "dinner", "snack"}.issubset(meal_types_today):
        a = _grant(user_id, "full_day")
        if a:
            earned.append(a)
    if full_day_count >= 7:
        a = _grant(user_id, "full_day_7")
        if a:
            earned.append(a)

    return {"points_earned": 10, "streak": streak, "achievements": earned}


def process_weight_logged(user_id: int, new_weight: float) -> dict:
    _ensure_row(user_id)

    # Only award base points once per day
    today = date.today().isoformat()
    with get_db() as db:
        already_today = db.execute(
            "SELECT COUNT(*) as c FROM weight_logs WHERE user_id = ? AND date = ? AND date < ?",
            (user_id, today, today),
        ).fetchone()["c"]
        total_logs = db.execute(
            "SELECT COUNT(*) as c FROM weight_logs WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        profile = db.execute(
            "SELECT weight_kg FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()

    pts = 20
    _add_points(user_id, pts)
    streak = _update_streak(user_id)
    earned = []

    for threshold, key in [(7, "weight_logs_7"), (30, "weight_logs_30")]:
        if total_logs >= threshold:
            a = _grant(user_id, key)
            if a:
                earned.append(a)

    # Weight loss milestones vs starting weight in profile
    if profile and profile["weight_kg"]:
        lost = profile["weight_kg"] - new_weight
        for threshold, key in [(1, "weight_loss_1"), (3, "weight_loss_3"), (5, "weight_loss_5"), (10, "weight_loss_10")]:
            if lost >= threshold:
                a = _grant(user_id, key)
                if a:
                    earned.append(a)

    earned += _check_streak_achievements(user_id, streak)
    return {"points_earned": pts, "streak": streak, "achievements": earned}


def process_feedback(user_id: int, consumed: int, target: int) -> dict:
    _ensure_row(user_id)
    on_target = consumed <= target

    pts = 10 + (50 if on_target else 0)
    _add_points(user_id, pts)
    streak = _update_streak(user_id)
    earned = []

    if on_target:
        with get_db() as db:
            days_on_target = db.execute(
                """SELECT COUNT(*) as c FROM daily_feedback df
                   JOIN profiles p ON p.user_id = df.user_id
                   WHERE df.user_id = ? AND df.total_calories <= p.target_calories""",
                (user_id,),
            ).fetchone()["c"]
        for threshold, key in [(3, "on_target_3"), (7, "on_target_7"), (14, "on_target_14")]:
            if days_on_target >= threshold:
                a = _grant(user_id, key)
                if a:
                    earned.append(a)

    earned += _check_streak_achievements(user_id, streak)
    return {"points_earned": pts, "on_target": on_target, "streak": streak, "achievements": earned}


def process_ai_chat(user_id: int) -> dict:
    _ensure_row(user_id)
    _add_points(user_id, 15)
    streak = _update_streak(user_id)
    earned = []

    with get_db() as db:
        chat_count = db.execute(
            "SELECT COUNT(*) as c FROM chat_messages WHERE user_id = ? AND role = 'user'",
            (user_id,),
        ).fetchone()["c"]

    for threshold, key in [(5, "chat_5"), (25, "chat_25"), (100, "chat_100")]:
        if chat_count >= threshold:
            a = _grant(user_id, key)
            if a:
                earned.append(a)

    earned += _check_streak_achievements(user_id, streak)
    return {"points_earned": 15, "streak": streak, "achievements": earned}


# ──────────────────────────────────────────────
# Stats & leaderboard queries
# ──────────────────────────────────────────────

def get_user_stats(user_id: int) -> dict:
    _ensure_row(user_id)
    with get_db() as db:
        pts_row = db.execute(
            "SELECT total_points, current_streak, longest_streak FROM user_points WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        earned_rows = db.execute(
            "SELECT achievement_key, earned_at FROM achievements WHERE user_id = ? ORDER BY earned_at DESC",
            (user_id,),
        ).fetchall()
        rank = db.execute(
            """SELECT COUNT(*) + 1 as r FROM user_points
               WHERE total_points > (SELECT total_points FROM user_points WHERE user_id = ?)""",
            (user_id,),
        ).fetchone()["r"]

    total_points = pts_row["total_points"] if pts_row else 0
    current_streak = pts_row["current_streak"] if pts_row else 0
    longest_streak = pts_row["longest_streak"] if pts_row else 0

    achievements = []
    for row in earned_rows:
        key = row["achievement_key"]
        meta = ACHIEVEMENTS.get(key, {})
        achievements.append({
            "key": key,
            "name": meta.get("name", key),
            "icon": meta.get("icon", "🏅"),
            "desc": meta.get("desc", ""),
            "earned_at": row["earned_at"],
        })

    return {
        "total_points": total_points,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "rank": rank,
        "achievement_count": len(achievements),
        "achievements": achievements,
        "level": get_level(total_points),
    }


def get_leaderboard(limit: int = 50) -> list:
    with get_db() as db:
        rows = db.execute(
            """SELECT u.id, u.username,
                      COALESCE(up.total_points, 0)   AS total_points,
                      COALESCE(up.current_streak, 0) AS current_streak,
                      COALESCE(up.longest_streak, 0) AS longest_streak,
                      (SELECT COUNT(*) FROM achievements a WHERE a.user_id = u.id) AS achievement_count
               FROM users u
               LEFT JOIN user_points up ON up.user_id = u.id
               ORDER BY total_points DESC, current_streak DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    result = []
    for i, row in enumerate(rows):
        d = dict(row)
        d["rank"] = i + 1
        d["level"] = get_level(d["total_points"])
        result.append(d)
    return result
