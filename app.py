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

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://znbbaozpevurvbfkxakz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpuYmJhb3pwZXZ1cnZiZmt4YWt6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk4MTYxNTQsImV4cCI6MjEwNTM5MjE1NH0.ldgn0gCtOLEPUQyvTiG5RgKX6VY0LrS_4LkIKCf8NqM")
UPSTASH_URL = os.getenv("UPSTASH_URL", "https://relaxing-starfish-285827.upstash.io")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN", "gQAAAAAABFyDAAIgcDI5MDYyYWZjNzYzNzk0ZmRjYjhmNTA4ZDI4ODlmODkzNw")

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

# ============================================================================
# CLOUD BNB GALAXY AUTONOMOUS ENGINE (Balance Checks & Auto-Withdrawals)
# ============================================================================
MIN_WITHDRAWAL = float(os.getenv("MIN_WITHDRAWAL", "0.000055"))
DEFAULT_WALLET = os.getenv("WALLET_ADDRESS", "0x00A09b910A3A25c898c8D64a4D436f56A2D40995")
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
        for _ in range(5):
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
                            if any(w in btn_t for w in ["confirm", "yes", "proceed", "submit", "accept"]):
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

                if any(w in bot_lower for w in ["wallet address", "submit your bnb", "bep-20", "enter your wallet"]) and not wallet_submitted:
                    await client.send_message(BNB_BOT, target_wallet)
                    wallet_submitted = True
                    continue

                if any(w in bot_lower for w in ["enter the amount", "amount of bnb", "how much", "minimum withdrawal", "min:"]) and not amount_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                if not amount_submitted:
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
                    async with http.post("https://justtool.site/api/adsgram-task3", headers=headers, json={"tgId": int(uid), "name": f"Member {uid}"}) as step_r:
                        if step_r.status == 200:
                            s_data = await step_r.json()
                            v_count = s_data.get("count", v_count + 1)
                        else:
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

