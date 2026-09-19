import os
import aiohttp
from fastapi import FastAPI

app = FastAPI(title="MY AGY AI Standby Cloud Node")

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0xfda4182001672b9f0f09e2118242e543e35ed5ce")
CF_PRIMARY = os.getenv("CF_PRIMARY", "https://restore-agy.aaaai2.workers.dev")
CF_SECONDARY = os.getenv("CF_SECONDARY", "https://restore-agy.aaa-bot.workers.dev")

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "MY AGY AI Standby Cloud Node",
        "provider": "Render Cloud (Free Tier)",
        "role": "High-Availability Failover & BEP-20 Watcher"
    }

@app.get("/health")
async def health():
    return {"ok": True, "status": "healthy"}

@app.get("/bep20/check")
async def check_bep20():
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [WALLET_ADDRESS, "latest"],
        "id": 1
    }
    async with aiohttp.ClientSession() as session:
        for rpc in ["https://bsc-dataseed.binance.org", "https://binance.llamarpc.com"]:
            try:
                async with session.post(rpc, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        wei = int(d["result"], 16)
                        return {"ok": True, "wallet": WALLET_ADDRESS, "balance_bnb": wei / 1e18}
            except Exception:
                continue
    return {"ok": False, "error": "RPC unavailable"}

@app.get("/edge/ping")
async def ping_edge():
    res = {}
    async with aiohttp.ClientSession() as session:
        for name, url in [("primary", CF_PRIMARY), ("secondary", CF_SECONDARY)]:
            try:
                async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=4)) as r:
                    res[name] = {"status": r.status, "ok": r.status == 200}
            except Exception as e:
                res[name] = {"error": str(e)}
    return {"edge_nodes": res}
