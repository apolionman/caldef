import re
import requests

AI_ENDPOINT = "http://192.168.70.48:8000/v1/chat/completions"
AI_MODEL = "nvidia/Nemotron-Cascade-2-30B-A3B"

# Per-call timeouts (seconds).  Plan generation is the longest prompt.
TIMEOUT_CHAT     = 120
TIMEOUT_FEEDBACK = 120
TIMEOUT_PLAN     = 300

# Phrases that indicate the model leaked its chain-of-thought reasoning
_THINKING_PREFIXES = (
    "we need to", "i need to", "the user ", "user wants", "user is asking",
    "let me think", "thinking:", "okay so", "alright,", "alright so",
    "ok, ", "ok so", "so the user", "to respond", "we should respond",
    "i should respond", "based on the context", "the context shows",
    "looking at the", "step 1", "first, i", "let's see", "i'll ",
    "we'll ", "provide ", "keep ", "suggest ",
)


def _strip_thinking(text: str) -> str:
    """Remove chain-of-thought / planning text leaked by reasoning models."""
    # Strip explicit <think>...</think> blocks (DeepSeek / Nemotron style)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # If the first paragraph looks like internal planning, drop it.
    # The model sometimes prepends its reasoning before the actual answer.
    blocks = re.split(r"\n{2,}", text)
    if len(blocks) >= 2:
        first_lower = blocks[0].strip().lower()
        if first_lower.startswith(_THINKING_PREFIXES):
            text = "\n\n".join(blocks[1:]).strip()

    return text


def _call_ai(messages: list, system_prompt: str = None, timeout: int = TIMEOUT_CHAT) -> str:
    all_messages = []
    if system_prompt:
        all_messages.append({"role": "system", "content": system_prompt})
    all_messages.extend(messages)

    try:
        resp = requests.post(
            AI_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json={"model": AI_MODEL, "messages": all_messages, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        return _strip_thinking(raw)
    except requests.exceptions.ConnectionError:
        return "AI service is currently unreachable. Please check your network connection."
    except requests.exceptions.Timeout:
        return "AI response timed out. Please try again."
    except Exception as e:
        return f"AI service error. Please try again later."


def generate_plan(profile: dict) -> str:
    activity_desc = {
        "low": "sedentary (little to no exercise)",
        "moderate": "moderately active (light exercise 3-5 days/week)",
        "high": "very active (hard exercise 6-7 days/week)",
    }.get(profile["activity_level"], "moderately active")

    goal_desc = {
        "lose": "lose weight (calorie deficit)",
        "maintain": "maintain current weight",
        "gain": "gain weight/muscle (calorie surplus)",
    }.get(profile["goal"], "maintain weight")

    rate_desc = {
        "lose": "approximately 0.3–0.5 kg per week (safe, sustainable rate)",
        "maintain": "stable weight maintenance",
        "gain": "approximately 0.25–0.4 kg per week of lean mass",
    }.get(profile["goal"], "stable")

    system = (
        "You are a certified nutritionist and fitness coach. Provide science-based, realistic, "
        "honest dietary guidance. NEVER exaggerate results or make unrealistic promises. "
        "Safe weight loss is 0.25–0.5 kg/week max. Always prioritize long-term health over speed. "
        "Be supportive, concise, and practical."
    )

    user_msg = (
        f"Create a personalized nutrition plan for me based on my profile:\n\n"
        f"- Age: {profile['age']} years\n"
        f"- Gender: {profile['gender'].capitalize()}\n"
        f"- Height: {profile['height_cm']} cm\n"
        f"- Weight: {profile['weight_kg']} kg\n"
        f"- Activity Level: {activity_desc}\n"
        f"- Goal: {goal_desc}\n\n"
        f"Calculated Metabolic Data:\n"
        f"- BMR (Basal Metabolic Rate): {profile['bmr']:.0f} kcal/day\n"
        f"- TDEE (Total Daily Energy Expenditure): {profile['tdee']:.0f} kcal/day\n"
        f"- Recommended Daily Calories: {profile['target_calories']} kcal/day\n"
        f"- Expected progress rate: {rate_desc}\n\n"
        f"Please provide:\n"
        f"1. A brief honest assessment of my metabolic baseline\n"
        f"2. Daily macronutrient targets (protein, carbs, fat in grams)\n"
        f"3. Simple weekly eating guidelines (not a rigid meal plan)\n"
        f"4. Realistic timeline expectations for my goal\n"
        f"5. 3-4 practical, actionable tips for my situation\n\n"
        f"Keep it honest, encouraging, and achievable. Use clear sections with short headings."
    )

    return _call_ai([{"role": "user", "content": user_msg}], system, timeout=TIMEOUT_PLAN)


def get_daily_feedback(profile: dict, username: str, consumed: int, logs: list) -> str:
    target = profile["target_calories"]
    remaining = target - consumed
    meal_list = ", ".join([f"{log['food_name']} ({log['calories']} kcal)" for log in logs]) if logs else "nothing logged yet"

    system = (
        f"You are a friendly, honest nutrition coach monitoring {username}'s daily calorie intake. "
        f"Be supportive and realistic. Give brief, specific feedback (2-3 sentences max). "
        f"Don't be preachy. If they're doing well, acknowledge it warmly. "
        f"If they're over their target, be honest but kind and give one practical tip."
    )

    if consumed == 0:
        msg = (
            f"It's a new day for {username}! Their target is {target} kcal today. "
            f"Give them a brief, warm motivational message to start tracking."
        )
    elif remaining > 0:
        msg = (
            f"{username} has consumed {consumed} kcal today (target: {target} kcal). "
            f"Remaining: {remaining} kcal. "
            f"Today's meals: {meal_list}. "
            f"Give a brief encouraging check-in about their progress."
        )
    else:
        over = abs(remaining)
        msg = (
            f"{username} has consumed {consumed} kcal today (target: {target} kcal), "
            f"which is {over} kcal over their target. "
            f"Today's meals: {meal_list}. "
            f"Give honest, kind feedback and one practical suggestion for the rest of the day."
        )

    return _call_ai([{"role": "user", "content": msg}], system, timeout=TIMEOUT_FEEDBACK)


def chat_with_ai(profile: dict, username: str, history: list, user_message: str,
                 today_consumed: int, today_logs: list) -> str:
    target = profile.get("target_calories", 2000)
    goal_desc = {"lose": "lose weight", "maintain": "maintain weight", "gain": "gain muscle"}.get(
        profile.get("goal", "maintain"), "maintain weight"
    )
    meal_list = (
        ", ".join([f"{log['food_name']} ({log['calories']} kcal)" for log in today_logs])
        if today_logs
        else "nothing logged yet"
    )

    system = (
        f"You are a knowledgeable, friendly nutrition coach helping {username} achieve their health goals.\n\n"
        f"User Profile:\n"
        f"- Goal: {goal_desc}\n"
        f"- Daily calorie target: {target} kcal\n"
        f"- BMR: {profile.get('bmr', 'N/A')} kcal | TDEE: {profile.get('tdee', 'N/A')} kcal\n"
        f"- Activity: {profile.get('activity_level', 'moderate')}\n\n"
        f"Today's Progress:\n"
        f"- Consumed: {today_consumed} / {target} kcal\n"
        f"- Today's meals: {meal_list}\n\n"
        f"Guidelines: Be conversational, specific, and honest. Answer nutrition and fitness questions helpfully. "
        f"Provide calorie estimates for foods when asked. Never give medical diagnoses. "
        f"Keep responses concise (under 150 words unless a detailed plan is requested)."
    )

    messages = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
    messages.append({"role": "user", "content": user_message})

    return _call_ai(messages, system, timeout=TIMEOUT_CHAT)
