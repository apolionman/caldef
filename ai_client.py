import re
import json as _json
from datetime import datetime as _dt
import requests

AI_ENDPOINT = "http://192.168.70.48:8000/v1/chat/completions"
AI_MODEL    = "nvidia/Nemotron-Cascade-2-30B-A3B"

# Per-call timeouts (seconds)
TIMEOUT_CHAT     = 120
TIMEOUT_FEEDBACK = 120
TIMEOUT_PLAN     = 300
TIMEOUT_VOICE    = 30

# ── Thinking-text detection ─────────────────────────────────────────────────
# Paragraphs whose first word(s) indicate the model leaked its internal reasoning.
_THINKING_PREFIXES = (
    # Classic reasoning preambles
    "we need to", "i need to", "let me think", "let me ", "let's think",
    "let's do", "let's write", "let me write", "let me provide",
    "okay so", "ok, ", "ok so", "alright,", "alright so",
    # Meta-commentary about the task
    "the user ", "user wants", "user is asking", "so the user",
    "the prompt:", "the goal is", "the task is",
    "this is a request", "this should", "this response",
    "response should", "we should respond", "i should respond",
    "we should ", "i should ", "i'll ", "we'll ",
    # Planning / instruction leaks
    "to respond", "based on the context", "the context shows",
    "looking at the", "step 1", "first, i", "let's see",
    "make sure", "so probably", "probably just",
    "keep it ", "keep the ", "keep responses",
    "provide ", "suggest ", "here's a plan", "here is a plan",
    "i will provide", "i will write", "i will give",
    # Transition markers the model uses before the real answer
    "here's my response", "here is my response",
    "here's the response", "here is the response",
)

# Regex to find a "transition marker" and extract everything AFTER it.
# Handles cases where thinking and real content are mixed in the same block.
_TRANSITION_RE = re.compile(
    r"(?:let'?s do[:\s]+|here'?s? (?:the |my )?(?:response|message|answer|feedback)[:\s]+|"
    r"so,?\s+here'?s?[:\s]+|here you go[:\s]+)"
    r"[\"']?(.+)",
    re.IGNORECASE | re.DOTALL,
)


def _strip_thinking(text: str) -> str:
    """Remove all chain-of-thought / planning text leaked by reasoning models."""
    # 1. Strip explicit <think>…</think> blocks (DeepSeek / Nemotron style)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # 2. Repeatedly strip leading planning paragraphs (up to 12 passes)
    for _ in range(12):
        blocks = re.split(r"\n{2,}", text.strip())
        if not blocks:
            break
        first_lower = blocks[0].strip().lower()
        if first_lower.startswith(_THINKING_PREFIXES):
            if len(blocks) > 1:
                # Check whether the current block contains a transition marker —
                # if so, the real answer starts inside it.
                m = _TRANSITION_RE.search(blocks[0])
                if m:
                    text = m.group(1).strip() + (
                        "\n\n" + "\n\n".join(blocks[1:]) if len(blocks) > 1 else ""
                    )
                else:
                    text = "\n\n".join(blocks[1:]).strip()
            else:
                # Only one block — try the transition extractor before giving up
                m = _TRANSITION_RE.search(text)
                text = m.group(1).strip() if m else text
            continue
        break

    # 3. Strip any leftover isolated single-line planning notes that snuck
    #    between real paragraphs (e.g. "Make sure to keep clear headings.")
    cleaned_blocks = []
    blocks = re.split(r"\n{2,}", text.strip())
    for b in blocks:
        b_lower = b.strip().lower()
        # A "planning note" is a short block (≤ 2 sentences) that starts with
        # a known prefix AND has no markdown heading / list / table markers.
        is_short  = len(b.strip().split(".")) <= 3
        has_style = bool(re.search(r"^#{1,3} |^\d+\.|^\*|^\-|\|", b.strip(), re.M))
        if is_short and not has_style and b_lower.startswith(_THINKING_PREFIXES):
            continue   # skip this planning note
        cleaned_blocks.append(b)
    text = "\n\n".join(cleaned_blocks).strip()

    return text


# ── Low-level API caller ────────────────────────────────────────────────────
# Preamble appended to every system prompt to suppress reasoning leakage.
_NO_PREAMBLE = (
    "\n\nCRITICAL: Begin your reply immediately with the actual content. "
    "Do NOT include any thinking, planning, reasoning steps, meta-commentary, "
    "or notes about how you will respond. No preamble. No postamble."
)


def _call_ai(messages: list, system_prompt: str = None, timeout: int = TIMEOUT_CHAT) -> str:
    all_messages = []
    if system_prompt:
        all_messages.append({"role": "system", "content": system_prompt + _NO_PREAMBLE})
    all_messages.extend(messages)

    # Ask the Nemotron model to disable its built-in thinking/reasoning mode.
    # vLLM / NIM servers that support this will honour it; others ignore the field.
    payload = {
        "model":  AI_MODEL,
        "messages": all_messages,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        resp = requests.post(
            AI_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        return _strip_thinking(raw)
    except requests.exceptions.ConnectionError:
        return "AI service is currently unreachable. Please check your network connection."
    except requests.exceptions.Timeout:
        return "AI response timed out. Please try again."
    except Exception:
        return "AI service error. Please try again later."


# ── Voice command parser ────────────────────────────────────────────────────
def parse_voice_command(transcript: str, today_logs: list,
                        target_calories: int, today_consumed: int) -> dict:
    """Parse a voice transcript into a structured food-log action."""
    hour = _dt.now().hour
    if hour < 10:
        default_meal = "breakfast"
    elif hour < 15:
        default_meal = "lunch"
    elif hour < 20:
        default_meal = "dinner"
    else:
        default_meal = "snack"

    log_summary = "; ".join(
        f'id={l["id"]} "{l["food_name"]}" {l["calories"]}kcal {l["meal_type"]}'
        for l in today_logs
    ) or "none"

    system = (
        f"You are a voice command parser for a calorie tracker. "
        f"Return ONLY a single JSON object, no markdown, no extra text.\n\n"
        f"Current time: {_dt.now().strftime('%I:%M %p')}. Default meal: {default_meal}.\n"
        f"Today's log (id, name, kcal, meal): {log_summary}\n"
        f"Target: {target_calories} kcal | Consumed: {today_consumed} kcal\n\n"
        f"Supported actions:\n"
        f'ADD:    {{"action":"add_food","food_name":"...","calories":N,"meal_type":"breakfast|lunch|dinner|snack","protein_g":0,"carbs_g":0,"fat_g":0,"speak":"Added X (N kcal) to your meal."}}\n'
        f'EDIT:   {{"action":"edit_food","log_id":N,"food_name":"...","calories":N,"meal_type":"...","protein_g":0,"carbs_g":0,"fat_g":0,"speak":"Updated X to N calories."}}\n'
        f'DELETE: {{"action":"delete_food","log_id":N,"speak":"Removed X from your log."}}\n'
        f'QUERY:  {{"action":"query","speak":"...natural language answer..."}}\n'
        f'UNCLEAR:{{"action":"unknown","speak":"Sorry, I didn\'t catch that. Try: add breakfast egg white 36 calories."}}\n\n'
        f"Rules: infer calories for common foods if not stated; "
        f'use log ids from today\'s log for edit/delete; meal defaults to "{default_meal}".'
    )

    raw = _call_ai(
        [{"role": "user", "content": transcript}],
        system_prompt=system,
        timeout=TIMEOUT_VOICE,
    )

    try:
        clean = raw.strip()
        if "```" in clean:
            for part in clean.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    clean = part
                    break
        start = clean.find("{")
        end   = clean.rfind("}")
        if start != -1 and end != -1:
            clean = clean[start : end + 1]
        return _json.loads(clean)
    except Exception:
        return {
            "action": "unknown",
            "speak":  "I had trouble parsing that command. Please try again.",
        }


# ── Nutrition plan ──────────────────────────────────────────────────────────
def generate_plan(profile: dict) -> str:
    activity_desc = {
        "low":      "sedentary (little to no exercise)",
        "moderate": "moderately active (light exercise 3-5 days/week)",
        "high":     "very active (hard exercise 6-7 days/week)",
    }.get(profile["activity_level"], "moderately active")

    goal_desc = {
        "lose":     "lose weight (calorie deficit)",
        "maintain": "maintain current weight",
        "gain":     "gain weight/muscle (calorie surplus)",
    }.get(profile["goal"], "maintain weight")

    rate_desc = {
        "lose":     "approximately 0.3–0.5 kg per week (safe, sustainable rate)",
        "maintain": "stable weight maintenance",
        "gain":     "approximately 0.25–0.4 kg per week of lean mass",
    }.get(profile["goal"], "stable")

    system = (
        "You are a certified nutritionist and fitness coach. "
        "Provide science-based, realistic, honest dietary guidance. "
        "NEVER exaggerate results or make unrealistic promises. "
        "Safe weight loss is 0.25–0.5 kg/week max. "
        "Always prioritize long-term health over speed. "
        "Be supportive, concise, and practical. "
        "Use clear markdown headings (##) and keep each section brief."
    )

    user_msg = (
        f"Write a personalized nutrition plan for me:\n\n"
        f"- Age: {profile['age']} years | Gender: {profile['gender'].capitalize()}\n"
        f"- Height: {profile['height_cm']} cm | Weight: {profile['weight_kg']} kg\n"
        f"- Activity: {activity_desc}\n"
        f"- Goal: {goal_desc}\n"
        f"- BMR: {profile['bmr']:.0f} kcal | TDEE: {profile['tdee']:.0f} kcal\n"
        f"- Daily target: {profile['target_calories']} kcal\n"
        f"- Expected rate: {rate_desc}\n\n"
        f"Include: (1) brief metabolic assessment, (2) daily macro targets, "
        f"(3) simple eating guidelines, (4) realistic timeline, (5) 3–4 practical tips. "
        f"Start directly with '## ' — no intro sentence."
    )

    return _call_ai([{"role": "user", "content": user_msg}], system, timeout=TIMEOUT_PLAN)


# ── Daily feedback ──────────────────────────────────────────────────────────
def get_daily_feedback(profile: dict, username: str, consumed: int, logs: list) -> str:
    target    = profile["target_calories"]
    remaining = target - consumed
    meal_list = (
        ", ".join(f"{l['food_name']} ({l['calories']} kcal)" for l in logs)
        if logs else "nothing logged yet"
    )

    system = (
        f"You are a friendly, concise nutrition coach. "
        f"Reply with 2–3 sentences of direct, warm feedback. "
        f"No preamble, no sign-off, no meta-commentary — just the feedback."
    )

    if consumed == 0:
        msg = (
            f"{username}'s calorie target today is {target} kcal and they haven't logged anything yet. "
            f"Give a warm, encouraging 2-sentence message to motivate them to start tracking."
        )
    elif remaining > 0:
        msg = (
            f"{username} has consumed {consumed} / {target} kcal today ({remaining} kcal remaining). "
            f"Today's meals: {meal_list}. "
            f"Give a brief, encouraging 2-sentence check-in."
        )
    else:
        over = abs(remaining)
        msg = (
            f"{username} is {over} kcal over their {target} kcal target today. "
            f"Meals: {meal_list}. "
            f"Give honest, kind 2-sentence feedback with one practical tip for the rest of the day."
        )

    return _call_ai([{"role": "user", "content": msg}], system, timeout=TIMEOUT_FEEDBACK)


# ── Chat ────────────────────────────────────────────────────────────────────
def chat_with_ai(profile: dict, username: str, history: list, user_message: str,
                 today_consumed: int, today_logs: list) -> str:
    target   = profile.get("target_calories", 2000)
    goal_desc = {
        "lose": "lose weight", "maintain": "maintain weight", "gain": "gain muscle"
    }.get(profile.get("goal", "maintain"), "maintain weight")
    meal_list = (
        ", ".join(f"{l['food_name']} ({l['calories']} kcal)" for l in today_logs)
        if today_logs else "nothing logged yet"
    )

    system = (
        f"You are a knowledgeable, friendly nutrition coach for {username}.\n"
        f"Goal: {goal_desc} | Target: {target} kcal | "
        f"Today: {today_consumed}/{target} kcal consumed\n"
        f"Today's meals: {meal_list}\n"
        f"BMR: {profile.get('bmr','?')} | TDEE: {profile.get('tdee','?')} | "
        f"Activity: {profile.get('activity_level','moderate')}\n\n"
        f"Reply conversationally and specifically. Give calorie estimates when asked. "
        f"Never diagnose. Keep replies under 150 words unless a detailed plan is requested."
    )

    messages = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
    messages.append({"role": "user", "content": user_message})

    return _call_ai(messages, system, timeout=TIMEOUT_CHAT)
