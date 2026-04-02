"""
Multi-Symbol Indicator Subset Backtest — OKX + CoinAnk Edition

Data Sources:
  - Klines:     OKX (history-candles)
  - L/S Ratio:  OKX (rubik stat)
  - OI:         OKX (rubik stat)
  - FR:         OKX (funding-rate-history)
  - Liquidation: CoinAnk
  - OI/MC:      CoinAnk
  - FNG:        alternative.me

Symbols: BTC, ETH, SOL
Periods: 90, 60, 30 days
Groups:  A-G (7 indicator subsets)

Usage: python -m backend.trading.indicator_subset_backtest_v2
"""
import asyncio
import json
import os
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from loguru import logger

# Reuse scoring functions from v1
from backend.trading.indicator_subset_backtest import (
    score_group_a, score_group_b, score_group_c,
    score_group_d, score_group_e, simulate_trades,
)
from backend.trading.backtester_v2 import _SortedLookup

import httpx

COINANK_KEY = "e643ebc71b624355a863c688235a87a6"


# ============================================================
# OKX Data Fetcher
# ============================================================

class OKXDataFetcher:
    """Fetch historical data from OKX + CoinAnk"""

    OKX_BASE = "https://www.okx.com"

    SYMBOL_MAP = {
        "BTCUSDT": {"okx": "BTC-USDT-SWAP", "ccy": "BTC", "coinank": "BTC"},
        "ETHUSDT": {"okx": "ETH-USDT-SWAP", "ccy": "ETH", "coinank": "ETH"},
        "SOLUSDT": {"okx": "SOL-USDT-SWAP", "ccy": "SOL", "coinank": "SOL"},
    }

    async def _get(self, client, url, params=None, headers=None, retries=3):
        for attempt in range(retries):
            try:
                resp = await client.get(url, params=params, headers=headers)
                return resp
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    async def fetch_klines(self, symbol: str, start: datetime, end: datetime) -> List[Dict]:
        """OKX history-candles — paginated, newest first"""
        inst = self.SYMBOL_MAP[symbol]["okx"]
        all_klines = []
        end_ms = int(end.timestamp() * 1000)
        start_ms = int(start.timestamp() * 1000)

        async with httpx.AsyncClient(timeout=30.0) as client:
            after = str(end_ms)
            while True:
                resp = await self._get(client, f"{self.OKX_BASE}/api/v5/market/history-candles",
                    params={"instId": inst, "bar": "1H", "after": after, "limit": "100"})
                if resp.status_code != 200:
                    break
                data = resp.json().get("data", [])
                if not data:
                    break
                for k in data:
                    ts = int(k[0])
                    if ts < start_ms:
                        continue
                    all_klines.append({
                        "ts": ts, "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                    })
                oldest_ts = int(data[-1][0])
                if oldest_ts <= start_ms:
                    break
                after = str(oldest_ts)
                await asyncio.sleep(0.2)

        all_klines.sort(key=lambda x: x["ts"])
        logger.info(f"  OKX K线: {len(all_klines)} 条 ({symbol})")
        return all_klines

    async def fetch_funding_rate(self, symbol: str, start: datetime, end: datetime) -> Dict[int, float]:
        """OKX funding rate history"""
        inst = self.SYMBOL_MAP[symbol]["okx"]
        result = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            after = ""
            for _ in range(20):  # max pages
                params = {"instId": inst, "limit": "100"}
                if after:
                    params["after"] = after
                resp = await self._get(client, f"{self.OKX_BASE}/api/v5/public/funding-rate-history", params=params)
                if resp.status_code != 200:
                    break
                data = resp.json().get("data", [])
                if not data:
                    break
                for d in data:
                    ts = int(d["fundingTime"])
                    if ts < int(start.timestamp() * 1000):
                        break
                    result[ts] = float(d["fundingRate"]) * 100
                oldest = int(data[-1]["fundingTime"])
                if oldest < int(start.timestamp() * 1000):
                    break
                after = data[-1]["fundingTime"]
                await asyncio.sleep(0.2)
        logger.info(f"  OKX FR: {len(result)} 条")
        return result

    async def fetch_ls_ratio(self, symbol: str) -> Dict[int, float]:
        """OKX L/S ratio — returns up to 720 1H candles (30 days)"""
        ccy = self.SYMBOL_MAP[symbol]["ccy"]
        result = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await self._get(client, f"{self.OKX_BASE}/api/v5/rubik/stat/contracts/long-short-account-ratio",
                params={"ccy": ccy, "period": "1H"})
            if resp.status_code == 200:
                for item in resp.json().get("data", []):
                    ts = int(item[0])
                    ratio = float(item[1])
                    result[ts] = ratio
        logger.info(f"  OKX L/S: {len(result)} 条")
        return result

    async def fetch_oi(self, symbol: str) -> Dict[int, float]:
        """OKX OI+Volume — returns up to 720 1H candles"""
        ccy = self.SYMBOL_MAP[symbol]["ccy"]
        result = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await self._get(client, f"{self.OKX_BASE}/api/v5/rubik/stat/contracts/open-interest-volume",
                params={"ccy": ccy, "period": "1H"})
            if resp.status_code == 200:
                for item in resp.json().get("data", []):
                    ts = int(item[0])
                    oi = float(item[1])
                    result[ts] = oi
        logger.info(f"  OKX OI: {len(result)} 条")
        return result

    async def fetch_coinank_liq(self, symbol: str, end: datetime) -> Dict[int, Dict]:
        """CoinAnk liquidation history"""
        base = self.SYMBOL_MAP[symbol]["coinank"]
        result = {}
        end_ms = int(end.timestamp() * 1000)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await self._get(client,
                    "https://open-api.coinank.com/api/liquidation/aggregated-history",
                    params={"baseCoin": base, "interval": "1h", "endTime": end_ms, "size": 500},
                    headers={"apikey": COINANK_KEY})
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("data"):
                        for item in data["data"]:
                            ts = item.get("ts", 0)
                            all_data = item.get("all", {})
                            result[ts] = {
                                "longTurnover": all_data.get("longTurnover", 0),
                                "shortTurnover": all_data.get("shortTurnover", 0),
                            }
        except Exception as e:
            logger.warning(f"  CoinAnk liq error: {e}")
        logger.info(f"  CoinAnk Liq: {len(result)} 条")
        return result

    async def fetch_coinank_oi_mc(self, symbol: str, end: datetime) -> Dict[int, float]:
        """CoinAnk OI/Market Cap ratio"""
        base = self.SYMBOL_MAP[symbol]["coinank"]
        result = {}
        end_ms = int(end.timestamp() * 1000)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await self._get(client,
                    "https://open-api.coinank.com/api/instruments/oiVsMc",
                    params={"baseCoin": base, "endTime": end_ms, "size": 500, "interval": "1h"},
                    headers={"apikey": COINANK_KEY})
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("data"):
                        for item in data["data"]:
                            ts = item.get("ts", item.get("createTime", 0))
                            oi = item.get("openInterest", 0)
                            mc = item.get("marketCap", 1)
                            if mc > 0:
                                result[ts] = round(oi / mc * 100, 4)
        except Exception as e:
            logger.warning(f"  CoinAnk OI/MC error: {e}")
        logger.info(f"  CoinAnk OI/MC: {len(result)} 条")
        return result

    async def fetch_fng(self, days: int) -> Dict[int, int]:
        """Fear & Greed Index"""
        result = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"https://api.alternative.me/fng/?limit={days+10}&format=json")
                if r.status_code == 200:
                    for item in r.json().get("data", []):
                        ts_day = int(item["timestamp"]) * 1000 // 86400000
                        result[ts_day] = int(item["value"])
        except Exception as e:
            logger.warning(f"  FNG error: {e}")
        logger.info(f"  FNG: {len(result)} 条")
        return result

    async def fetch_all(self, symbol: str, start: datetime, end: datetime, days: int) -> Dict:
        """Fetch all data in parallel"""
        logger.info(f"📥 拉取 {symbol} (OKX+CoinAnk): {start.strftime('%m-%d')} → {end.strftime('%m-%d')}")

        # Need extra lookback for moving averages
        lookback_start = start - timedelta(days=10)

        klines, fr, ls, oi, ca_liq, ca_oi_mc, fng = await asyncio.gather(
            self.fetch_klines(symbol, lookback_start, end),
            self.fetch_funding_rate(symbol, start, end),
            self.fetch_ls_ratio(symbol),
            self.fetch_oi(symbol),
            self.fetch_coinank_liq(symbol, end),
            self.fetch_coinank_oi_mc(symbol, end),
            self.fetch_fng(days),
        )

        return {
            "klines": klines,
            "funding_rates": fr,
            "long_short_ratios": ls,
            "oi_history": oi,
            "coinank_liq": ca_liq,
            "coinank_oi_mc": ca_oi_mc,
            "fng_history": fng,
        }


# ============================================================
# Main Runner
# ============================================================

GROUPS = [
    ("A: Pure Trend", score_group_a, 60),
    ("B: Trend+Momentum", score_group_b, 60),
    ("C: Trend+SMC", score_group_c, 60),
    ("D: Trend+Sentiment", score_group_d, 60),
    ("E: Full@60", score_group_e, 60),
    ("F: Full@65", score_group_e, 65),
    ("G: Full@70", score_group_e, 70),
]

async def run_single(symbol: str, days: int, fetcher: OKXDataFetcher) -> List[Dict]:
    """Run all 7 groups for one symbol/period"""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp() * 1000)

    data = await fetcher.fetch_all(symbol, start, end, days)
    klines = data["klines"]

    if len(klines) < 100:
        logger.error(f"K线不足: {len(klines)} for {symbol} {days}d")
        return []

    logger.info(f"  数据: {len(klines)} K线, {len(data['funding_rates'])} FR, "
                f"{len(data['long_short_ratios'])} LS, {len(data['oi_history'])} OI")

    results = []
    for label, score_fn, threshold in GROUPS:
        r = simulate_trades(klines, score_fn, data, start_ms,
                           score_threshold=threshold, label=label)
        results.append(r)
        logger.info(f"    {label}: {r['trades']}T {r['win_rate']}%WR "
                    f"${r['total_pnl']:+.0f} PF={r['profit_factor']:.2f}")

    return results


async def run_all():
    """Run all symbols × periods"""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    periods = [90, 60, 30]
    fetcher = OKXDataFetcher()

    all_results = {}

    for symbol in symbols:
        all_results[symbol] = {}
        for days in periods:
            logger.info(f"\n{'='*60}")
            logger.info(f"🔬 {symbol} — {days}天回测 (OKX+CoinAnk)")
            logger.info(f"{'='*60}")

            results = await run_single(symbol, days, fetcher)
            all_results[symbol][str(days)] = results

            # Respect rate limits
            await asyncio.sleep(1)

    # Print comparison table
    lines = []
    lines.append("=" * 120)
    lines.append("MULTI-SYMBOL INDICATOR SUBSET BACKTEST RESULTS (OKX + CoinAnk Data)")
    lines.append("=" * 120)

    for symbol in symbols:
        lines.append(f"\n{'='*80}")
        lines.append(f"  {symbol}")
        lines.append(f"{'='*80}")

        for days in periods:
            results = all_results[symbol].get(str(days), [])
            if not results:
                lines.append(f"\n  [{days}d] No data")
                continue

            lines.append(f"\n  [{days}d]")
            lines.append(f"  {'Group':<22} {'T':>4} {'WR%':>6} {'PnL$':>10} {'PnL%':>7} {'PF':>6} {'DD%':>6}")
            lines.append(f"  {'-'*70}")
            for r in results:
                lines.append(f"  {r['label']:<22} {r['trades']:>4} {r['win_rate']:>5.1f}% "
                           f"{r['total_pnl']:>+9.0f} {r['total_pnl_pct']:>+6.1f}% "
                           f"{r['profit_factor']:>5.2f} {r['max_drawdown_pct']:>5.1f}%")

    # Best per symbol
    lines.append(f"\n{'='*80}")
    lines.append("BEST GROUP PER SYMBOL × PERIOD (by PnL)")
    lines.append(f"{'='*80}")
    for symbol in symbols:
        for days in periods:
            results = all_results[symbol].get(str(days), [])
            if results:
                best = max(results, key=lambda x: x["total_pnl"])
                lines.append(f"  {symbol} {days}d: {best['label']} → "
                           f"${best['total_pnl']:+.0f} ({best['win_rate']:.1f}% WR, PF={best['profit_factor']:.2f})")

    # Cross-symbol best group
    lines.append(f"\n{'='*80}")
    lines.append("CROSS-SYMBOL GROUP RANKING (avg PnL% across all symbols × periods)")
    lines.append(f"{'='*80}")
    group_totals = {}
    for g_label, _, _ in GROUPS:
        pnl_pcts = []
        for symbol in symbols:
            for days in periods:
                results = all_results[symbol].get(str(days), [])
                for r in results:
                    if r["label"] == g_label:
                        pnl_pcts.append(r["total_pnl_pct"])
        if pnl_pcts:
            group_totals[g_label] = sum(pnl_pcts) / len(pnl_pcts)
    for label, avg_pnl in sorted(group_totals.items(), key=lambda x: -x[1]):
        lines.append(f"  {label:<22} avg PnL%: {avg_pnl:>+6.2f}%")

    report = "\n".join(lines)
    print(report)

    # Save
    os.makedirs("data", exist_ok=True)
    save_data = {
        "timestamp": datetime.now().isoformat(),
        "data_source": "OKX + CoinAnk",
        "symbols": symbols,
        "periods": periods,
        "results": {},
    }
    for symbol in symbols:
        save_data["results"][symbol] = {}
        for days in periods:
            results = all_results[symbol].get(str(days), [])
            save_data["results"][symbol][str(days)] = [
                {k: v for k, v in r.items() if k != "trade_details"} for r in results
            ]

    with open("data/backtest_multi_symbol_okx.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

    with open("data/backtest_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"\n💾 Results: data/backtest_multi_symbol_okx.json")
    logger.info(f"💾 Report:  data/backtest_report.txt")


if __name__ == "__main__":
    asyncio.run(run_all())
