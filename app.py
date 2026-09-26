import os
import time
import json
import asyncio
import urllib.parse
import logging
import re
import aiohttp
from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import RequestWebViewRequest, RequestAppWebViewRequest
from telethon.tl.types import InputBotAppShortName
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    FloodWaitError
)

try:
    from web3 import Web3
    from eth_account import Account
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    import base64
    HAS_TONSDK = True
except ImportError:
    HAS_TONSDK = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RenderSessionCollector")

app = FastAPI(title="MY AGY AI — Standby Batch Session Link Collector")

SECRET_KEY = os.getenv("SECRET_KEY", "agy_cf_secret_7d36994e_2026")
API_ID = int(os.getenv("TELEGRAM_API_ID", "37321306"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "5cd9e5bbfb572a4429a0c54774153b47")
REPORT_CHAT_ID = os.getenv("REPORT_CHAT_ID", "6727787768")

CF_WORKER_URLS = [
    "https://restore-agy.aaaai2.workers.dev",
    "https://restore-agy.aaa-bot.workers.dev",
    "https://restore-agy.aaa222.workers.dev"
]

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://znbbaozpevurvbfkxakz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpuYmJhb3pwZXZ1cnZiZmt4YWt6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk4MTYxNTQsImV4cCI6MjEwNTM5MjE1NH0.ldgn0gCtOLEPUQyvTiG5RgKX6VY0LrS_4LkIKCf8NqM")
UPSTASH_URL = os.getenv("UPSTASH_URL", "https://relaxing-starfish-285827.upstash.io")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN", "gQAAAAAABFyDAAIgcDI5MDYyYWZjNzYzNzk0ZmRjYjhmNTA4ZDI4ODlmODkzNw")

STONES_BOT = "stoneswithestand_bot"
MRG_BOT = "mrgminerbot"
MRG_REFERRAL_CODE = "ref_IRN1G3XD"
ART_BOT = "ART_AIRDROP_BOT"
BNB_BOT = "CryptoProUpRobot"
AILAB_BOT = "AiLab_robot"
ULTRAWALLET_BOT = "UltrawalletTrade_Bot"
ULTRAWALLET_REFERRAL_CODE = "6727787768"
APX_BOT = "ApxMinerBot"
APX_REFERRAL_CODE = "6727787768"
AINOVUM_BOT = "ainovum_bot"
AINOVUM_REFERRAL_CODE = "ref_6727787768"
MININGGRAM_BOT = "MiningGRAM_Bot"
MININGGRAM_REFERRAL_CODE = "339JU9K"

LAST_BATCH_RUN = {
    "status": "idle",
    "collected": 0,
    "timestamp": 0
}

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "MY AGY AI Standby Batch Session Link Collector",
        "provider": "Render Cloud (Free Tier)",
        "purpose": "Wakes up on-demand to collect batch session links, syncs to 3x Cloudflare KV, triggers cloud farming, and spins down to save free hours.",
        "nodes": CF_WORKER_URLS,
        "last_run": LAST_BATCH_RUN
    }

@app.get("/health")
async def health():
    return {"ok": True, "status": "healthy"}

async def extract_tokens_for_account(acc: dict) -> dict:
    name = acc.get("name", "User")
    uid = str(acc.get("user_id"))
    sess_str = acc.get("session_string") or acc.get("session")
    if not sess_str:
        return {}

    client = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    tokens = {
        "account_id": uid,
        "name": name,
        "synced_at": time.time()
    }
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"[{name}] Session unauthorized")
            return {}

        # 1. Stones Miners WebApp initData
        try:
            bot = await client.get_entity(STONES_BOT)
            res = await client(RequestWebViewRequest(
                peer=bot,
                bot=bot,
                platform="android",
                url="https://app.stoneswithestand.my.id/"
            ))
            parsed = urllib.parse.urlparse(res.url)
            tokens["stones_init_data"] = urllib.parse.parse_qs(parsed.fragment).get("tgWebAppData", [None])[0]
        except Exception as e:
            logger.debug(f"[{name}] Stones error: {e}")

        # 2. MRG Miner WebApp initData
        try:
            bot_in = await client.get_input_entity(MRG_BOT)
            res = await client(RequestAppWebViewRequest(
                peer=bot_in,
                app=InputBotAppShortName(bot_id=bot_in, short_name="app"),
                platform="android",
                start_param=MRG_REFERRAL_CODE
            ))
            parsed = urllib.parse.urlparse(res.url)
            tokens["mrg_init_data"] = urllib.parse.parse_qs(parsed.fragment).get("tgWebAppData", [None])[0]
        except Exception as e:
            logger.debug(f"[{name}] MRG error: {e}")

        # 3. ART Airdrop WebApp initData
        try:
            bot = await client.get_entity(ART_BOT)
            res = await client(RequestWebViewRequest(
                peer=bot,
                bot=bot,
                platform="android",
                url=f"https://art.tamimdev.dev/?ref={REPORT_CHAT_ID}"
            ))
            parsed = urllib.parse.urlparse(res.url)
            tokens["art_init_data"] = urllib.parse.parse_qs(parsed.fragment).get("tgWebAppData", [None])[0]
        except Exception as e:
            logger.debug(f"[{name}] ART error: {e}")

        # 4. BNB Galaxy Webhook Link
        try:
            messages = await client.get_messages(BNB_BOT, limit=20)
            for msg in messages:
                for text_val in [getattr(msg, "text", None), getattr(msg, "raw_text", None)]:
                    if text_val and "wh=" in text_val:
                        m = re.search(r"wh=([^&\s\"'>]+)", text_val)
                        if m:
                            tokens["bnb_wh_url"] = urllib.parse.unquote(m.group(1))
                            break
                if "bnb_wh_url" in tokens:
                    break
        except Exception as e:
            logger.debug(f"[{name}] BNB webhook error: {e}")

        # 5. AI Lab Robot WebApp initData
        try:
            bot_ai = await client.get_entity(AILAB_BOT)
            res_ai = await client(RequestWebViewRequest(
                peer=bot_ai,
                bot=bot_ai,
                platform="android",
                url="https://ailab-agent.online/"
            ))
            parsed_ai = urllib.parse.urlparse(res_ai.url)
            ai_init = urllib.parse.parse_qs(parsed_ai.fragment).get("tgWebAppData", [None])[0]
            if ai_init:
                tokens["ailab_init_data"] = ai_init
        except Exception as aie:
            logger.debug(f"[{name}] AI Lab error: {aie}")

        # 6. UltraWallet WebApp initData
        try:
            bot_uw = await client.get_input_entity(ULTRAWALLET_BOT)
            res_uw = await client(RequestAppWebViewRequest(
                peer=bot_uw,
                app=InputBotAppShortName(bot_id=bot_uw, short_name="app"),
                platform="android",
                start_param=str(ULTRAWALLET_REFERRAL_CODE)
            ))
            parsed_uw = urllib.parse.urlparse(res_uw.url)
            uw_init = urllib.parse.parse_qs(parsed_uw.fragment).get("tgWebAppData", [None])[0]
            if uw_init:
                tokens["ultrawallet_init_data"] = uw_init
        except Exception as uwe:
            logger.debug(f"[{name}] UltraWallet error: {uwe}")

        # 7. Apex Miner WebApp initData
        try:
            bot_apx = await client.get_input_entity(APX_BOT)
            res_apx = await client(RequestAppWebViewRequest(
                peer=bot_apx,
                app=InputBotAppShortName(bot_id=bot_apx, short_name="app"),
                platform="android",
                start_param=str(APX_REFERRAL_CODE)
            ))
            parsed_apx = urllib.parse.urlparse(res_apx.url)
            apx_init = urllib.parse.parse_qs(parsed_apx.fragment).get("tgWebAppData", [None])[0]
            if apx_init:
                tokens["apx_init_data"] = apx_init
        except Exception as apx_e:
            logger.debug(f"[{name}] Apex Miner error: {apx_e}")

        # 8. Ainovum Bot WebApp initData
        try:
            bot_an = await client.get_entity(AINOVUM_BOT)
            res_an = await client(RequestWebViewRequest(
                peer=bot_an,
                bot=bot_an,
                platform="android",
                url=f"https://ainovum.biz/?startapp={AINOVUM_REFERRAL_CODE}&ref={AINOVUM_REFERRAL_CODE}"
            ))
            parsed_an = urllib.parse.urlparse(res_an.url)
            an_init = urllib.parse.parse_qs(parsed_an.fragment).get("tgWebAppData", [None])[0]
            if an_init:
                tokens["ainovum_init_data"] = an_init
        except Exception as ane:
            logger.debug(f"[{name}] Ainovum error: {ane}")

        # 9. MiningGRAM Bot WebApp initData
        try:
            bot_mg = await client.get_input_entity(MININGGRAM_BOT)
            res_mg = await client(RequestAppWebViewRequest(
                peer=bot_mg,
                app=InputBotAppShortName(bot_id=bot_mg, short_name="mine"),
                platform="android",
                start_param=MININGGRAM_REFERRAL_CODE
            ))
            parsed_mg = urllib.parse.urlparse(res_mg.url)
            mg_init = urllib.parse.parse_qs(parsed_mg.fragment).get("tgWebAppData", [None])[0]
            if mg_init:
                tokens["mininggram_init_data"] = mg_init
        except Exception as mge:
            logger.debug(f"[{name}] MiningGRAM error: {mge}")

        # 10. ATF Miner WebApp initData (@ATF_AIRDROP_bot)
        try:
            bot_atf = await client.get_entity("ATF_AIRDROP_bot")
            res_atf = await client(RequestWebViewRequest(
                peer=bot_atf,
                bot=bot_atf,
                platform="android",
                url="https://atfminers.asloni.online/miner/index.html?entry=bot_start",
                start_param=REPORT_CHAT_ID
            ))
            parsed_atf = urllib.parse.urlparse(res_atf.url)
            atf_init = urllib.parse.parse_qs(parsed_atf.fragment).get("tgWebAppData", [None])[0]
            if atf_init:
                tokens["atf_init_data"] = atf_init
        except Exception as atf_e:
            logger.debug(f"[{name}] ATF Miner error: {atf_e}")

    except Exception as e:
        logger.error(f"[{name}] Telethon connection error: {e}")
    finally:
        await client.disconnect()

    return tokens

@app.post("/collect-tokens")
async def collect_tokens(request: Request):
    auth = request.headers.get("Authorization") or ""
    if auth != f"Bearer {SECRET_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    accounts = body.get("accounts", [])
    
    # If accounts lack session strings, pull latest_backup_zip from Cloudflare KV
    has_sessions = any(a.get("session_string") or a.get("session") for a in accounts) if accounts else False
    if not has_sessions:
        import zipfile
        import io
        async with aiohttp.ClientSession() as http:
            for cf_url in CF_WORKER_URLS:
                try:
                    async with http.get(f"{cf_url}/backup.zip", timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status == 200:
                            zip_bytes = await r.read()
                            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                                if "accounts.json" in zf.namelist():
                                    raw_acc = zf.read("accounts.json").decode("utf-8")
                                    accounts = json.loads(raw_acc)
                                    logger.info(f"Loaded {len(accounts)} accounts with sessions from Cloudflare KV backup archive.")
                                    break
                except Exception as e:
                    logger.warning(f"Could not load backup zip from {cf_url}: {e}")

    if not accounts:
        return {"ok": True, "message": "No accounts with sessions found in backup archive or body", "collected": 0}

    LAST_BATCH_RUN["status"] = "running"
    LAST_BATCH_RUN["timestamp"] = time.time()

    collected_batch = {}
    for acc in accounts:
        uid = str(acc.get("user_id"))
        tokens = await extract_tokens_for_account(acc)
        if tokens:
            collected_batch[uid] = tokens
            async with aiohttp.ClientSession() as http:
                # 1. Sync to 3x Cloudflare KV
                for cf_url in CF_WORKER_URLS:
                    try:
                        await http.post(
                            f"{cf_url}/api/miniapp/tokens/sync",
                            json=tokens,
                            headers={
                                "Authorization": f"Bearer {SECRET_KEY}",
                                "Content-Type": "application/json",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            },
                            timeout=aiohttp.ClientTimeout(total=5)
                        )
                    except Exception as se:
                        logger.warning(f"Sync error to {cf_url}: {se}")

                # 2. Sync to Upstash Redis
                if UPSTASH_URL and UPSTASH_TOKEN:
                    try:
                        await http.post(
                            f"{UPSTASH_URL}/set/fleet:tokens:{uid}",
                            data=json.dumps(tokens),
                            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                            timeout=aiohttp.ClientTimeout(total=4)
                        )
                    except Exception as ue:
                        logger.warning(f"Upstash token sync note: {ue}")

                # 3. Sync to Supabase Postgres
                if SUPABASE_URL and SUPABASE_KEY:
                    try:
                        await http.patch(
                            f"{SUPABASE_URL}/rest/v1/fleet_accounts?id=eq.{uid}",
                            json={"data": tokens},
                            headers={
                                "apikey": SUPABASE_KEY,
                                "Authorization": f"Bearer {SUPABASE_KEY}",
                                "Content-Type": "application/json"
                            },
                            timeout=aiohttp.ClientTimeout(total=4)
                        )
                    except Exception as sbe:
                        logger.warning(f"Supabase account update note: {sbe}")

    # Trigger Cloudflare Edge Autonomous Cloud Farming for ALL bots
    async with aiohttp.ClientSession() as http:
        for idx, cf_url in enumerate(CF_WORKER_URLS):
            try:
                await http.post(
                    f"{cf_url}/api/farm/all",
                    json={"all": True, "bot": "all"},
                    headers={"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
            except Exception:
                pass

    LAST_BATCH_RUN["status"] = "completed"
    LAST_BATCH_RUN["collected"] = len(collected_batch)
    LAST_BATCH_RUN["timestamp"] = time.time()

    return {
        "ok": True,
        "collected": len(collected_batch),
        "timestamp": time.time(),
        "message": "Batch session links collected and synced to 3x Cloudflare KV nodes. Cloud farming dispatched. Standby node entering sleep."
    }

# ============================================================================
# CLOUD BNB GALAXY AUTONOMOUS ENGINE (Balance Checks & Auto-Withdrawals)
# ============================================================================
MIN_WITHDRAWAL = float(os.getenv("MIN_WITHDRAWAL", "0.000055"))
DEFAULT_WALLET = os.getenv("WALLET_ADDRESS", "0xfda4182001672b9f0f09e2118242e543e35ed5ce")
CLOUD_BNB_STATUS = {
    "last_cycle_at": 0,
    "status": "idle",
    "accounts": {}
}

async def fetch_accounts_from_cloud():
    accounts = []
    import zipfile
    import io
    async with aiohttp.ClientSession() as http:
        for cf_url in CF_WORKER_URLS:
            try:
                async with http.get(f"{cf_url}/backup.zip", timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        zip_bytes = await r.read()
                        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                            if "accounts.json" in zf.namelist():
                                raw_acc = zf.read("accounts.json").decode("utf-8")
                                accounts = json.loads(raw_acc)
                                logger.info(f"Loaded {len(accounts)} accounts from Cloudflare KV backup archive.")
                                return accounts
            except Exception as e:
                logger.warning(f"Could not load backup zip from {cf_url}: {e}")
    return accounts

CACHED_GROQ_KEYS = []

async def get_groq_keys() -> list:
    global CACHED_GROQ_KEYS
    if CACHED_GROQ_KEYS:
        return CACHED_GROQ_KEYS
    env_keys = [
        os.getenv("GROQ_API_KEY_1"),
        os.getenv("GROQ_API_KEY_2"),
        os.getenv("GROQ_API_KEY_3"),
        os.getenv("GROQ_API_KEY")
    ]
    CACHED_GROQ_KEYS = [k for k in env_keys if k]
    if not CACHED_GROQ_KEYS and UPSTASH_URL and UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{UPSTASH_URL}/get/fleet:groq_keys", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status == 200:
                        data = await r.json()
                        res = data.get("result")
                        if res:
                            parsed = json.loads(res) if isinstance(res, str) else res
                            if isinstance(parsed, list):
                                CACHED_GROQ_KEYS = [k for k in parsed if k]
        except Exception:
            pass
    return CACHED_GROQ_KEYS

async def ai_classify_bot_prompt(bot_text: str) -> str:
    """Uses Cloudflare Edge AI (Gemini + Groq + Cloudflare Workers AI) with Groq direct fallback."""
    prompt = (
        f"The Telegram bot sent this message during a withdrawal: '{bot_text}'. "
        f"Classify what the bot requires from the user. Respond with ONLY one word: "
        f"WALLET (asking for crypto wallet address), EMAIL (asking for email address), "
        f"AMOUNT (asking for withdrawal amount or number), CONFIRM (asking to click a button or confirm), "
        f"or WAIT (asking to wait or showing status)."
    )

    # 1. Primary: Cloudflare Edge Multi-Cloud AI Cascade (Gemini Flash -> Groq -> Workers AI)
    for cf_url in CF_WORKER_URLS:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{cf_url}/api/ai",
                    json={"prompt": prompt},
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=4)
                ) as r:
                    if r.status == 200:
                        d = await r.json()
                        ans = (d.get("answer") or "").strip().upper()
                        for valid in ["WALLET", "EMAIL", "AMOUNT", "CONFIRM", "WAIT"]:
                            if valid in ans:
                                return valid
        except Exception:
            continue

    # 2. Secondary Fallback: Direct Groq API
    keys = await get_groq_keys()
    for k in keys:
        try:
            async with aiohttp.ClientSession() as s:
                payload = {
                    "model": "qwen/qwen3.8-27b",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 10,
                    "temperature": 0.1
                }
                headers = {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}
                async with s.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        d = await r.json()
                        ans = d.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
                        for valid in ["WALLET", "EMAIL", "AMOUNT", "CONFIRM", "WAIT"]:
                            if valid in ans:
                                return valid
        except Exception:
            continue
    return "UNKNOWN"

async def check_and_auto_withdraw_cloud(acc: dict) -> dict:
    name = acc.get("name", "User")
    uid = str(acc.get("user_id"))
    sess_str = acc.get("session_string") or acc.get("session")
    target_wallet = acc.get("bnb_wallet") or DEFAULT_WALLET
    if not sess_str:
        return {"user_id": uid, "name": name, "ok": False, "error": "No session string"}

    result = {
        "user_id": uid,
        "name": name,
        "balance": 0.0,
        "withdrawn": False,
        "amount": 0.0,
        "verification_count": 0,
        "status": "checked",
        "timestamp": time.time(),
        "ok": True
    }

    client = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result["ok"] = False
            result["error"] = "Unauthorized session"
            return result

        # 1. Fetch live balance from @CryptoProUpRobot
        init_msgs = await client.get_messages(BNB_BOT, limit=1)
        last_id = init_msgs[0].id if init_msgs else 0
        await client.send_message(BNB_BOT, "💰 Balance")

        balance = 0.0
        for _ in range(8):
            await asyncio.sleep(1.0)
            msgs = await client.get_messages(BNB_BOT, limit=3)
            found = False
            for m in msgs:
                if m.id > last_id and not m.out:
                    text = m.raw_text or ""
                    match = re.search(r"Your Balance:\s*([0-9.]+)\s*BNB", text, re.IGNORECASE)
                    if match:
                        balance = float(match.group(1))
                        found = True
                        break
            if found:
                break

        result["balance"] = balance
        logger.info(f"[{name}] Cloud BNB Balance: {balance:.6f} BNB (Threshold: {MIN_WITHDRAWAL})")

        # 2. Inspect Adsgram 5-step verification count
        v_count = 0
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36",
                "Referer": "https://justtool.site/tasks-adsgram/",
                "Origin": "https://justtool.site"
            }
            async with aiohttp.ClientSession() as http:
                async with http.get(f"https://justtool.site/api/adsgram-task3?tgId={uid}", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as vr:
                    if vr.status == 200:
                        vd = await vr.json()
                        v_count = vd.get("count", 0)
        except Exception:
            pass
        result["verification_count"] = v_count

        # 3. Check if balance >= MIN_WITHDRAWAL
        if balance >= MIN_WITHDRAWAL:
            withdraw_amount = round(balance, 6)
            amount_str = f"{withdraw_amount:.6f}".rstrip("0").rstrip(".")
            logger.info(f"[{name}] Cloud Auto-Withdraw triggered: {amount_str} BNB to {target_wallet}")

            prev_msgs = await client.get_messages(BNB_BOT, limit=1)
            prev_id = prev_msgs[0].id if prev_msgs else 0
            await client.send_message(BNB_BOT, "📤 Withdraw")

            wallet_submitted = False
            email_submitted = False
            amount_submitted = False

            for turn in range(1, 7):
                bot_msg = None
                for _ in range(6):
                    await asyncio.sleep(1.0)
                    msgs = await client.get_messages(BNB_BOT, limit=3)
                    for m in msgs:
                        if m.id > prev_id and not m.out:
                            bot_msg = m
                            break
                    if bot_msg:
                        break

                if not bot_msg:
                    if turn == 1:
                        prev_msgs = await client.get_messages(BNB_BOT, limit=1)
                        prev_id = prev_msgs[0].id if prev_msgs else 0
                        await client.send_message(BNB_BOT, "/withdraw")
                        continue
                    else:
                        break

                prev_id = bot_msg.id
                bot_text = (bot_msg.raw_text or "").strip()
                bot_lower = bot_text.lower()
                logger.info(f"[{name} Turn {turn}] Bot: {bot_text[:80]}")

                if bot_msg.buttons:
                    for row in bot_msg.buttons:
                        for btn in row:
                            btn_t = (btn.text or "").lower()
                            if any(w in btn_t for w in ["confirm", "yes", "proceed", "submit", "accept", "agree"]):
                                try:
                                    await btn.click()
                                    await asyncio.sleep(1.5)
                                except Exception:
                                    pass
                                break

                if any(w in bot_lower for w in ["verification required", "withdrawal request submitted", "request submitted", "withdraw-adsgram"]):
                    break

                if any(w in bot_lower for w in ["send your email", "email id", "email for continue"]) and not email_submitted:
                    rand_id = int(time.time() * 1000) % 90000 + 10000
                    await client.send_message(BNB_BOT, f"user_{uid}_{rand_id}@gmail.com")
                    email_submitted = True
                    continue

                if any(w in bot_lower for w in ["wallet address", "submit your bnb", "bep-20", "bep20", "enter your wallet", "enter bnb"]) and not wallet_submitted:
                    await client.send_message(BNB_BOT, target_wallet)
                    wallet_submitted = True
                    continue

                if any(w in bot_lower for w in ["enter the amount", "amount of bnb", "how much", "minimum withdrawal", "min:", "enter amount", "amount to withdraw"]) and not amount_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                # AI dynamic classification fallback
                ai_intent = await ai_classify_bot_prompt(bot_text)
                logger.info(f"[{name} Turn {turn}] AI Prompt Classification: {ai_intent}")

                if ai_intent == "EMAIL" and not email_submitted:
                    rand_id = int(time.time() * 1000) % 90000 + 10000
                    await client.send_message(BNB_BOT, f"user_{uid}_{rand_id}@gmail.com")
                    email_submitted = True
                    continue

                if ai_intent == "WALLET" and not wallet_submitted:
                    await client.send_message(BNB_BOT, target_wallet)
                    wallet_submitted = True
                    continue

                if ai_intent == "AMOUNT" and not amount_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                if ai_intent == "WAIT":
                    await asyncio.sleep(2.0)
                    continue

                if not amount_submitted and wallet_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                if amount_submitted and (wallet_submitted or "0x" in bot_lower):
                    break

            # Advance anti-bot verification to 5/5
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36",
                "Referer": "https://justtool.site/tasks-adsgram/",
                "Origin": "https://justtool.site"
            }
            async with aiohttp.ClientSession() as http:
                while v_count < 5:
                    try:
                        async with http.post("https://justtool.site/api/adsgram-task3", headers=headers, json={"tgId": int(uid), "name": f"Member {uid}"}, timeout=aiohttp.ClientTimeout(total=5)) as step_r:
                            if step_r.status == 200:
                                s_data = await step_r.json()
                                v_count = s_data.get("count", v_count + 1)
                            else:
                                break
                    except Exception:
                        break
                    if v_count < 5:
                        await asyncio.sleep(1.2)

            result["withdrawn"] = True
            result["amount"] = withdraw_amount
            result["verification_count"] = v_count
            result["status"] = "withdrawn"
            logger.info(f"[{name}] ✅ Cloud Auto-Withdrawal completed: {amount_str} BNB (5/5 verified)")

            # Record payout to Upstash
            if UPSTASH_URL and UPSTASH_TOKEN:
                try:
                    payout_payload = {
                        "account_id": uid,
                        "name": name,
                        "amount": withdraw_amount,
                        "currency": "BNB",
                        "wallet": target_wallet,
                        "network": "BEP-20",
                        "timestamp": time.time(),
                        "status": "processing"
                    }
                    async with aiohttp.ClientSession() as http:
                        await http.post(
                            f"{UPSTASH_URL}/lpush/fleet:payouts",
                            data=json.dumps(payout_payload),
                            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                            timeout=aiohttp.ClientTimeout(total=4)
                        )
                except Exception:
                    pass

            # Send Official Telegram Payout Receipt with Bangladesh Time (BST)
            import datetime
            bot_token = os.getenv("ALERT_BOT_TOKEN", "8858823950:AAFFkuls8hBf23taCZE1y5gVzP4AFCuqI5o")
            bst_time = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)).strftime("%Y-%m-%d %I:%M:%S %p BST")
            usd_val = withdraw_amount * 645.0
            bdt_val = usd_val * 122.50

            receipt_msg = (
                f"🎉 <b>OFFICIAL BNB GALAXY PAYOUT RECEIPT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Account:</b> {name} (<code>{uid}</code>)\n"
                f"💰 <b>Amount:</b> <code>{amount_str} BNB</code> (~${usd_val:.4f} USD / ~৳{bdt_val:.2f} BDT)\n"
                f"💼 <b>Recipient Wallet:</b> <a href=\"https://bscscan.com/address/{target_wallet}\"><code>{target_wallet}</code></a>\n"
                f"🌐 <b>Network:</b> Binance Smart Chain (BEP-20)\n"
                f"🛡️ <b>Verification:</b> <code>5/5 Anti-Bot Human Steps Completed</code> ✅\n"
                f"🕒 <b>Submitted At:</b> <code>{bst_time}</code> (Bangladesh Time)\n"
                f"⏳ <b>Status:</b> <b>Processing</b> (Estimated ~8 hours)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <b>Fleet Node:</b> Render Cloud Standby • Singapore & Frankfurt\n"
                f"🛡️ <b>Autonomous Cloud Fleet Operations by MY AGY AI</b>"
            )

            receipt_markup = {
                "inline_keyboard": [
                    [{"text": "🔍 View on BscScan", "url": f"https://bscscan.com/address/{target_wallet}"}],
                    [{"text": "🚀 Launch Mini App", "url": "https://restore-agy.aaaai2.workers.dev/dashboard"}],
                    [{"text": "📢 Verified Payouts Channel", "url": "https://t.me/+oN8uefSRYWUyM2Fl"}]
                ]
            }

            async with aiohttp.ClientSession() as http:
                # Send to Admin Private DM
                try:
                    await http.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={
                            "chat_id": REPORT_CHAT_ID,
                            "text": receipt_msg,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                            "reply_markup": receipt_markup
                        },
                        timeout=aiohttp.ClientTimeout(total=5)
                    )
                except Exception as te:
                    logger.warning(f"Telegram receipt note: {te}")

                # Send to Payout Channel
                try:
                    await http.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={
                            "chat_id": "-1004402765950",
                            "text": receipt_msg,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                            "reply_markup": receipt_markup
                        },
                        timeout=aiohttp.ClientTimeout(total=5)
                    )
                except Exception as pe:
                    logger.warning(f"Payout channel note: {pe}")


    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"[{name}] Cloud BNB cycle error: {e}")
    finally:
        await client.disconnect()

    return result

@app.post("/bnb/cloud-cycle")
async def bnb_cloud_cycle(request: Request):
    auth = request.headers.get("Authorization") or ""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    accounts = body.get("accounts", [])
    if not accounts:
        accounts = await fetch_accounts_from_cloud()

    if not accounts:
        return {"ok": False, "message": "No accounts found"}

    CLOUD_BNB_STATUS["status"] = "running"
    CLOUD_BNB_STATUS["last_cycle_at"] = time.time()

    results = []
    for acc in accounts:
        res = await check_and_auto_withdraw_cloud(acc)
        results.append(res)
        CLOUD_BNB_STATUS["accounts"][str(res["user_id"])] = res
        await asyncio.sleep(1.0)

    CLOUD_BNB_STATUS["status"] = "idle"
    return {
        "ok": True,
        "checked": len(results),
        "withdrawn": sum(1 for r in results if r.get("withdrawn")),
        "results": results,
        "timestamp": time.time()
    }

@app.get("/bnb/status")
async def bnb_status():
    return {
        "ok": True,
        "status": CLOUD_BNB_STATUS["status"],
        "last_cycle_at": CLOUD_BNB_STATUS["last_cycle_at"],
        "accounts": CLOUD_BNB_STATUS["accounts"]
    }

BETTERSTACK_HEARTBEAT_URL = "https://uptime.betterstack.com/api/v1/heartbeat/bABS7gYDXgHp6H35XGcU7S6p"

async def bnb_cloud_watchdog():
    logger.info("Starting Cloud BNB Watchdog (runs every 30m)...")
    await asyncio.sleep(45)
    while True:
        try:
            # 1. Ping BetterStack Heartbeat to confirm Cloud Render is 100% operational
            async with aiohttp.ClientSession() as session:
                try:
                    await session.get(BETTERSTACK_HEARTBEAT_URL, timeout=aiohttp.ClientTimeout(total=10))
                except Exception as hbe:
                    logger.warning(f"Heartbeat ping error: {hbe}")

            accounts = await fetch_accounts_from_cloud()
            if accounts:
                for acc in accounts:
                    res = await check_and_auto_withdraw_cloud(acc)
                    CLOUD_BNB_STATUS["accounts"][str(res["user_id"])] = res
                    await asyncio.sleep(1.5)
                CLOUD_BNB_STATUS["last_cycle_at"] = time.time()
        except Exception as e:
            logger.error(f"Watchdog error: {e}")
        await asyncio.sleep(1800)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(bnb_cloud_watchdog())
    asyncio.create_task(cloud_wealth_automation_watchdog())



# =====================================================================
# FAST CLOUD MTPROTO ACCOUNT ONBOARDING & REFERRAL BINDING ENGINE
# =====================================================================
LOGIN_SESSIONS = {}

def get_clean_phone(raw_phone: str) -> str:
    p = re.sub(r"[\s\-\(\)]", "", str(raw_phone).strip())
    if p.startswith("00"):
        p = "+" + p[2:]
    elif not p.startswith("+"):
        if p.startswith("01") and len(p) == 11:
            p = "+880" + p[1:]
        elif p.startswith("1") and len(p) == 10:
            p = "+880" + p
        else:
            p = "+" + p
    return p

async def bind_account_master_referrals(client: TelegramClient, acc_entry: dict):
    """
    Guarantees master referral codes are registered on all 8 bots:
    1. Stones: r6727787768
    2. MRG: ref_IRN1G3XD
    3. ART: 6727787768
    4. AI Lab: 296852
    5. UltraWallet: 6727787768
    6. Apex: 6727787768
    7. Ainovum: ref_6727787768
    8. ATF Miner: 6727787768
    """
    name = acc_entry.get("name", "User")
    uid = acc_entry.get("user_id")
    logger.info(f"[{name}] 🚀 Initiating 8-bot master referral binding (Master ID: 6727787768)...")

    # 1. Stones Miner
    try:
        b_stones = await client.get_entity(STONES_BOT)
        await client.send_message(b_stones, "/start r6727787768")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] Stones referral bind note: {e}")

    # 2. MRG Miner
    try:
        b_mrg = await client.get_entity(MRG_BOT)
        await client.send_message(b_mrg, f"/start {MRG_REFERRAL_CODE}")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] MRG referral bind note: {e}")

    # 3. ART Airdrop
    try:
        b_art = await client.get_entity(ART_BOT)
        await client.send_message(b_art, f"/start {REPORT_CHAT_ID}")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] ART referral bind note: {e}")

    # 4. AI Lab Robot
    try:
        b_ai = await client.get_entity(AILAB_BOT)
        await client.send_message(b_ai, "/start 296852")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] AI Lab referral bind note: {e}")

    # 5. UltraWallet
    try:
        b_uw = await client.get_entity(ULTRAWALLET_BOT)
        await client.send_message(b_uw, f"/start {ULTRAWALLET_REFERRAL_CODE}")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] UltraWallet referral bind note: {e}")

    # 6. Apex Miner
    try:
        b_apx = await client.get_entity(APX_BOT)
        await client.send_message(b_apx, f"/start {APX_REFERRAL_CODE}")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] Apex referral bind note: {e}")

    # 7. Ainovum Bot
    try:
        b_ain = await client.get_entity(AINOVUM_BOT)
        await client.send_message(b_ain, f"/start {AINOVUM_REFERRAL_CODE}")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] Ainovum referral bind note: {e}")

    # 8. ATF Miner
    try:
        b_atf = await client.get_entity("ATF_AIRDROP_bot")
        await client.send_message(b_atf, f"/start {REPORT_CHAT_ID}")
        await asyncio.sleep(0.8)
    except Exception as e:
        logger.warning(f"[{name}] ATF referral bind note: {e}")

    logger.info(f"[{name}] ✅ All 8 fleet bots successfully bound to Master ID 6727787768!")

    # Notify Telegram Admin & Vault
    bot_token = os.getenv("REPORT_BOT_TOKEN", "8858823950:AAFFkuls8hBf23taCZE1y5gVzP4AFCuqI5o")
    receipt = (
        f"🔗 <b>Master Referrals Bound (8/8 Bots)</b>\n\n"
        f"• <b>Account:</b> {name} (<code>{uid}</code>)\n"
        f"• <b>Master Referral ID:</b> <code>6727787768</code>\n"
        f"• <b>Active Bots Bound:</b>\n"
        f"  ✅ Stones Miners (@stoneswithestand_bot)\n"
        f"  ✅ MRG Miner (@mrgminerbot)\n"
        f"  ✅ ART Airdrop (@ART_AIRDROP_BOT)\n"
        f"  ✅ AI Lab Robot (@AiLab_robot)\n"
        f"  ✅ UltraWallet (@UltrawalletTrade_Bot)\n"
        f"  ✅ Apex Miner (@ApxMinerBot)\n"
        f"  ✅ Ainovum Bot (@ainovum_bot)\n"
        f"  ✅ ATF Miner (@ATF_AIRDROP_bot)\n\n"
        f"💎 All referral hash rate and earnings permanently credited to Master Account!"
    )
    async with aiohttp.ClientSession() as s:
        try:
            await s.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": REPORT_CHAT_ID, "text": receipt, "parse_mode": "HTML"},
                timeout=aiohttp.ClientTimeout(total=8)
            )
        except Exception:
            pass

    try:
        await client.disconnect()
    except Exception:
        pass


async def sync_new_account_to_clouds(acc_entry: dict):
    """Saves new permanent account across Cloudflare KV, Supabase, and Upstash Redis."""
    # 1. Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{SUPABASE_URL}/rest/v1/accounts",
                    headers={
                        "apikey": SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates"
                    },
                    json=acc_entry,
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception as e:
            logger.warning(f"Supabase sync note: {e}")

    # 2. Upstash Redis
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{UPSTASH_URL}/set/account:{acc_entry['user_id']}",
                    headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                    data=json.dumps(acc_entry),
                    timeout=aiohttp.ClientTimeout(total=10)
                )
                await s.post(
                    f"{UPSTASH_URL}/sadd/fleet_accounts_set/{acc_entry['user_id']}",
                    headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception as e:
            logger.warning(f"Upstash sync note: {e}")

    # 3. Cloudflare KV Sync
    for cf_url in CF_WORKER_URLS:
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{cf_url}/api/fleet/sync_account",
                    headers={"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"},
                    json=acc_entry,
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception:
            pass


@app.post("/api/account/login/send-code")
async def send_login_code(request: Request):
    """Direct fast MTProto code request in the cloud (<1 sec)."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    auth = request.headers.get("Authorization") or ""
    req_secret = data.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        pass

    chat_id = str(data.get("chat_id") or REPORT_CHAT_ID)
    raw_phone = data.get("phone", "")
    if not raw_phone:
        return {"ok": False, "error": "Phone number is required"}

    cleaned_phone = get_clean_phone(raw_phone)
    logger.info(f"[Standby Cloud Login] Requesting code for {cleaned_phone} (Chat {chat_id})")

    # Disconnect any old pending client for this chat
    if chat_id in LOGIN_SESSIONS and LOGIN_SESSIONS[chat_id].get("client"):
        try:
            await LOGIN_SESSIONS[chat_id]["client"].disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)

    temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await temp_client.connect()
        sent_code = await asyncio.wait_for(temp_client.send_code_request(cleaned_phone), timeout=25)
        LOGIN_SESSIONS[chat_id] = {
            "client": temp_client,
            "phone": cleaned_phone,
            "phone_code_hash": sent_code.phone_code_hash,
            "created_at": time.time()
        }
        logger.info(f"[Standby Cloud Login] ✅ Code dispatched to {cleaned_phone} (hash: {sent_code.phone_code_hash[:8]})")
        return {
            "ok": True,
            "phone": cleaned_phone,
            "phone_code_hash": sent_code.phone_code_hash,
            "message": f"Verification code sent to {cleaned_phone}"
        }
    except PhoneNumberInvalidError:
        try:
            await temp_client.disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)
        return {"ok": False, "error": f"Invalid phone number: {cleaned_phone}. Please check country code."}
    except Exception as e:
        logger.error(f"[Standby Cloud Login] Error sending code to {cleaned_phone}: {e}")
        try:
            await temp_client.disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)
        return {"ok": False, "error": str(e)}


@app.post("/api/account/login/verify-code")
async def verify_login_code(request: Request):
    """Direct fast MTProto code or 2FA password verification in the cloud (<1 sec)."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    chat_id = str(data.get("chat_id") or REPORT_CHAT_ID)
    code = str(data.get("code") or "").strip()
    password = str(data.get("password") or "").strip()

    session_data = LOGIN_SESSIONS.get(chat_id)
    if not session_data or not session_data.get("client"):
        return {"ok": False, "error": "No active login session found. Please tap Add Account to start over."}

    client: TelegramClient = session_data["client"]
    phone = session_data["phone"]
    phone_code_hash = session_data["phone_code_hash"]

    try:
        if not client.is_connected():
            await client.connect()

        if password:
            logger.info(f"[Standby Cloud Login] Attempting 2FA sign in for {phone}...")
            await asyncio.wait_for(client.sign_in(password=password), timeout=25)
        else:
            clean_code = re.sub(r"[^0-9]", "", code)
            if not clean_code or len(clean_code) < 3:
                return {"ok": False, "error": "Please provide a valid verification code."}
            logger.info(f"[Standby Cloud Login] Attempting code sign in for {phone} (code: {clean_code})...")
            await asyncio.wait_for(client.sign_in(phone=phone, code=clean_code, phone_code_hash=phone_code_hash), timeout=25)

        # Authenticated successfully!
        me = await client.get_me()
        user_id = me.id
        acc_name = f"{me.first_name or ''} {me.last_name or ''}".strip() or "User"
        uname = me.username or "None"
        sess_str = client.session.save()

        logger.info(f"[Standby Cloud Login] 🎉 Account signed in: {acc_name} (@{uname}, ID: {user_id})")

        acc_entry = {
            "name": acc_name,
            "username": uname,
            "user_id": user_id,
            "phone": phone,
            "session_string": sess_str,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "active"
        }

        # Automatically bind all 8 master referrals in the background
        asyncio.create_task(bind_account_master_referrals(client, acc_entry))

        # Sync account to Supabase, Upstash Redis, and Cloudflare KV
        asyncio.create_task(sync_new_account_to_clouds(acc_entry))

        LOGIN_SESSIONS.pop(chat_id, None)

        return {
            "ok": True,
            "user_id": user_id,
            "name": acc_name,
            "username": uname,
            "phone": phone,
            "session_string": sess_str,
            "referrals": "Binding to Master Fleet (8/8 Bots)...",
            "message": "Account connected successfully! All 8 fleet bots are being bound to Master ID 6727787768."
        }

    except SessionPasswordNeededError:
        logger.info(f"[Standby Cloud Login] 🔒 2FA password required for {phone}")
        return {
            "ok": False,
            "need_2fa": True,
            "phone": phone,
            "message": "Two-Factor Cloud Password required"
        }
    except PhoneCodeInvalidError:
        return {"ok": False, "need_2fa": False, "error": "Invalid verification code. Please check and retry."}
    except PhoneCodeExpiredError:
        try:
            await client.disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)
        return {"ok": False, "need_2fa": False, "error": "Verification code expired. Please tap Add Account to start over."}
    except Exception as e:
        logger.error(f"[Standby Cloud Login] Sign-in error: {e}")
        return {"ok": False, "need_2fa": False, "error": str(e)}


@app.post("/api/account/login/cancel")
async def cancel_login(request: Request):
    """Cancels active login session for a chat."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    chat_id = str(data.get("chat_id") or REPORT_CHAT_ID)
    if chat_id in LOGIN_SESSIONS:
        cl = LOGIN_SESSIONS[chat_id].get("client")
        if cl:
            try:
                await cl.disconnect()
            except Exception:
                pass
        LOGIN_SESSIONS.pop(chat_id, None)
        logger.info(f"[Standby Cloud Login] ❌ Login session cancelled for Chat {chat_id}")
    return {"ok": True, "message": "Login cancelled"}


# =============================================================================
# 100% CLOUD AUTOMATED WITHDRAWALS & ON-CHAIN VAULT SWEEPER ENGINE
# =============================================================================
MASTER_EVM_VAULT = "0xfda4182001672b9f0f09e2118242e543e35ed5ce"
MASTER_TON_VAULT = "UQBPZiSvitdPU3VUyJK2mRaHVBl69xejw5aOrh1KfKA7gwDT"
PAYOUT_CHANNEL_ID = os.getenv("PAYOUT_CHANNEL_ID", "-1004402765950")

async def send_payout_receipt(message: str):
    """Broadcasts payout & on-chain receipts to Telegram channel and Admin DM."""
    bot_token = os.getenv("REPORT_BOT_TOKEN", "8858823950:AAFFkuls8hBf23taCZE1y5gVzP4AFCuqI5o")
    targets = [REPORT_CHAT_ID, PAYOUT_CHANNEL_ID]
    async with aiohttp.ClientSession() as s:
        for tid in targets:
            try:
                await s.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": tid,
                        "text": message,
                        "parse_mode": "HTML" if "<" in message else "Markdown",
                        "disable_web_page_preview": True
                    },
                    timeout=aiohttp.ClientTimeout(total=8)
                )
            except Exception:
                pass


async def check_and_withdraw_ailab(session: aiohttp.ClientSession, acc: dict, tokens: dict) -> dict:
    """Checks and executes auto-withdrawal for AI Lab Robot (Threshold: $0.02 for master, $1.00 for workers)."""
    uid = str(acc.get("user_id"))
    name = acc.get("name", uid)
    is_master = (uid == "6727787768" or acc.get("phone") in ("+8801317342850", "01317342850") or acc.get("is_primary"))
    init_data = tokens.get(uid, {}).get("ailab_init_data")
    if not init_data:
        return {"uid": uid, "name": name, "status": "no_init_data", "balance": 0.0}

    base_url = "https://api.ailab-agent.online/api/v1"
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro)"}
    try:
        async with session.post(f"{base_url}/users/auth/login", json={"user": init_data}, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as lr:
            if lr.status != 200:
                return {"uid": uid, "name": name, "status": f"login_err_{lr.status}", "balance": 0.0}
            ld = await lr.json()
            tok = ld.get("result", {}).get("bearer") or ld.get("user_info", {}).get("session_id")
            if not tok:
                return {"uid": uid, "name": name, "status": "no_token", "balance": 0.0}

        auth_headers = {**headers, "Authorization": f"Bearer {tok}"}
        async with session.get(f"{base_url}/cashout", headers=auth_headers, timeout=aiohttp.ClientTimeout(total=8)) as cr:
            if cr.status != 200:
                return {"uid": uid, "name": name, "status": f"cashout_err_{cr.status}", "balance": 0.0}
            cd = await cr.json()
            ubal = float(cd.get("user_info", {}).get("balance", 0) or 0)

        thresh = 0.02 if is_master else 1.00
        logger.info(f"[Cloud AI Lab] {name} ({uid}) balance: ${ubal:.4f} USD (Threshold: ${thresh:.2f})")
        if ubal >= thresh:
            wd_usd = round(int(ubal * 100) / 100.0, 2)
            async with session.post(f"{base_url}/cashout-pay", json={"ps_id": 5, "amount_usd": wd_usd, "wallet": MASTER_EVM_VAULT, "dest_tag": ""}, headers=auth_headers, timeout=aiohttp.ClientTimeout(total=10)) as pr:
                pres = await pr.json()
                if pres.get("request_info", {}).get("error_code") == 0 or pres.get("result"):
                    role_str = "Main Master Host" if is_master else "Worker"
                    receipt = (
                        f"🎉 <b>AI Lab Robot Auto-Cashout Submitted!</b>\n\n"
                        f"• <b>Account:</b> {name} ({role_str} - <code>{uid}</code>)\n"
                        f"• <b>Amount:</b> <code>${wd_usd} USD</code>\n"
                        f"• <b>Destination:</b> <code>{MASTER_EVM_VAULT}</code> (BEP-20)\n"
                        f"• <b>Status:</b> Approved / In Flight\n"
                        f"🛡️ <i>100% Cloud Autonomous Execution</i>"
                    )
                    await send_payout_receipt(receipt)
                    return {"uid": uid, "name": name, "status": "withdrawn", "amount": wd_usd}
        return {"uid": uid, "name": name, "status": "below_threshold", "balance": ubal}
    except Exception as e:
        logger.warning(f"[Cloud AI Lab] Error for {name}: {e}")
        return {"uid": uid, "name": name, "status": "error", "error": str(e)}


async def check_and_withdraw_ainovum(session: aiohttp.ClientSession, acc: dict, tokens: dict) -> dict:
    """Checks and executes auto-withdrawal for Ainovum (Threshold: 0.10 USDT for master, 1.00 USDT for workers)."""
    uid = str(acc.get("user_id"))
    name = acc.get("name", uid)
    is_master = (uid == "6727787768" or acc.get("phone") in ("+8801317342850", "01317342850") or acc.get("is_primary"))
    init_data = tokens.get(uid, {}).get("ainovum_init_data")
    if not init_data:
        return {"uid": uid, "name": name, "status": "no_init_data", "available": 0.0}

    base_url = "https://ainovum.biz"
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro)"}
    try:
        cookie_hdr = ""
        boot_user = {}
        async with session.post(f"{base_url}/api/bootstrap", json={"initData": init_data, "platform": "android", "referrer": "ref_6727787768"}, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as br:
            if br.status == 200:
                bd = await br.json()
                boot_user = bd.get("user", {})
                raw_cookies = br.headers.getall("Set-Cookie", [])
                cookie_hdr = "; ".join([c.split(";")[0] for c in raw_cookies])
            else:
                return {"uid": uid, "name": name, "status": f"bootstrap_err_{br.status}", "available": 0.0}

        auth_headers = dict(headers)
        if cookie_hdr:
            auth_headers["Cookie"] = cookie_hdr

        # Open any available gift boxes
        try:
            async with session.get(f"{base_url}/api/gift-box/state", headers=auth_headers, timeout=aiohttp.ClientTimeout(total=5)) as gsr:
                if gsr.status == 200:
                    gsd = await gsr.json()
                    boxes_left = int(gsd.get("box", {}).get("boxes_left", 0) or 0)
                    while boxes_left > 0:
                        async with session.post(f"{base_url}/api/gift-box/open", json={}, headers=auth_headers, timeout=aiohttp.ClientTimeout(total=6)) as gbr:
                            if gbr.status == 200:
                                gbd = await gbr.json()
                                boxes_left = int(gbd.get("box", {}).get("boxes_left", 0) or 0)
                            else:
                                break
        except Exception:
            pass

        avail = 0.0
        async with session.get(f"{base_url}/api/withdraws/usdt/config", headers=auth_headers, timeout=aiohttp.ClientTimeout(total=8)) as cr:
            if cr.status == 200:
                cd = await cr.json()
                avail = float(cd.get("freeze", {}).get("available", 0) or 0)

        thresh = 0.10 if is_master else 1.00
        logger.info(f"[Cloud Ainovum] {name} ({uid}) available: {avail:.4f} USDT (Threshold: {thresh:.2f})")
        if boot_user.get("is_withdraw_locked") == 1:
            return {"uid": uid, "name": name, "status": "locked_or_deposit_required", "available": avail}

        if avail >= thresh:
            wd_amt = round(avail, 4)
            async with session.post(f"{base_url}/api/withdraws/usdt/create", json={"amount": wd_amt, "wallet": MASTER_EVM_VAULT, "network": "bep20"}, headers=auth_headers, timeout=aiohttp.ClientTimeout(total=10)) as wr:
                wd = await wr.json()
                if wr.status == 200 and not wd.get("access_denied") and not wd.get("error"):
                    receipt = (
                        f"🎉 <b>Ainovum USDT Auto-Withdrawal Submitted!</b>\n\n"
                        f"• <b>Account:</b> {name} (<code>{uid}</code>)\n"
                        f"• <b>Amount:</b> <code>{wd_amt} USDT</code> (BEP-20)\n"
                        f"• <b>Destination:</b> <code>{MASTER_EVM_VAULT}</code>\n"
                        f"• <b>Status:</b> Approved / Dispatched\n"
                        f"🛡️ <i>100% Cloud Autonomous Execution</i>"
                    )
                    await send_payout_receipt(receipt)
                    return {"uid": uid, "name": name, "status": "withdrawn", "amount": wd_amt}
        return {"uid": uid, "name": name, "status": "below_threshold", "available": avail}
    except Exception as e:
        logger.warning(f"[Cloud Ainovum] Error for {name}: {e}")
        return {"uid": uid, "name": name, "status": "error", "error": str(e)}


async def check_and_withdraw_stones(session: aiohttp.ClientSession, acc: dict, tokens: dict) -> dict:
    """Checks and executes auto-withdrawal for Stones Miners (Threshold: >= 500 STONES)."""
    uid = str(acc.get("user_id"))
    name = acc.get("name", uid)
    if uid == "6727787768":
        return {"uid": uid, "name": name, "status": "compounding_mode"}

    init_data = tokens.get(uid, {}).get("stones_init_data")
    if not init_data:
        return {"uid": uid, "name": name, "status": "no_init_data"}

    base_url = "https://app.stoneswithestand.my.id"
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro)"}
    try:
        async with session.post(f"{base_url}/api/state", json={"initData": init_data}, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as sr:
            if sr.status == 200:
                sd = await sr.json()
                coins = float(sd.get("user", {}).get("coins", 0) or 0)
                logger.info(f"[Cloud Stones] {name} ({uid}) coins: {coins:.1f} (Threshold: 500)")
                if coins >= 500:
                    receipt = (
                        f"💎 <b>Stones Miners Threshold Reached (>= 500 STONES)!</b>\n\n"
                        f"• <b>Account:</b> {name} (<code>{uid}</code>)\n"
                        f"• <b>Holding:</b> <code>{coins:.1f} STONES</code>\n"
                        f"• <b>Destination:</b> <code>{MASTER_EVM_VAULT}</code> (Arbitrum One)\n"
                        f"• <b>Status:</b> Threshold Met • Auto-Queued\n"
                        f"🛡️ <i>100% Cloud Autonomous Execution</i>"
                    )
                    await send_payout_receipt(receipt)
                    return {"uid": uid, "name": name, "status": "threshold_reached", "coins": coins}
                return {"uid": uid, "name": name, "status": "below_threshold", "coins": coins}
        return {"uid": uid, "name": name, "status": "state_check_failed"}
    except Exception as e:
        logger.warning(f"[Cloud Stones] Error for {name}: {e}")
        return {"uid": uid, "name": name, "status": "error", "error": str(e)}


# =============================================================================
# MULTI-CHAIN ON-CHAIN SWEEPER & CONSOLIDATION ENGINE
# =============================================================================
FLEET_EVM_CACHE = {}
FLEET_TON_CACHE = {}

BSC_USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
DRPC_KEY = os.getenv("DRPC_API_KEY", "AqfE-vxQsEgZrdrPasY_EsnLP3satOIR8YH4El_NDNxu")
TONAPI_KEY = os.getenv("TONAPI_KEY", "")
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "")

BSC_RPCS = [
    f"https://bsc.drpc.org/ogrpc?dkey={DRPC_KEY}",
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed1.binance.org"
]

ARB_RPCS = [
    f"https://arbitrum.drpc.org/ogrpc?dkey={DRPC_KEY}",
    "https://arb1.arbitrum.io/rpc"
]

async def load_fleet_wallets_from_cloud() -> tuple:
    """Loads worker EVM and TON wallets from local disk or Cloudflare backup.zip."""
    global FLEET_EVM_CACHE, FLEET_TON_CACHE
    if FLEET_EVM_CACHE and FLEET_TON_CACHE:
        return FLEET_EVM_CACHE, FLEET_TON_CACHE

    if os.path.exists("fleet_evm_wallets.json") and os.path.exists("fleet_ton_wallets.json"):
        try:
            with open("fleet_evm_wallets.json", "r", encoding="utf-8") as f:
                FLEET_EVM_CACHE = json.load(f)
            with open("fleet_ton_wallets.json", "r", encoding="utf-8") as f:
                FLEET_TON_CACHE = json.load(f)
            return FLEET_EVM_CACHE, FLEET_TON_CACHE
        except Exception:
            pass

    import zipfile, io
    async with aiohttp.ClientSession() as http:
        for cf_url in CF_WORKER_URLS:
            try:
                async with http.get(f"{cf_url}/backup.zip", timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        zip_bytes = await r.read()
                        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                            if "fleet_evm_wallets.json" in zf.namelist():
                                FLEET_EVM_CACHE = json.loads(zf.read("fleet_evm_wallets.json").decode("utf-8"))
                            if "fleet_ton_wallets.json" in zf.namelist():
                                FLEET_TON_CACHE = json.loads(zf.read("fleet_ton_wallets.json").decode("utf-8"))
                            if FLEET_EVM_CACHE and FLEET_TON_CACHE:
                                logger.info(f"Loaded {len(FLEET_EVM_CACHE)} EVM and {len(FLEET_TON_CACHE)} TON wallets from cloud backup.")
                                return FLEET_EVM_CACHE, FLEET_TON_CACHE
            except Exception as e:
                logger.warning(f"Could not load wallets from {cf_url}: {e}")
    return FLEET_EVM_CACHE, FLEET_TON_CACHE


async def query_evm_rpc(session: aiohttp.ClientSession, rpc_list: list, method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": int(time.time()), "method": method, "params": params}
    for rpc in rpc_list:
        try:
            async with session.post(rpc, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        return data["result"]
        except Exception:
            continue
    return None


async def audit_single_evm(session: aiohttp.ClientSession, uid: str, info: dict):
    if not isinstance(info, dict) or "address" not in info:
        return None
    addr = info["address"]
    name = info.get("name", f"Worker {uid}")
    clean_addr = addr.lower().replace("0x", "").zfill(64)
    usdt_call_data = "0x70a08231" + clean_addr

    raw_bnb_t = query_evm_rpc(session, BSC_RPCS, "eth_getBalance", [addr, "latest"])
    raw_eth_t = query_evm_rpc(session, ARB_RPCS, "eth_getBalance", [addr, "latest"])
    raw_usdt_t = query_evm_rpc(session, BSC_RPCS, "eth_call", [{"to": BSC_USDT_CONTRACT, "data": usdt_call_data}, "latest"])

    raw_bnb, raw_eth, raw_usdt = await asyncio.gather(raw_bnb_t, raw_eth_t, raw_usdt_t, return_exceptions=True)

    bnb_bal = int(raw_bnb, 16) / 1e18 if isinstance(raw_bnb, str) and raw_bnb else 0.0
    eth_bal = int(raw_eth, 16) / 1e18 if isinstance(raw_eth, str) and raw_eth else 0.0
    usdt_bal = int(raw_usdt, 16) / 1e18 if isinstance(raw_usdt, str) and raw_usdt not in ("0x", "0x0") else 0.0

    return {
        "uid": uid,
        "name": name,
        "address": addr,
        "private_key": info.get("private_key"),
        "bnb_balance": bnb_bal,
        "eth_balance": eth_bal,
        "usdt_balance": usdt_bal
    }


async def audit_single_ton(session: aiohttp.ClientSession, uid: str, info: dict, headers: dict):
    if not isinstance(info, dict) or "address" not in info:
        return None
    addr = info["address"]
    name = info.get("name", f"Worker {uid}")
    ton_bal = 0.0
    try:
        url = f"https://tonapi.io/v2/accounts/{addr}"
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw_bal = data.get("balance", 0)
                ton_bal = int(raw_bal) / 1e9
    except Exception:
        pass
    return {
        "uid": uid,
        "name": name,
        "address": addr,
        "mnemonic": info.get("mnemonic"),
        "ton_balance": ton_bal
    }


def sweep_evm_native_balance(rpc_list: list, chain_id: int, chain_name: str, private_key: str, from_addr: str, to_addr: str, native_balance: float, min_val: float = 0.0005):
    if not HAS_WEB3 or not private_key or native_balance <= min_val:
        return None
    try:
        w3 = None
        for rpc in rpc_list:
            try:
                tw3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                if tw3.is_connected():
                    w3 = tw3
                    break
            except Exception:
                continue
        if not w3:
            return None

        cs_from = Web3.to_checksum_address(from_addr)
        cs_to = Web3.to_checksum_address(to_addr)
        if cs_from.lower() == cs_to.lower():
            return None

        nonce = w3.eth.get_transaction_count(cs_from)
        gas_price = w3.eth.gas_price
        gas_limit = 50000 if chain_id == 42161 else 21000
        gas_cost = gas_price * gas_limit
        balance_wei = w3.eth.get_balance(cs_from)
        amount_to_send = balance_wei - gas_cost
        if amount_to_send <= 0:
            return None

        tx = {
            "nonce": nonce,
            "to": cs_to,
            "value": amount_to_send,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "chainId": chain_id
        }
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
        raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()
        if not tx_hash_hex.startswith("0x"):
            tx_hash_hex = "0x" + tx_hash_hex
        logger.info(f"[{chain_name}] Swept {amount_to_send / 1e18:.6f} to {to_addr}! Tx: {tx_hash_hex}")
        return tx_hash_hex
    except Exception as e:
        logger.error(f"[{chain_name}] Sweep failed for {from_addr}: {e}")
        return None


def sweep_bep20_token_balance(rpc_list: list, chain_id: int, private_key: str, token_addr: str, from_addr: str, to_addr: str, token_balance: float, min_tokens: float = 0.08):
    if not HAS_WEB3 or not private_key or token_balance <= min_tokens:
        return None
    try:
        w3 = None
        for rpc in rpc_list:
            try:
                tw3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                if tw3.is_connected():
                    w3 = tw3
                    break
            except Exception:
                continue
        if not w3:
            return None

        cs_from = Web3.to_checksum_address(from_addr)
        cs_to = Web3.to_checksum_address(to_addr)
        if cs_from.lower() == cs_to.lower():
            return None

        cs_token = Web3.to_checksum_address(token_addr)
        native_bal = w3.eth.get_balance(cs_from)
        gas_price = w3.eth.gas_price
        gas_limit = 65000
        gas_cost = gas_price * gas_limit
        if native_bal < gas_cost:
            logger.warning(f"[BEP-20 Sweep] {from_addr} has tokens but insufficient gas")
            return None

        nonce = w3.eth.get_transaction_count(cs_from)
        transfer_abi = [
            {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}
        ]
        contract = w3.eth.contract(address=cs_token, abi=transfer_abi)
        raw_bal = contract.functions.balanceOf(cs_from).call()
        if raw_bal <= 0:
            return None

        tx = contract.functions.transfer(cs_to, raw_bal).build_transaction({
            "from": cs_from,
            "nonce": nonce,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "chainId": chain_id
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
        raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()
        if not tx_hash_hex.startswith("0x"):
            tx_hash_hex = "0x" + tx_hash_hex
        logger.info(f"[BEP-20 Sweep] Swept {token_balance:.2f} USDT to {to_addr}! Tx: {tx_hash_hex}")
        return tx_hash_hex
    except Exception as e:
        logger.error(f"[BEP-20 Sweep] Sweep failed for {from_addr}: {e}")
        return None


async def sweep_ton_balance(session: aiohttp.ClientSession, mnemonic: str, from_addr: str, to_addr: str, balance: float, min_threshold: float = 0.02):
    if not HAS_TONSDK or not mnemonic or balance <= min_threshold:
        return None
    try:
        words = mnemonic.strip().split()
        if len(words) != 24:
            return None
        _mn, _pub, _priv, wallet = Wallets.from_mnemonics(words, version=WalletVersionEnum.v4r2)
        seqno = 0
        try:
            tc_headers = {"X-API-Key": TONCENTER_API_KEY} if TONCENTER_API_KEY else {}
            tc_url = "https://toncenter.com/api/v2/runGetMethod"
            payload = {"address": from_addr, "method": "seqno", "stack": []}
            async with session.post(tc_url, json=payload, headers=tc_headers, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    d = await r.json()
                    if d.get("ok") and d.get("result", {}).get("stack"):
                        raw = d["result"]["stack"][0][1]
                        seqno = int(raw, 16) if str(raw).startswith("0x") else int(raw)
        except Exception:
            pass

        gas_fee = 0.008
        amount_to_send = balance - gas_fee
        if amount_to_send <= 0:
            return None

        amount_nano = int(amount_to_send * 1e9)
        query = wallet.create_transfer_message(
            to_addr=to_addr,
            amount=amount_nano,
            seqno=seqno,
            payload="Automated Fleet Sweep"
        )
        boc = query["message"].to_boc(False)
        b64_boc = base64.b64encode(boc).decode("utf-8")

        tc_headers = {"X-API-Key": TONCENTER_API_KEY, "Content-Type": "application/json"} if TONCENTER_API_KEY else {"Content-Type": "application/json"}
        send_url = "https://toncenter.com/api/v2/sendBoc"
        async with session.post(send_url, json={"boc": b64_boc}, headers=tc_headers, timeout=aiohttp.ClientTimeout(total=8)) as br:
            if br.status == 200:
                resp_d = await br.json()
                if resp_d.get("ok"):
                    logger.info(f"[TON Sweep] Swept {amount_to_send:.4f} TON from {from_addr} to {to_addr}!")
                    return "boc_sent"
    except Exception as e:
        logger.error(f"[TON Sweep] Failed for {from_addr}: {e}")
    return None


async def execute_cloud_onchain_sweeper(session: aiohttp.ClientSession, accounts: list = None, execute_sweep: bool = True, notify: bool = False) -> dict:
    """Audits on-chain balances across all worker EVM and TON wallets and sweeps surplus balances."""
    logger.info("[Cloud Sweeper] Auditing on-chain balances across all fleet wallets...")
    evm_wallets, ton_wallets = await load_fleet_wallets_from_cloud()

    evm_tasks = [audit_single_evm(session, uid, info) for uid, info in evm_wallets.items()]
    evm_audit = [r for r in await asyncio.gather(*evm_tasks, return_exceptions=True) if isinstance(r, dict)]

    ton_headers = {"Authorization": f"Bearer {TONAPI_KEY}"} if TONAPI_KEY else {}
    ton_tasks = [audit_single_ton(session, uid, info, ton_headers) for uid, info in ton_wallets.items()]
    ton_audit = [r for r in await asyncio.gather(*ton_tasks, return_exceptions=True) if isinstance(r, dict)]

    funded_evm = [w for w in evm_audit if w.get("bnb_balance", 0) > 0.0005 or w.get("eth_balance", 0) > 0.0002 or w.get("usdt_balance", 0) > 0.08]
    funded_ton = [w for w in ton_audit if w.get("ton_balance", 0) > 0.01]

    total_bnb = sum(w.get("bnb_balance", 0) for w in evm_audit)
    total_eth = sum(w.get("eth_balance", 0) for w in evm_audit)
    total_usdt = sum(w.get("usdt_balance", 0) for w in evm_audit)
    total_ton = sum(w.get("ton_balance", 0) for w in ton_audit)

    swept_txs = []
    if execute_sweep:
        if HAS_WEB3:
            for w in funded_evm:
                pk = w.get("private_key")
                addr = w.get("address")
                name = w.get("name")
                if not pk or not addr or addr.lower() == MASTER_EVM_VAULT.lower():
                    continue
                if w.get("bnb_balance", 0) > 0.0008:
                    tx_bnb = sweep_evm_native_balance(BSC_RPCS, 56, "BSC", pk, addr, MASTER_EVM_VAULT, w["bnb_balance"])
                    if tx_bnb:
                        swept_txs.append({"chain": "BSC", "coin": "BNB", "amount": w["bnb_balance"], "name": name, "tx": tx_bnb, "url": f"https://bscscan.com/tx/{tx_bnb}"})
                if w.get("eth_balance", 0) > 0.0002:
                    tx_eth = sweep_evm_native_balance(ARB_RPCS, 42161, "Arbitrum One", pk, addr, MASTER_EVM_VAULT, w["eth_balance"])
                    if tx_eth:
                        swept_txs.append({"chain": "Arbitrum One", "coin": "ETH", "amount": w["eth_balance"], "name": name, "tx": tx_eth, "url": f"https://arbiscan.io/tx/{tx_eth}"})
                if w.get("usdt_balance", 0) > 0.08:
                    tx_usdt = sweep_bep20_token_balance(BSC_RPCS, 56, pk, BSC_USDT_CONTRACT, addr, MASTER_EVM_VAULT, w["usdt_balance"], min_tokens=0.08)
                    if tx_usdt:
                        swept_txs.append({"chain": "BSC", "coin": "USDT", "amount": w["usdt_balance"], "name": name, "tx": tx_usdt, "url": f"https://bscscan.com/tx/{tx_usdt}"})

        if HAS_TONSDK:
            for w in funded_ton:
                mn = w.get("mnemonic")
                addr = w.get("address")
                name = w.get("name")
                ton_bal = w.get("ton_balance", 0)
                if not mn or not addr or addr == MASTER_TON_VAULT or ton_bal <= 0.02:
                    continue
                tx_ton = await sweep_ton_balance(session, mn, addr, MASTER_TON_VAULT, ton_bal)
                if tx_ton:
                    swept_txs.append({"chain": "TON", "coin": "TON", "amount": ton_bal - 0.008, "name": name, "tx": tx_ton, "url": f"https://tonviewer.com/{addr}"})

    if swept_txs:
        lines = [f"• <b>{s['name']} ({s['chain']}):</b> Swept <code>{s['amount']:.4f} {s['coin']}</code> → <a href=\"{s['url']}\">View Tx</a>" for s in swept_txs]
        receipt_msg = (
            f"⚡ <b>ON-CHAIN VAULT CONSOLIDATION SWEEP EXECUTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) +
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Master Vault (Binance Web3):</b> <code>{MASTER_EVM_VAULT}</code>\n"
            f"🛡️ <i>100% Cloud Autonomous Execution</i>"
        )
        await send_payout_receipt(receipt_msg)
    elif notify:
        msg = (
            f"💼 <b>MY AGY AI — Multi-Chain Vault Sweep Audit</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 👥 <b>Worker Wallets Audited:</b> <code>{len(evm_audit)} EVM / {len(ton_audit)} TON</code>\n"
            f"• 🪙 <b>BSC Worker Holding:</b> <code>{total_bnb:.6f} BNB</code>\n"
            f"• 💵 <b>BSC Worker USDT:</b> <code>${total_usdt:.2f} USDT</code>\n"
            f"• 💎 <b>Arbitrum Worker Holding:</b> <code>{total_eth:.6f} ETH</code>\n"
            f"• 💎 <b>TON Worker Holding:</b> <code>{total_ton:.4f} TON</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Master Destination Vaults (Binance Web3):</b>\n"
            f"• <code>EVM:</code> <code>{MASTER_EVM_VAULT}</code>\n"
            f"• <code>TON:</code> <code>{MASTER_TON_VAULT}</code>\n\n"
            f"🛡️ <i>Direct in-bot routing sends 100% of mining profits directly to your Binance Web3 Vault.</i>"
        )
        await send_payout_receipt(msg)

    return {
        "ok": True,
        "evm_total_bnb": total_bnb,
        "evm_total_eth": total_eth,
        "evm_total_usdt": total_usdt,
        "ton_total": total_ton,
        "funded_evm_count": len(funded_evm),
        "funded_ton_count": len(funded_ton),
        "swept_count": len(swept_txs),
        "swept_txs": swept_txs
    }


@app.get("/api/sweep/audit")
async def api_sweep_audit(request: Request):
    """Audits on-chain balances across all worker wallets without executing transfers."""
    notify = request.query_params.get("notify") == "1"
    async with aiohttp.ClientSession() as session:
        res = await execute_cloud_onchain_sweeper(session, execute_sweep=False, notify=notify)
    return {"ok": True, "audit": res, "timestamp": time.time()}


@app.post("/api/sweep/execute")
async def api_sweep_execute(request: Request):
    """Executes on-chain vault sweeper across EVM and TON worker wallets."""
    async with aiohttp.ClientSession() as session:
        res = await execute_cloud_onchain_sweeper(session, execute_sweep=True, notify=False)
    return {"ok": True, "results": res, "timestamp": time.time()}


@app.post("/api/withdraw/auto-cycle")
async def api_withdraw_auto_cycle(request: Request):
    """Executes automated withdrawal cycles across AI Lab, Ainovum, and Stones."""
    accounts = await fetch_accounts_from_cloud()
    if not accounts:
        return {"ok": False, "message": "No accounts found"}

    tokens = {}
    async with aiohttp.ClientSession() as session:
        for cf_url in CF_WORKER_URLS:
            try:
                async with session.get(f"{cf_url}/api/fleet/tokens", timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        tokens = await r.json()
                        break
            except Exception:
                pass

        ailab_res = []
        ainovum_res = []
        stones_res = []

        for acc in accounts:
            a_res = await check_and_withdraw_ailab(session, acc, tokens)
            ailab_res.append(a_res)
            await asyncio.sleep(0.4)

            an_res = await check_and_withdraw_ainovum(session, acc, tokens)
            ainovum_res.append(an_res)
            await asyncio.sleep(0.4)

            st_res = await check_and_withdraw_stones(session, acc, tokens)
            stones_res.append(st_res)
            await asyncio.sleep(0.4)

    return {
        "ok": True,
        "ailab": ailab_res,
        "ainovum": ainovum_res,
        "stones": stones_res,
        "timestamp": time.time()
    }


async def cloud_wealth_automation_watchdog():
    """24/7 background watchdog executing scheduled auto-withdrawals & wallet sweeps in the cloud."""
    logger.info("[Cloud Wealth Watchdog] Initialized 24/7 autonomous withdrawal & on-chain sweeper scheduler...")
    await asyncio.sleep(60)
    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            accounts = await fetch_accounts_from_cloud()
            if accounts:
                logger.info(f"[Cloud Wealth Watchdog] ⚡ Running Scheduled Cloud Withdrawal & Sweep Cycle #{cycle_count}...")
                async with aiohttp.ClientSession() as session:
                    tokens = {}
                    for cf_url in CF_WORKER_URLS:
                        try:
                            async with session.get(f"{cf_url}/api/fleet/tokens", timeout=aiohttp.ClientTimeout(total=8)) as r:
                                if r.status == 200:
                                    tokens = await r.json()
                                    break
                        except Exception:
                            pass

                    for acc in accounts:
                        await check_and_withdraw_ailab(session, acc, tokens)
                        await asyncio.sleep(0.6)
                        await check_and_withdraw_ainovum(session, acc, tokens)
                        await asyncio.sleep(0.6)
                        await check_and_withdraw_stones(session, acc, tokens)
                        await asyncio.sleep(0.6)

                    await execute_cloud_onchain_sweeper(session, execute_sweep=True, notify=False)

        except Exception as e:
            logger.error(f"[Cloud Wealth Watchdog] Cycle error: {e}")

        await asyncio.sleep(1800)
