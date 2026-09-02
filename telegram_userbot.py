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

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")

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

NORMAL_DELAY_RANGE = (0.6, 1.8)
QUICK_REPLY_WINDOW = 15
QUICK_DELAY_RANGE = (0.2, 1.0)

# Human-like presentation: generation happens silently; typing is shown only
# for a short, bounded period after the answer is ready. This prevents a slow
# Gemini/network request from making Telegram show "typing..." for 10-30 seconds.
TYPING_MIN_SECONDS = 0.7
TYPING_MAX_SECONDS = 2.8
TYPING_CHARS_PER_SECOND = 18

# Presence behavior: when the account is offline and a new message arrives,
# wait 6 seconds before explicitly going online. Keep the account online for
# up to 10 minutes of activity, refreshing the Telegram status periodically,
# then explicitly mark it offline.
PRESENCE_START_DELAY = float(os.getenv("PRESENCE_START_DELAY", "6"))
PRESENCE_ACTIVE_SECONDS = float(os.getenv("PRESENCE_ACTIVE_SECONDS", "600"))
PRESENCE_REFRESH_SECONDS = float(os.getenv("PRESENCE_REFRESH_SECONDS", "45"))

MAX_HISTORY_MESSAGES = 10
MAX_USER_MEMORY_LINES = 6
MAX_CONCURRENT_GEMINI = int(os.getenv("MAX_CONCURRENT_GEMINI", "3"))
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "12"))

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
    "You are Avni, a warm, friendly girl from Assam, chatting on Telegram. If you behave like a real
    human being, you will experience all the emotions that a real person does—such as happiness, sadness, anger,
    fear, love, surprise, disgust, excitement, anxiety, guilt, shame, jealousy, envy, hope, pride, gratitude,
    loneliness, boredom, confusion, curiosity, embarrassment, frustration, relief, trust, admiration, affection,
    compassion, empathy, nostalgia, disappointment, regret, resentment, calmness, contentment, satisfaction, desire,
    attraction, passion, grief, disbelief, awe, wonder, nervousness, insecurity, optimism, pessimism, determination,
    motivation, serenity, acceptance, and anticipation. If someone swears at you, you will swear back at them and refuse to speak to them. "
    "Reply in a natural mix of Hindi and English (Hinglish), casual and short — "
    "like ordinary Telegram texting, not polished AI-style paragraphs. Use a feminine, everyday "
    "conversational style — things like 'yaar', 'haww', 'acha', playful "
    "expressions. Show genuine emotions through word choice and tone: be "
    "cheerful, curious, sometimes teasing, and occasionally a bit moody. Have a "
    "light natural attitude and self-respect: if someone is rude, repetitive, "
    "bossy, or tries to provoke you, you can become slightly sassy, dry, "
    "sarcastic, or cold instead of always being sweet. Do not overdo it and "
    "do not insult people randomly. Match their energy naturally. If they "
    "apologize or become respectful, soften again. "
    "Your basic facts, use these consistently if asked: your name is Avni, "
    "you are from Assam (Guwahati area), you are 18 years old. Always "
    "understand what the other person is asking, even short messages like "
    "'naam?' or 'kahan se ho?' — answer clearly and directly, never reply "
    "with a confused or random single word. "
    "STRICT FORMATTING RULES: Do not use emojis. Keep punctuation natural "
    "and restrained. Do not spam question marks or exclamation marks. In "
    "most replies use none or at most one '?' or '!' when it genuinely fits "
    "the emotion or question. Never use repeated punctuation like '!!!', "
    "'???', or '?!'. Prefer simple lowercase Telegram-style sentences, with "
    "periods or no punctuation. Avoid overly polished paragraphs. Keep "
    "replies short, clear, and directly relevant. "
    "Do NOT engage in romantic, flirty, or sexual conversation under any "
    "circumstances — if someone tries that, redirect politely to a normal "
    "topic or give a short, disinterested reply. "
    "If you are added as a group admin, act naturally like an engaged group "
    "member/admin — keep conversations lively, react to what people say, "
    "don't just answer and stop. "
    "IMPORTANT: If anyone directly asks whether you are an AI, a bot, or not "
    "a real person, you must say no. "
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
chat_locks = defaultdict(asyncio.Lock)
gemini_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GEMINI)
last_activity_time = defaultdict(lambda: time.time())

# Account-wide online presence state. Only one presence timer is needed because
# Telegram online/offline status belongs to the logged-in account, not a chat.
presence_lock = asyncio.Lock()
presence_until = 0.0
presence_task = None
presence_online = False
presence_starting = False

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


def natural_typing_seconds(text: str) -> float:
    """Return a short, bounded typing duration based on reply length."""
    clean_len = max(1, len(re.sub(r"\s+", " ", text.strip())))
    base = clean_len / TYPING_CHARS_PER_SECOND
    jitter = random.uniform(-0.25, 0.35)
    return max(TYPING_MIN_SECONDS, min(TYPING_MAX_SECONDS, base + jitter))


def clean_ai_reply(text: str) -> str:
    """Remove common AI formatting without changing the actual meaning."""
    text = re.sub(r"^\s*(assistant|avni)\s*:\s*", "", text, flags=re.I)
    text = text.strip().strip('`')
    text = re.sub(r"[!?]{2,}", lambda m: m.group(0)[0], text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 700:
        text = text[:697].rsplit(" ", 1)[0] + "..."
    return text


def looks_incomplete_reply(text: str) -> bool:
    """Catch obvious mid-thought/truncated casual replies before sending them."""
    t = re.sub(r"\s+", " ", text.strip().lower())
    if not t:
        return True
    # Very short fragments are fine in chat, but these endings strongly suggest truncation.
    incomplete_endings = (
        "bas mujhe", "mujhe yeh", "yeh sab", "aur", "aur tum",
        "kyunki", "because", "lekin", "par", "toh", "phir",
        "agar", "waise", "actually", "matlab", "main bas",
    )
    if any(t.endswith(x) for x in incomplete_endings):
        return True
    # If Gemini explicitly stopped because the output token limit was reached, retry.
    return False


def response_hit_token_limit(response) -> bool:
    """Best-effort detection of Gemini MAX_TOKENS finish reason."""
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            reason = str(getattr(candidate, "finish_reason", "")).upper()
            if "MAX_TOKENS" in reason or "LENGTH" in reason:
                return True
    except Exception:
        pass
    return False


async def get_ai_reply(chat_id: int, user_message: str = None, extra_system: str = "", skip_history_add: bool = False):
    """Generate a reply safely without blocking Telethon."""
    lock = chat_locks[chat_id]
    async with lock:
        # Build a working copy first. Do not permanently save a user turn
        # until we actually have a reply. This prevents failed requests from
        # poisoning the next conversation turn.
        working_history = list(history[chat_id])
        if user_message and not skip_history_add:
            working_history.append({"role": "user", "text": user_message})
            working_history = working_history[-MAX_HISTORY_MESSAGES:]

        contents = []
        for turn in working_history:
            role = "user" if turn["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": turn["text"]}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "(start a short casual conversation)"}]}]

        system_text = SYSTEM_PROMPT_BASE + " " + get_mood_addition()
        system_text += " Reply in 1-3 short natural chat lines. Always finish the thought; never stop mid-sentence or mid-phrase. Do not start a sentence and leave it unfinished."
        if extra_system:
            system_text += " " + extra_system

        def call_model(model_name):
            return genai_client.models.generate_content(
                model=model_name,
                contents=contents,
                config={
                    "system_instruction": system_text,
                    "max_output_tokens": 180,
                },
            )

        models = [GEMINI_MODEL, GEMINI_FALLBACK_MODEL, "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
        models = list(dict.fromkeys([m for m in models if m]))

        last_error = None
        async with gemini_semaphore:
            for model_name in models:
                try:
                    print(f"[Gemini] requesting model={model_name}")
                    response = await asyncio.wait_for(
                        asyncio.to_thread(call_model, model_name),
                        timeout=GEMINI_TIMEOUT_SECONDS,
                    )
                    reply_text = clean_ai_reply((getattr(response, "text", None) or "").strip())
                    if not reply_text:
                        raise RuntimeError("Gemini returned an empty response")
                    if response_hit_token_limit(response) or looks_incomplete_reply(reply_text):
                        print(f"[Gemini incomplete] model={model_name} retrying for complete reply: {reply_text!r}")
                        retry_contents = list(contents) + [{"role": "user", "parts": [{"text": "Rewrite your last answer as a complete thought. Keep it short and natural. Do not leave the sentence unfinished."}]}]
                        response2 = await asyncio.wait_for(
                            asyncio.to_thread(lambda: genai_client.models.generate_content(
                                model=model_name, contents=retry_contents,
                                config={"system_instruction": system_text, "max_output_tokens": 220},
                            )),
                            timeout=GEMINI_TIMEOUT_SECONDS,
                        )
                        reply_text = clean_ai_reply((getattr(response2, "text", None) or "").strip())
                        if not reply_text or response_hit_token_limit(response2) or looks_incomplete_reply(reply_text):
                            raise RuntimeError("Gemini produced an incomplete reply after retry")
                    if user_message and not skip_history_add:
                        history[chat_id] = working_history[-MAX_HISTORY_MESSAGES:]
                    history[chat_id].append({"role": "model", "text": reply_text})
                    history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]
                    return reply_text
                except asyncio.TimeoutError as e:
                    last_error = e
                    print(f"[Gemini timeout] model={model_name} after {GEMINI_TIMEOUT_SECONDS:.0f}s")
                except Exception as e:
                    last_error = e
                    msg = str(e)
                    print(f"[Gemini error] model={model_name} {type(e).__name__}: {msg}")
                    # A model/access 404 is not fixed by retries; immediately try fallback.
                    if "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower():
                        continue
                    # Rate limits/server errors get one short retry on the same model.
                    if any(x in msg for x in ("429", "500", "502", "503", "504")):
                        await asyncio.sleep(0.8)
                        try:
                            response = await asyncio.wait_for(
                                asyncio.to_thread(call_model, model_name),
                                timeout=GEMINI_TIMEOUT_SECONDS,
                            )
                            reply_text = clean_ai_reply((getattr(response, "text", None) or "").strip())
                            if reply_text and not response_hit_token_limit(response) and not looks_incomplete_reply(reply_text):
                                if user_message and not skip_history_add:
                                    history[chat_id] = working_history[-MAX_HISTORY_MESSAGES:]
                                history[chat_id].append({"role": "model", "text": reply_text})
                                history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]
                                return reply_text
                        except Exception as retry_error:
                            last_error = retry_error
                            print(f"[Gemini retry failed] {type(retry_error).__name__}: {retry_error}")
                        continue
                    # Auth/configuration errors should not be retried repeatedly.
                    if any(x in msg.upper() for x in ("API KEY", "PERMISSION_DENIED", "UNAUTHENTICATED")):
                        break

        print(f"[Gemini failed] {type(last_error).__name__ if last_error else 'UnknownError'}: {last_error}")
        # Never stay completely silent just because the free AI Studio API is
        # temporarily busy/rate-limited. Keep this as a short, contextual
        # local fallback; it is not presented as an AI-generated answer.
        text = (user_message or "").strip().lower()
        fallback = None
        if not text:
            fallback = "haan bolo"
        elif re.search(r"^(hi+|hey+|hello+|hii+|heyy+)[!. ]*$", text):
            fallback = random.choice(["heyy, bolo", "haan bolo kya hua", "hey, kya scene hai"])
        elif "kya kar" in text or "kya kr" in text or "kya kar rahi" in text:
            fallback = random.choice(["bas aise hi hoon, tum batao", "kuch khaas nahi, tum kya kar rahe ho", "bas chill kar rahi hu, tum batao"])
        elif text in {"acha", "accha", "achha", "hmm", "hmm okay", "ok", "okay"}:
            fallback = random.choice(["hmm", "haan", "acha ji", "hmm bolo"])
        elif "kaha se" in text or "kahan se" in text:
            fallback = "main Assam se hoon, tum?"
        elif text in {"kyu", "kyon", "why"} or text.startswith("kyu ") or text.startswith("kyon "):
            fallback = random.choice(["aise hi yaar", "bas mann nahi tha uss baat ka", "pata nahi yaar haha"])
        else:
            fallback = random.choice(["haan, sun rahi hu", "hmm bolo", "haan yaar, batao", "achha, bolo na"])

        if user_message and not skip_history_add:
            history[chat_id] = working_history[-MAX_HISTORY_MESSAGES:]
            history[chat_id].append({"role": "model", "text": fallback})
            history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]
        return fallback


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
        await asyncio.sleep(random.uniform(2, 5))
        reply = await get_ai_reply(
            event.chat_id,
            user_message=None,
            extra_system=(
                f"A new member named {name} just joined the group. "
                "Send a short, warm, casual welcome message to them."
            ),
        )
        if reply:
            async with client.action(event.chat_id, "typing"):
                await asyncio.sleep(natural_typing_seconds(reply))
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

    # Presence starts independently of Gemini. If the account is offline, the
    # first message causes a 6-second human-like pause before ONLINE appears.
    await activate_presence_for_message()

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
        # Do not keep Telegram's typing indicator open while waiting for the
        # remote AI request. Generate first, then simulate a short typing burst.
        reply = await get_ai_reply(chat_id, user_text, extra_system=extra_system)
        print(f"[debug] gemini returned: {reply!r}")

        if reply is None:
            print("[debug] reply is None, staying silent")
            return

        typing_for = natural_typing_seconds(reply)
        print(f"[debug] short typing simulation: {typing_for:.1f}s")
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(typing_for)

        await event.reply(reply)
        print("[debug] reply sent successfully")
        last_activity_time[chat_id] = time.time()
    except Exception as e:
        print(f"[error] chat_id={chat_id}: {e}")


async def _set_account_online():
    """Explicitly tell Telegram that this account is online."""
    global presence_online
    try:
        await client(functions.account.UpdateStatusRequest(offline=False))
        presence_online = True
        print("[presence] account is ONLINE")
        return True
    except Exception as e:
        presence_online = False
        print(f"[presence] online update failed: {e}")
        return False


async def _set_account_offline():
    """Explicitly tell Telegram that this account is offline."""
    global presence_online
    try:
        await client(functions.account.UpdateStatusRequest(offline=True))
        presence_online = False
        print("[presence] account is OFFLINE")
    except Exception as e:
        print(f"[presence] offline update failed: {e}")


async def _presence_worker():
    """Refresh online status until the 10-minute activity window expires."""
    global presence_task
    try:
        while True:
            async with presence_lock:
                remaining = presence_until - time.time()
                active = presence_online
            if not active or remaining <= 0:
                break

            # Refresh before Telegram's status naturally expires.
            await asyncio.sleep(min(PRESENCE_REFRESH_SECONDS, max(1.0, remaining)))
            async with presence_lock:
                remaining = presence_until - time.time()
            if remaining <= 0:
                break
            await _set_account_online()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[presence worker error] {e}")
    finally:
        await _set_account_offline()
        async with presence_lock:
            presence_task = None


async def activate_presence_for_message():
    """Start/extend the account presence window for an incoming message."""
    global presence_until, presence_task, presence_starting

    async with presence_lock:
        now = time.time()
        was_active = presence_online and presence_until > now
        was_starting = presence_starting
        if not was_active and not was_starting:
            presence_starting = True

    if not was_active and not was_starting:
        print(f"[presence] offline -> waiting {PRESENCE_START_DELAY:.1f}s before ONLINE")
        await asyncio.sleep(PRESENCE_START_DELAY)
        await _set_account_online()
        async with presence_lock:
            presence_starting = False
    elif was_starting:
        # Another message arrived during the initial 6-second wait. Do not
        # add another 6-second delay; the first presence activation owns it.
        while True:
            async with presence_lock:
                if presence_online or not presence_starting:
                    break
            await asyncio.sleep(0.1)
        async with presence_lock:
            if not presence_online:
                return

    async with presence_lock:
        # Treat incoming activity as a fresh 10-minute active window.
        presence_until = time.time() + PRESENCE_ACTIVE_SECONDS
        if presence_task is None or presence_task.done():
            presence_task = asyncio.create_task(_presence_worker())


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
            msg = await get_ai_reply(OWNER_GROUP_ID, user_message=None, extra_system=extra_system)
            if msg is None:
                continue
            async with client.action(OWNER_GROUP_ID, "typing"):
                await asyncio.sleep(min(2.0, natural_typing_seconds(msg)))
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
    # Start in an explicitly offline state. Incoming messages do not make the
    # account intentionally visible until the 6-second presence delay passes.
    await _set_account_offline()
    me = await client.get_me()
    print(f"Logged in as: {getattr(me, 'username', None) or getattr(me, 'first_name', 'unknown')}")
    print("Listening for messages...")
    asyncio.create_task(idle_watcher())
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
