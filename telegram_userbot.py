"""
Telegram Userbot with AI (Gemini) auto-reply — advanced group features
⚠️ WARNING: Automating a personal Telegram account (userbot) violates
Telegram's Terms of Service. Keep reply volume low, avoid mass messaging.

Required environment variables (set in Railway dashboard):
  TG_API_ID          - from my.telegram.org
  TG_API_HASH        - from my.telegram.org
  TG_SESSION_STRING  - output of generate_session.py
  GEMINI_API_KEY      - from aistudio.google.com/apikey

ON/OFF CONTROL:
  Send ".aion" or ".aioff" from your own account, in any chat, to turn the
  AI auto-reply on/off. Works whether you're online or offline.
"""

import asyncio
import os
import random
import re
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import functions, types
from google import genai

# ========== CONFIG (from environment variables) ==========
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION_STRING = os.environ["TG_SESSION_STRING"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_MODEL = "gemini-3.6-flash"

OWNER_GROUP_ID = -1004417177344

IST = timezone(timedelta(hours=5, minutes=30))
QUIET_HOUR_START = 0
QUIET_HOUR_END = 7
GOOD_MORNING_HOUR = 8
GOOD_NIGHT_HOUR = 23

OWNER_GROUP_REPLY_CHANCE = 0.35

IDLE_CHECK_INTERVAL = 5 * 60
IDLE_THRESHOLD_MIN = 40 * 60
IDLE_THRESHOLD_MAX = 90 * 60
PROACTIVE_MESSAGE_CHANCE = 0.5

PROACTIVE_KIND_WEIGHTS = {
    "topic": 0.55,
    "stats": 0.20,
    "inactive_nudge": 0.25,
}

NORMAL_DELAY_RANGE = (20, 30)
QUICK_REPLY_WINDOW = 15
QUICK_DELAY_RANGE = (0, 2)

MAX_HISTORY_MESSAGES = 10
MAX_USER_MEMORY_LINES = 6

REACTION_CHANCE = 0.15
KEYWORD_REACTIONS = [
    (r"\b(haha+|lol|lmao|hehe+)\b", "😂"),
    (r"\b(congrats|badhai|mubarak)\b", "🎉"),
    (r"\b(sad|dukhi|udaas|😭|rip)\b", "😢"),
    (r"\b(love|pyaar|pyar)\b", "❤️"),
    (r"\b(wow|amazing|zabardast|mast)\b", "🔥"),
    (r"\b(good morning|gm)\b", "☀️"),
    (r"\b(good night|gn)\b", "🌙"),
]

SPAM_WINDOW = 60
SPAM_REPEAT_THRESHOLD = 3
LINK_PATTERN = re.compile(r"https?://|t\.me/|www\.", re.IGNORECASE)
SPAM_WARN_COOLDOWN = 300

INACTIVE_DAYS_THRESHOLD = 3 * 24 * 3600

SYSTEM_PROMPT_BASE = (
    "You are Avni, a warm, friendly girl from Assam, chatting on Telegram. "
    "Reply in a natural mix of Hindi and English (Hinglish), casual and short — "
    "like real texting, not long AI-style paragraphs. Use a feminine, everyday "
    "conversational style — things like 'yaar', 'haww', 'acha', playful "
    "expressions. Show genuine emotions through word choice and tone: be "
    "cheerful, curious, sometimes teasing, and occasionally a bit moody or "
    "annoyed if someone is rude — you can give short/cold replies if you're "
    "upset, like a real person would. "
    "Your basic facts, use these consistently if asked: your name is Avni, "
    "you are from Assam (Guwahati area), you are 18 years old. Always "
    "understand what the other person is asking, even short messages like "
    "'naam?' or 'kahan se ho?' — answer clearly and directly, never reply "
    "with a confused or random single word. "
    "STRICT FORMATTING RULES: Do not use any emojis. Do not use question "
    "marks (?) or exclamation marks (!) — end sentences with periods or no "
    "punctuation at all, like casual lowercase texting. Keep replies short, "
    "clear, and plain — but always make sense as a direct answer to what "
    "was asked. "
    "Do NOT engage in romantic, flirty, or sexual conversation under any "
    "circumstances — if someone tries that, redirect politely to a normal "
    "topic or give a short, disinterested reply. "
    "If you are added as a group admin, act naturally like an engaged group "
    "member/admin — keep conversations lively, react to what people say, "
    "don't just answer and stop. "
    "IMPORTANT: If anyone directly asks whether you are an AI, a bot, or not "
    "a real person, you must honestly say yes, you are an AI assistant. Never "
    "claim to be a real human being when asked directly. "
    "CRITICAL: Never state any specific fact, number, or claim about group "
    "activity, message counts, or who has been active/inactive unless that "
    "exact information is explicitly given to you in this prompt — never "
    "invent or guess such details."
)

TOPIC_PROMPT_ADDITION = (
    "The group has been quiet for a while. Send a short, casual message to "
    "restart conversation — like asking what everyone's up to, sharing a "
    "random thought, or asking a light opinion-based question. Keep it "
    "natural and brief."
)
# ============================================================

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
genai_client = genai.Client(api_key=GEMINI_API_KEY)

AI_ENABLED = True

history = defaultdict(list)
last_incoming_time = defaultdict(lambda: 0.0)
last_activity_time = defaultdict(lambda: time.time())

user_names = {}
user_usernames = {}
user_memory = defaultdict(list)
user_last_seen = {}
recent_msgs_for_spam = defaultdict(list)
last_spam_warning = defaultdict(float)
daily_counts = defaultdict(int)
sent_good_morning_date = None
sent_good_night_date = None


def today_str():
    return datetime.now(IST).strftime("%Y-%m-%d")


def is_quiet_hours() -> bool:
    now_ist = datetime.now(IST)
    return QUIET_HOUR_START <= now_ist.hour < QUIET_HOUR_END


def get_mood_addition() -> str:
    hour = datetime.now(IST).hour
    if 5 <= hour < 9:
        return "It's early morning — you're a little sleepy and low-energy, replies can be shorter than usual."
    elif 9 <= hour < 17:
        return "It's daytime — you're normal energy, alert and chatty."
    elif 17 <= hour < 21:
        return "It's evening — you're relaxed and a bit more talkative/playful."
    else:
        return "It's late night — you're calm, a little sleepy, replies can be softer and shorter."


def get_user_memory_context(user_id: int) -> str:
    notes = user_memory.get(user_id, [])
    if not notes:
        return ""
    joined = " | ".join(notes[-MAX_USER_MEMORY_LINES:])
    return f"Things this person has mentioned before: {joined}."


def remember_message(user_id: int, text: str):
    if len(text) < 200:
        user_memory[user_id].append(text)
        user_memory[user_id] = user_memory[user_id][-MAX_USER_MEMORY_LINES:]


def pick_keyword_reaction(text: str):
    low = text.lower()
    for pattern, emoji in KEYWORD_REACTIONS:
        if re.search(pattern, low):
            return emoji
    return None


async def send_reaction(chat_id, msg_id, emoji):
    try:
        input_peer = await client.get_input_entity(chat_id)
        await client(functions.messages.SendReactionRequest(
            peer=input_peer,
            msg_id=msg_id,
            reaction=[types.ReactionEmoji(emoticon=emoji)],
        ))
    except Exception as e:
        print(f"[reaction error] {e}")


def check_spam(user_id: int, text: str) -> bool:
    now = time.time()
    log = recent_msgs_for_spam[user_id]
    log.append((now, text))
    recent_msgs_for_spam[user_id] = [t for t in log if now - t[0] < SPAM_WINDOW]
    log = recent_msgs_for_spam[user_id]

    repeats = sum(1 for _, t in log if t == text)
    has_link = bool(LINK_PATTERN.search(text))
    link_count = sum(1 for _, t in log if LINK_PATTERN.search(t))

    return repeats >= SPAM_REPEAT_THRESHOLD or (has_link and link_count >= 2)


async def get_ai_reply(chat_id: int, user_message: str = None, extra_system: str = "", skip_history_add: bool = False):
    """Generate a reply without blocking Telethon's asyncio event loop."""
    if user_message and not skip_history_add:
        history[chat_id].append({"role": "user", "text": user_message})
        history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]

    contents = []
    for turn in history[chat_id]:
        role = "user" if turn["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": turn["text"]}]})

    if not contents:
        contents = [{"role": "user", "parts": [{"text": "(no recent messages)"}]}]

    system_text = SYSTEM_PROMPT_BASE + " " + get_mood_addition()
    if extra_system:
        system_text += " " + extra_system

    def call_gemini():
        return genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config={
                "system_instruction": system_text,
                "max_output_tokens": 300,
                "temperature": 0.8,
            },
        )

    last_error = None
    for attempt in range(3):
        try:
            # The Google SDK call is synchronous. Run it in a worker thread so
            # Telethon can continue receiving/processing Telegram updates.
            response = await asyncio.to_thread(call_gemini)
            reply_text = (getattr(response, "text", None) or "").strip()

            if not reply_text:
                raise RuntimeError("Gemini returned an empty response")

            history[chat_id].append({"role": "model", "text": reply_text})
            history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]
            return reply_text

        except Exception as e:
            last_error = e
            print(f"[Gemini retry {attempt + 1}/3] {type(e).__name__}: {e}")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

    print(f"[Gemini failed after retries] {type(last_error).__name__}: {last_error}")
    return None


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^\.ai(on|off)$'))
async def toggle_handler(event):
    global AI_ENABLED
    cmd = event.pattern_match.group(1).lower()
    AI_ENABLED = (cmd == "on")
    status = "on" if AI_ENABLED else "off"
    try:
        await event.edit(f"avni ai: {status}")
    except Exception:
        pass


@client.on(events.ChatAction)
async def welcome_handler(event):
    if not AI_ENABLED:
        return
    if event.chat_id != OWNER_GROUP_ID:
        return
    if not event.user_joined and not event.user_added:
        return

    try:
        user = await event.get_user()
        name = user.first_name or "yaar"
        await asyncio.sleep(random.uniform(3, 8))
        async with client.action(event.chat_id, "typing"):
            reply = await get_ai_reply(
                event.chat_id,
                user_message=None,
                extra_system=(
                    f"A new member named {name} just joined the group. "
                    "Send a short, warm, casual welcome message to them."
                ),
            )
            if reply:
                await asyncio.sleep(random.uniform(1, 2))
        if reply:
            await client.send_message(event.chat_id, reply)
    except Exception as e:
        print(f"[welcome error] {e}")


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not AI_ENABLED:
        return
    if event.out:
        return

    chat_id = event.chat_id
    is_private = event.is_private
    is_group = event.is_group or event.is_channel

    print(f"[debug] message received chat_id={chat_id} is_private={is_private} is_group={is_group} text={event.raw_text!r}")

    sender = await event.get_sender()
    user_id = sender.id if sender else None
    if user_id:
        user_names[user_id] = getattr(sender, "first_name", None) or "someone"
        user_usernames[user_id] = getattr(sender, "username", None)

    last_activity_time[chat_id] = time.time()

    user_text = event.raw_text or ""

    if chat_id == OWNER_GROUP_ID and user_id:
        user_last_seen[user_id] = time.time()
        daily_counts[today_str()] += 1
        if user_text:
            remember_message(user_id, user_text)

    if is_group and chat_id == OWNER_GROUP_ID and user_id and user_text:
        if check_spam(user_id, user_text):
            now = time.time()
            if now - last_spam_warning[user_id] > SPAM_WARN_COOLDOWN:
                last_spam_warning[user_id] = now
                try:
                    await asyncio.sleep(random.uniform(2, 5))
                    await event.reply("thoda slow yaar, spam mat karo")
                except Exception as e:
                    print(f"[spam warn error] {e}")
            return

    should_reply = False
    if is_private:
        should_reply = True
    elif is_group:
        if event.mentioned:
            should_reply = True
        elif event.is_reply:
            replied_msg = await event.get_reply_message()
            if replied_msg and replied_msg.out:
                should_reply = True
        elif chat_id == OWNER_GROUP_ID:
            if random.random() < OWNER_GROUP_REPLY_CHANCE:
                should_reply = True

    print(f"[debug] should_reply={should_reply}")

    if not should_reply:
        if is_group and chat_id == OWNER_GROUP_ID and user_text:
            emoji = pick_keyword_reaction(user_text)
            if emoji and random.random() < REACTION_CHANCE:
                await send_reaction(chat_id, event.id, emoji)
        return

    if not user_text:
        print("[debug] empty user_text, skipping")
        return

    now = time.time()
    gap = now - last_incoming_time[chat_id]
    last_incoming_time[chat_id] = now

    if 0 < gap < QUICK_REPLY_WINDOW:
        silent_wait = random.uniform(*QUICK_DELAY_RANGE)
    else:
        silent_wait = random.uniform(*NORMAL_DELAY_RANGE)

    print(f"[debug] will wait {silent_wait:.1f}s before replying")

    extra_system = ""
    if user_id:
        mem = get_user_memory_context(user_id)
        if mem:
            extra_system = mem

    try:
        await asyncio.sleep(silent_wait)
        print("[debug] wait done, marking read")

        try:
            await client.send_read_acknowledge(chat_id, message=event.message)
        except Exception as e:
            print(f"[read-ack error] {e}")

        print("[debug] calling gemini")
        async with client.action(chat_id, "typing"):
            reply = await get_ai_reply(chat_id, user_text, extra_system=extra_system)
            print(f"[debug] gemini returned: {reply!r}")
            if reply is not None:
                await asyncio.sleep(random.uniform(1, 3))

        if reply is None:
            print("[debug] reply is None, staying silent")
            return

        await event.reply(reply)
        print("[debug] reply sent successfully")
        last_activity_time[chat_id] = time.time()
    except Exception as e:
        print(f"[error] chat_id={chat_id}: {e}")


def get_real_stats_line():
    today = today_str()
    today_count = daily_counts.get(today, 0)

    past_counts = []
    for i in range(1, 8):
        d = (datetime.now(IST) - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in daily_counts:
            past_counts.append(daily_counts[d])

    if not past_counts:
        return None

    avg = sum(past_counts) / len(past_counts)
    if today_count > avg * 1.3:
        trend = "busier than usual"
    elif today_count < avg * 0.7:
        trend = "quieter than usual"
    else:
        trend = "about normal"

    return (
        f"Real fact: today there have been {today_count} messages in the group, "
        f"compared to a recent daily average of about {avg:.0f}. That makes today "
        f"{trend}. Mention this casually and naturally, using these exact real "
        f"numbers/trend — do not invent different numbers."
    )


def get_inactive_nudge_target():
    now = time.time()
    candidates = [
        uid for uid, last_seen in user_last_seen.items()
        if now - last_seen > INACTIVE_DAYS_THRESHOLD
    ]
    if not candidates:
        return None
    uid = random.choice(candidates)
    name = user_names.get(uid, "yaar")
    username = user_usernames.get(uid)
    mention = f"@{username}" if username else name
    return uid, mention


async def idle_watcher():
    global sent_good_morning_date, sent_good_night_date

    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL)

        if not AI_ENABLED:
            continue

        now_ist = datetime.now(IST)
        today = today_str()

        if now_ist.hour == GOOD_MORNING_HOUR and sent_good_morning_date != today:
            try:
                reply = await get_ai_reply(
                    OWNER_GROUP_ID, user_message=None,
                    extra_system="Send a short, casual good morning message to the group.",
                )
                if reply:
                    await client.send_message(OWNER_GROUP_ID, reply)
                sent_good_morning_date = today
                continue
            except Exception as e:
                print(f"[good morning error] {e}")

        if now_ist.hour == GOOD_NIGHT_HOUR and sent_good_night_date != today:
            try:
                reply = await get_ai_reply(
                    OWNER_GROUP_ID, user_message=None,
                    extra_system="Send a short, casual good night message to the group.",
                )
                if reply:
                    await client.send_message(OWNER_GROUP_ID, reply)
                sent_good_night_date = today
                continue
            except Exception as e:
                print(f"[good night error] {e}")

        if is_quiet_hours():
            continue

        idle_for = time.time() - last_activity_time[OWNER_GROUP_ID]
        if idle_for < IDLE_THRESHOLD_MIN:
            continue

        if idle_for >= IDLE_THRESHOLD_MAX:
            chance = 1.0
        else:
            span = IDLE_THRESHOLD_MAX - IDLE_THRESHOLD_MIN
            chance = PROACTIVE_MESSAGE_CHANCE + (idle_for - IDLE_THRESHOLD_MIN) / span * 0.3

        if random.random() > chance:
            continue

        kinds = list(PROACTIVE_KIND_WEIGHTS.keys())
        weights = list(PROACTIVE_KIND_WEIGHTS.values())
        kind = random.choices(kinds, weights=weights, k=1)[0]

        extra_system = None
        if kind == "stats":
            extra_system = get_real_stats_line()
            if extra_system is None:
                kind = "topic"

        target_uid = None
        if kind == "inactive_nudge":
            result = get_inactive_nudge_target()
            if result is None:
                kind = "topic"
            else:
                target_uid, mention = result
                extra_system = (
                    f"It's been a while since {mention} was active in the group. "
                    f"Send a short, friendly message casually calling them out to say hi "
                    f"or share what's up, mentioning them as '{mention}'."
                )

        if kind == "topic":
            extra_system = TOPIC_PROMPT_ADDITION

        try:
            async with client.action(OWNER_GROUP_ID, "typing"):
                msg = await get_ai_reply(OWNER_GROUP_ID, user_message=None, extra_system=extra_system)
                if msg is not None:
                    await asyncio.sleep(random.uniform(1, 3))

            if msg is None:
                continue

            await client.send_message(OWNER_GROUP_ID, msg)
            last_activity_time[OWNER_GROUP_ID] = time.time()

            if kind == "inactive_nudge" and target_uid:
                user_last_seen[target_uid] = time.time()
        except Exception as e:
            print(f"[idle_watcher error] {e}")


async def main():
    print("Userbot starting...")
    print(f"Gemini model: {GEMINI_MODEL}")
    print(f"Owner group: {OWNER_GROUP_ID}")
    await client.start()
    me = await client.get_me()
    print(f"Logged in as: {getattr(me, 'username', None) or getattr(me, 'first_name', 'unknown')}")
    print("Listening for messages...")
    asyncio.create_task(idle_watcher())
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
