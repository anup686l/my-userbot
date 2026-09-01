"""
Telegram Userbot with AI (Gemini) auto-reply — deploy-ready version
---------------------------------------------------------------------
⚠️ WARNING: Automating a personal Telegram account (userbot) violates
Telegram's Terms of Service. Excessive/spammy activity can get your
account limited or banned. Keep reply volume low and avoid unsolicited
mass messaging.

This version reads all secrets from ENVIRONMENT VARIABLES (no hardcoded
keys, no interactive login) so it can run headless on Railway/Render/
a VPS. You must generate a session string ONCE beforehand — see
generate_session.py (run that one locally / in Termux where you can
type your phone + OTP).

Required environment variables (set these in Railway's dashboard):
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

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from google import genai

# ========== CONFIG (from environment variables) ==========
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION_STRING = os.environ["TG_SESSION_STRING"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_MODEL = "gemini-flash-latest"

SYSTEM_PROMPT = (
    "You are replying to Telegram messages on behalf of the account owner. "
    "Keep replies short, casual, and natural, like a real person texting. "
    "Do not mention that you are an AI unless directly asked."
)

MIN_REPLY_GAP = 3               # seconds between replies in the same chat
HUMAN_DELAY_RANGE = (1, 4)      # random "typing" delay before replying
MAX_HISTORY_MESSAGES = 10       # keep last N turns per chat
# ============================================================

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
genai_client = genai.Client(api_key=GEMINI_API_KEY)

history = defaultdict(list)          # {chat_id: [{"role": .., "text": ..}]}
last_reply_time = defaultdict(float)


def get_ai_reply(chat_id: int, user_message: str) -> str:
    history[chat_id].append({"role": "user", "text": user_message})
    history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]

    contents = []
    for turn in history[chat_id]:
        role = "user" if turn["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": turn["text"]}]})

    response = genai_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config={"system_instruction": SYSTEM_PROMPT, "max_output_tokens": 300},
    )
    reply_text = response.text
    history[chat_id].append({"role": "model", "text": reply_text})
    return reply_text


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if event.out:
        return

    chat_id = event.chat_id
    is_private = event.is_private
    is_group = event.is_group or event.is_channel

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
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(random.uniform(*HUMAN_DELAY_RANGE))
            reply = get_ai_reply(chat_id, user_text)
        await event.reply(reply)
    except Exception as e:
        print(f"[error] chat_id={chat_id}: {e}")


async def main():
    print("Userbot starting...")
    await client.start()
    print("Logged in. Listening for messages...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
