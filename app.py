import os
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from database import init_db, get_db
from ai_client import generate_plan, get_daily_feedback, chat_with_ai

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "caldef-apple-inspired-secret-2024")

@app.context_processor
def inject_now():
    return {"now": datetime.now}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("landing"))
        return f(*args, **kwargs)
    return decorated


def calc_bmr(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    base = (10 * weight_kg) + (6.25 * height_cm) - (5 * age)
    return base + 5 if gender == "male" else base - 161


def calc_tdee(bmr: float, activity: str) -> float:
    multipliers = {"low": 1.2, "moderate": 1.55, "high": 1.725}
    return bmr * multipliers.get(activity, 1.375)


def calc_target(tdee: float, goal: str) -> int:
    if goal == "lose":
        return max(1200, int(tdee - 500))
    if goal == "gain":
        return int(tdee + 300)
    return int(tdee)


def get_profile(user_id: int):
    with get_db() as db:
        row = db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_today_logs(user_id: int):
    today = date.today().isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM food_logs WHERE user_id = ? AND date = ? ORDER BY logged_at ASC",
            (user_id, today)
        ).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────

@app.route("/")
def landing():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")

        try:
            with get_db() as db:
                cursor = db.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password)),
                )
                user_id = cursor.lastrowid
            session["user_id"] = user_id
            session["username"] = username
            return redirect(url_for("onboarding"))
        except Exception:
            flash("Username or email already taken.", "error")
            return render_template("register.html")

    return render_template("register.html")


@app.route("/login", methods=["POST"])
def login():
    identifier = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (identifier, identifier.lower()),
        ).fetchone()

    if user and check_password_hash(user["password_hash"], password):
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        profile = get_profile(user["id"])
        return redirect(url_for("dashboard") if profile else url_for("onboarding"))

    flash("Invalid username or password.", "error")
    return redirect(url_for("landing"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


# ──────────────────────────────────────────────
# Onboarding
# ──────────────────────────────────────────────

@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        try:
            height_cm = float(request.form.get("height_cm") or 170)
            weight_kg = float(request.form.get("weight_kg") or 70)
            age = int(request.form.get("age") or 25)
            gender = request.form.get("gender") or "male"
            activity_level = request.form.get("activity_level") or "moderate"
            goal = request.form.get("goal") or "lose"
        except (ValueError, TypeError) as e:
            flash(f"Invalid form values: {e}. Please fill in all fields.", "error")
            return render_template("onboarding.html")

        bmr = calc_bmr(weight_kg, height_cm, age, gender)
        tdee = calc_tdee(bmr, activity_level)
        target_calories = calc_target(tdee, goal)

        profile_data = {
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "age": age,
            "gender": gender,
            "activity_level": activity_level,
            "goal": goal,
            "bmr": bmr,
            "tdee": tdee,
            "target_calories": target_calories,
        }

        # Save profile first so user reaches dashboard even if AI is slow
        with get_db() as db:
            db.execute(
                """INSERT INTO profiles
                   (user_id, height_cm, weight_kg, age, gender, activity_level,
                    goal, bmr, tdee, target_calories, plan_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   height_cm=excluded.height_cm, weight_kg=excluded.weight_kg,
                   age=excluded.age, gender=excluded.gender,
                   activity_level=excluded.activity_level, goal=excluded.goal,
                   bmr=excluded.bmr, tdee=excluded.tdee,
                   target_calories=excluded.target_calories,
                   plan_text=excluded.plan_text,
                   updated_at=CURRENT_TIMESTAMP""",
                (session["user_id"], height_cm, weight_kg, age, gender,
                 activity_level, goal, bmr, tdee, target_calories,
                 "Generating your personalized plan..."),
            )

        # Generate AI plan (may take time)
        plan_text = generate_plan(profile_data)

        with get_db() as db:
            db.execute(
                "UPDATE profiles SET plan_text=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (plan_text, session["user_id"]),
            )

        return redirect(url_for("dashboard"))

    return render_template("onboarding.html")


# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    profile = get_profile(user_id)
    if not profile:
        return redirect(url_for("onboarding"))

    logs = get_today_logs(user_id)
    total_consumed = sum(log["calories"] for log in logs)
    total_protein = sum(log["protein_g"] for log in logs)
    total_carbs = sum(log["carbs_g"] for log in logs)
    total_fat = sum(log["fat_g"] for log in logs)
    target = profile["target_calories"]
    remaining = target - total_consumed
    pct = min(100, round((total_consumed / target * 100) if target else 0))

    today = date.today().isoformat()
    with get_db() as db:
        fb_row = db.execute(
            "SELECT feedback FROM daily_feedback WHERE user_id = ? AND date = ?",
            (user_id, today)
        ).fetchone()
    ai_feedback = fb_row["feedback"] if fb_row else None

    return render_template(
        "dashboard.html",
        profile=profile,
        logs=logs,
        total_consumed=total_consumed,
        total_protein=round(total_protein, 1),
        total_carbs=round(total_carbs, 1),
        total_fat=round(total_fat, 1),
        target=target,
        remaining=remaining,
        pct=pct,
        ai_feedback=ai_feedback,
        today=date.today().strftime("%A, %B %-d"),
    )


@app.route("/api/feedback", methods=["POST"])
@login_required
def api_feedback():
    user_id = session["user_id"]
    profile = get_profile(user_id)
    logs = get_today_logs(user_id)
    consumed = sum(log["calories"] for log in logs)
    today = date.today().isoformat()

    feedback = get_daily_feedback(profile, session["username"], consumed, logs)

    with get_db() as db:
        db.execute(
            """INSERT INTO daily_feedback (user_id, date, feedback, total_calories)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET
               feedback=excluded.feedback, total_calories=excluded.total_calories""",
            (user_id, today, feedback, consumed),
        )

    return jsonify({"feedback": feedback})


# ──────────────────────────────────────────────
# Food Logging
# ──────────────────────────────────────────────

@app.route("/log")
@login_required
def log_food():
    user_id = session["user_id"]
    profile = get_profile(user_id)
    logs = get_today_logs(user_id)
    total_consumed = sum(log["calories"] for log in logs)
    target = profile["target_calories"] if profile else 2000
    remaining = target - total_consumed

    return render_template(
        "log_food.html",
        logs=logs,
        total_consumed=total_consumed,
        target=target,
        remaining=remaining,
    )


@app.route("/api/food", methods=["POST"])
@login_required
def api_add_food():
    data = request.get_json()
    user_id = session["user_id"]
    today = date.today().isoformat()

    food_name = (data.get("food_name") or "").strip()
    calories = int(data.get("calories", 0))
    protein_g = float(data.get("protein_g", 0))
    carbs_g = float(data.get("carbs_g", 0))
    fat_g = float(data.get("fat_g", 0))
    meal_type = data.get("meal_type", "meal")

    if not food_name or calories <= 0:
        return jsonify({"error": "Food name and calories are required."}), 400

    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO food_logs (user_id, date, meal_type, food_name, calories,
               protein_g, carbs_g, fat_g) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, today, meal_type, food_name, calories, protein_g, carbs_g, fat_g),
        )
        food_id = cursor.lastrowid

    return jsonify({
        "id": food_id,
        "food_name": food_name,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "meal_type": meal_type,
    })


@app.route("/api/food/<int:food_id>", methods=["DELETE"])
@login_required
def api_delete_food(food_id):
    with get_db() as db:
        db.execute(
            "DELETE FROM food_logs WHERE id = ? AND user_id = ?",
            (food_id, session["user_id"]),
        )
    return jsonify({"success": True})


@app.route("/api/today")
@login_required
def api_today():
    user_id = session["user_id"]
    profile = get_profile(user_id)
    logs = get_today_logs(user_id)
    consumed = sum(log["calories"] for log in logs)
    target = profile["target_calories"] if profile else 2000
    return jsonify({
        "consumed": consumed,
        "target": target,
        "remaining": target - consumed,
        "pct": min(100, round((consumed / target * 100) if target else 0)),
    })


# ──────────────────────────────────────────────
# Chat
# ──────────────────────────────────────────────

@app.route("/chat")
@login_required
def chat():
    user_id = session["user_id"]
    with get_db() as db:
        rows = db.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()
    messages = list(reversed([dict(r) for r in rows]))
    return render_template("chat.html", messages=messages)


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json()
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Message is required."}), 400

    user_id = session["user_id"]
    profile = get_profile(user_id)
    logs = get_today_logs(user_id)
    consumed = sum(log["calories"] for log in logs)

    with get_db() as db:
        rows = db.execute(
            "SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        ).fetchall()
    history = list(reversed([dict(r) for r in rows]))

    ai_response = chat_with_ai(profile or {}, session["username"], history, user_message, consumed, logs)

    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            "INSERT INTO chat_messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, "user", user_message)
        )
        db.execute(
            "INSERT INTO chat_messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, "assistant", ai_response)
        )

    return jsonify({"response": ai_response})


# ──────────────────────────────────────────────
# History
# ──────────────────────────────────────────────

@app.route("/history")
@login_required
def history():
    return render_template("history.html")


@app.route("/api/history")
@login_required
def api_history():
    user_id = session["user_id"]
    days = int(request.args.get("days", 30))
    start = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as db:
        rows = db.execute(
            """SELECT date, SUM(calories) as total,
               SUM(protein_g) as protein, SUM(carbs_g) as carbs, SUM(fat_g) as fat,
               COUNT(*) as entries
               FROM food_logs WHERE user_id = ? AND date >= ?
               GROUP BY date ORDER BY date ASC""",
            (user_id, start)
        ).fetchall()
        weight_rows = db.execute(
            "SELECT date, weight_kg FROM weight_logs WHERE user_id = ? AND date >= ? ORDER BY date ASC",
            (user_id, start)
        ).fetchall()

    profile = get_profile(user_id)
    return jsonify({
        "logs": [dict(r) for r in rows],
        "weight": [dict(r) for r in weight_rows],
        "target": profile["target_calories"] if profile else 2000,
    })


@app.route("/api/weight", methods=["POST"])
@login_required
def api_log_weight():
    data = request.get_json()
    weight_kg = float(data.get("weight_kg", 0))
    if weight_kg <= 0:
        return jsonify({"error": "Invalid weight."}), 400

    today = date.today().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO weight_logs (user_id, date, weight_kg)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET weight_kg=excluded.weight_kg""",
            (session["user_id"], today, weight_kg),
        )
    return jsonify({"success": True, "weight_kg": weight_kg})


# ──────────────────────────────────────────────
# Profile
# ──────────────────────────────────────────────

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]
    if request.method == "POST":
        height_cm = float(request.form.get("height_cm", 170))
        weight_kg = float(request.form.get("weight_kg", 70))
        age = int(request.form.get("age", 25))
        gender = request.form.get("gender", "male")
        activity_level = request.form.get("activity_level", "moderate")
        goal = request.form.get("goal", "lose")

        bmr = calc_bmr(weight_kg, height_cm, age, gender)
        tdee = calc_tdee(bmr, activity_level)
        target_calories = calc_target(tdee, goal)

        with get_db() as db:
            db.execute(
                """UPDATE profiles SET height_cm=?, weight_kg=?, age=?, gender=?,
                   activity_level=?, goal=?, bmr=?, tdee=?, target_calories=?,
                   updated_at=CURRENT_TIMESTAMP WHERE user_id=?""",
                (height_cm, weight_kg, age, gender, activity_level, goal,
                 bmr, tdee, target_calories, user_id),
            )

        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    prof = get_profile(user_id)
    with get_db() as db:
        user = db.execute("SELECT username, email FROM users WHERE id = ?", (user_id,)).fetchone()
    return render_template("profile.html", profile=prof, user=dict(user) if user else {})


# ──────────────────────────────────────────────
# Plan
# ──────────────────────────────────────────────

@app.route("/api/regenerate-plan", methods=["POST"])
@login_required
def api_regenerate_plan():
    user_id = session["user_id"]
    profile = get_profile(user_id)
    if not profile:
        return jsonify({"error": "No profile found."}), 404

    plan_text = generate_plan(profile)
    with get_db() as db:
        db.execute(
            "UPDATE profiles SET plan_text=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
            (plan_text, user_id),
        )
    return jsonify({"plan": plan_text})


# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5050)
