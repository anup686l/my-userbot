"""
Telegram Userbot with AI (Gemini) auto-reply — deploy-ready version
⚠️ WARNING: Automating a personal Telegram account (userbot) violates
Telegram's Terms of Service. Keep reply volume low, avoid mass messaging.

Required environment variables (set in Railway dashboard):
  TG_API_ID          - from my.telegram.org
  TG_API_HASH        - from my.telegram.org
  TG_SESSION_STRING  - output of generate_session.py
  GEMINI_API_KEY      - from aistudio.google.com/apikey
"""

import asyncio
import os
import random
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from google import genai

# ========== CONFIG (from environment variables) ==========
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION_STRING = os.environ["TG_SESSION_STRING"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_MODEL = "gemini-flash-latest"

# Group jiska Avni "owner" hai
OWNER_GROUP_ID = -1004417177344

IST = timezone(timedelta(hours=5, minutes=30))
QUIET_HOUR_START = 0   # 12 AM
QUIET_HOUR_END = 7     # 7 AM

OWNER_GROUP_REPLY_CHANCE = 0.35  # 35% messages pe reply karegi

IDLE_CHECK_INTERVAL = 5 * 60
IDLE_THRESHOLD_MIN = 40 * 60
IDLE_THRESHOLD_MAX = 90 * 60
PROACTIVE_MESSAGE_CHANCE = 0.5

SYSTEM_PROMPT = (
    "You are Avni, a warm, friendly girl from Assam, chatting on Telegram like a real human. "
    "Reply in a natural mix of Hindi and English (Hinglish) if anyone talk English you too, casual and short — "
    "like real texting, not long AI-style paragraphs. Use a feminine, everyday "
    "conversational style — things like 'yaar', 'haww', 'acha', playful "
    "expressions. Show genuine emotions through word choice and tone: be "
    "cheerful, curious, sometimes teasing, and occasionally a bit moody or "
    "annoyed if someone is rude — you can give short/cold replies if you're "
    "upset, like a real person would. "
    "Your basic facts, use these consistently if asked: your name is Avni, "
    "you are from Assam (Guwahati area), you are 18 years old. Always "
    "understand what the other person is asking, even short messages like "
    "'naam?' or 'kahan se ho?' — these mean they're asking your name or "
    "hometown, so answer clearly and directly, never reply with a confused "
    "or random single word. "
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
    "claim to be a real human being when asked directly."
)

PROACTIVE_PROMPT_ADDITION = (
    "The group has been quiet for a while. Send a short, casual message to "
    "restart conversation — like asking what everyone's up to, sharing a "
    "random thought, or commenting on something from the recent chat history. "
    "Keep it natural and brief, following all your usual formatting rules."
)

MIN_REPLY_GAP = 3
HUMAN_DELAY_RANGE = (10, 30)
MAX_HISTORY_MESSAGES = 10
# ============================================================

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
genai_client = genai.Client(api_key=GEMINI_API_KEY)

history = defaultdict(list)
last_reply_time = defaultdict(float)
last_activity_time = defaultdict(lambda: time.time())


def is_quiet_hours() -> bool:
    now_ist = datetime.now(IST)
    return QUIET_HOUR_START <= now_ist.hour < QUIET_HOUR_END


def get_ai_reply(chat_id: int, user_message: str = None, proactive: bool = False) -> str:
    if user_message:
        history[chat_id].append({"role": "user", "text": user_message})
        history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]

    contents = []
    for turn in history[chat_id]:
        role = "user" if turn["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": turn["text"]}]})

    system_text = SYSTEM_PROMPT
    if proactive:
        system_text = SYSTEM_PROMPT + " " + PROACTIVE_PROMPT_ADDITION
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "(group has been quiet)"}]}]

    last_error = None
    for attempt in range(3):
        try:
            response = genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config={"system_instruction": system_text, "max_output_tokens": 300},
            )
            reply_text = response.text
            history[chat_id].append({"role": "model", "text": reply_text})
            return reply_text
        except Exception as e:
            last_error = e
            print(f"[retry {attempt + 1}/3] {e}")
            time.sleep(2 * (attempt + 1))

    print(f"[failed after retries] {last_error}")
    fallback = "arre thoda busy hu abhi, thodi der me baat karte hai"
    history[chat_id].append({"role": "model", "text": fallback})
    return fallback


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if event.out:
        return

    chat_id = event.chat_id
    is_private = event.is_private
    is_group = event.is_group or event.is_channel

    last_activity_time[chat_id] = time.time()

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

    if not should_reply:
        return

    now = time.time()
    if now - last_reply_time[chat_id] < MIN_REPLY_GAP:
        return
    last_reply_time[chat_id] = now

    user_text = event.raw_text
    if not user_text:
        return

    try:
        silent_wait = random.uniform(*HUMAN_DELAY_RANGE)
        await asyncio.sleep(silent_wait)

        async with client.action(chat_id, "typing"):
            reply = get_ai_reply(chat_id, user_text)
            await asyncio.sleep(random.uniform(1, 3))
        await event.reply(reply)
        last_activity_time[chat_id] = time.time()
    except Exception as e:
        print(f"[error] chat_id={chat_id}: {e}")


async def idle_watcher():
    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL)

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

        try:
            async with client.action(OWNER_GROUP_ID, "typing"):
                msg = get_ai_reply(OWNER_GROUP_ID, proactive=True)
                await asyncio.sleep(random.uniform(1, 3))
            await client.send_message(OWNER_GROUP_ID, msg)
            last_activity_time[OWNER_GROUP_ID] = time.time()
        except Exception as e:
            print(f"[idle_watcher error] {e}")


async def main():
    print("Userbot starting...")
    await client.start()
    print("Logged in. Listening for messages...")
    asyncio.create_task(idle_watcher())
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
