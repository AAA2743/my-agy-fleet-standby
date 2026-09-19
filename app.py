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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RenderSessionCollector")

app = FastAPI(title="MY AGY AI — Standby Batch Session Link Collector")

SECRET_KEY = os.getenv("SECRET_KEY", "agy_cf_secret_7d36994e_2026")
API_ID = int(os.getenv("TELEGRAM_API_ID", "23788736"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "8098c495e2820d82935041ff91176b65")
REPORT_CHAT_ID = os.getenv("REPORT_CHAT_ID", "6727787768")

CF_WORKER_URLS = [
    "https://restore-agy.aaaai2.workers.dev",
    "https://restore-agy.aaa-bot.workers.dev",
    "https://restore-agy.aaa222.workers.dev"
]

STONES_BOT = "stoneswithestand_bot"
MRG_BOT = "mrgminerbot"
MRG_REFERRAL_CODE = "ref_IRN1G3XD"
ART_BOT = "ART_AIRDROP_BOT"
BNB_BOT = "CryptoProUpRobot"

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
                            timeout=aiohttp.ClientTimeout(total=6)
                        )
                    except Exception as se:
                        logger.warning(f"Sync error to {cf_url}: {se}")

    # Trigger Cloudflare Edge Autonomous Cloud Farming
    async with aiohttp.ClientSession() as http:
        for idx, cf_url in enumerate(CF_WORKER_URLS):
            try:
                await http.post(
                    f"{cf_url}/api/farm/bnb",
                    json={},
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
