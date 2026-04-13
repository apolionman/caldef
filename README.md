# CalDef — AI Calorie Deficit Tracker

A clean, Apple-inspired web app for tracking your daily calorie intake with an AI nutrition coach. Built with Flask and powered by a local LLM endpoint.

---

## Features

- **Smart onboarding** — enter your height, weight, age, gender, and activity level; the app calculates your BMR and TDEE using the Mifflin-St Jeor equation and sets a science-based calorie target
- **AI nutrition plan** — your AI coach generates a personalized, realistic plan on sign-up
- **Daily food logging** — log meals by name and calories (macros optional), with quick-pick common foods
- **Calorie ring dashboard** — animated donut chart showing consumed vs. remaining calories at a glance
- **AI daily feedback** — on-demand coach check-ins based on your actual intake that day
- **AI chat** — ask your coach anything; it has full context of your profile and today's meals
- **Progress history** — 7/14/30-day calorie bar charts, weight trend line, and day-by-day log table
- **Weight logging** — optional daily weigh-ins tracked over time
- **Mobile-friendly** — iOS-style bottom navigation, responsive layout

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 · Flask 3.0 · Gunicorn |
| Database | SQLite (file-based, zero config) |
| AI | Local LLM via OpenAI-compatible API |
| Frontend | Vanilla JS · CSS (Apple HIG design tokens) |
| Charts | Chart.js 4 |
| Markdown | marked.js 12 |

---

## Quick Start (Docker)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/) installed
- A running LLM endpoint compatible with the OpenAI chat completions API (default: `http://192.168.70.48:8000`)

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd caldef_app
```

Open `docker-compose.yml` and set a strong `SECRET_KEY`:

```yaml
environment:
  - SECRET_KEY=your-long-random-secret-here
```

If your AI endpoint is on a different host or uses a different model, update `ai_client.py`:

```python
AI_ENDPOINT = "http://<your-host>:<port>/v1/chat/completions"
AI_MODEL    = "your-model-name"
```

### 2. Build and run

```bash
docker compose up -d
```

The app is now running at **http://localhost:5050**

### 3. View logs

```bash
docker compose logs -f
```

### 4. Stop

```bash
docker compose down
```

The SQLite database is stored in a named Docker volume (`caldef_data`) and survives container restarts.

---

## Manual Installation (without Docker)

### Prerequisites

- Python 3.11+
- pip

### Steps

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
python3 app.py
```

The app starts at **http://localhost:5050** in Flask's development server.

To use a custom database path or secret key:

```bash
DATABASE_PATH=/path/to/caldef.db SECRET_KEY=mysecret python3 app.py
```

---

## Configuration

All configuration is done via environment variables:

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `caldef-apple-inspired-secret-2024` | Flask session signing key — **change in production** |
| `DATABASE_PATH` | `caldef.db` (cwd) | Absolute path to the SQLite database file |

AI endpoint and model are set directly in `ai_client.py`:

| Constant | Default |
|---|---|
| `AI_ENDPOINT` | `http://192.168.70.48:8000/v1/chat/completions` |
| `AI_MODEL` | `nvidia/Nemotron-Cascade-2-30B-A3B` |
| `TIMEOUT` | `60` seconds |

---

## Project Structure

```
caldef_app/
├── app.py              # Flask routes and application logic
├── ai_client.py        # LLM integration (plan, feedback, chat)
├── database.py         # SQLite schema and connection helper
├── requirements.txt    # Python dependencies
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── static/
│   ├── css/style.css   # Apple-inspired design system
│   └── js/main.js      # Toast notifications, flash auto-dismiss
└── templates/
    ├── base.html        # Navbar, bottom nav, flash messages
    ├── landing.html     # Landing page + sign-in form
    ├── register.html    # Registration
    ├── onboarding.html  # 3-step profile setup
    ├── dashboard.html   # Calorie ring, macros, AI feedback, meal list
    ├── log_food.html    # Food entry form and daily log table
    ├── chat.html        # AI coach chat (iOS Messages style)
    ├── history.html     # Charts and historical data
    └── profile.html     # Profile editor and metabolic summary
```

---

## Database Schema

```
users          — id, username, email, password_hash, created_at
profiles       — user_id, height_cm, weight_kg, age, gender,
                 activity_level, goal, bmr, tdee, target_calories, plan_text
food_logs      — user_id, date, meal_type, food_name, calories,
                 protein_g, carbs_g, fat_g
chat_messages  — user_id, role, content, created_at
daily_feedback — user_id, date, feedback, total_calories
weight_logs    — user_id, date, weight_kg
```

---

## Calorie Math

Targets are calculated server-side using the **Mifflin-St Jeor** equation:

```
BMR (men)   = (10 × kg) + (6.25 × cm) − (5 × age) + 5
BMR (women) = (10 × kg) + (6.25 × cm) − (5 × age) − 161

TDEE = BMR × activity multiplier
         low      → 1.20  (sedentary)
         moderate → 1.55  (light exercise)
         high     → 1.725 (very active)

Target = TDEE − 500  (lose)   → safe ~0.4 kg/week loss
       = TDEE        (maintain)
       = TDEE + 300  (gain)   → lean ~0.3 kg/week gain
       minimum 1,200 kcal/day enforced
```

---

## License

MIT
