"""
Backtester V2 — 专业回测引擎
复用 quick_analyze 真实 15 层评分逻辑的离线版
支持: 历史 K线 + FR + L/S + OI 数据注入

Usage:
    python -m backend.trading.backtester_v2
"""
import asyncio
import math
import httpx
import json
import bisect
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from loguru import logger

# Pre-import heavy modules once
try:
    from backend.analysis.smart_money import analyze_smc as _analyze_smc
except Exception:
    _analyze_smc = None
try:
    from backend.analysis.signal_matrix import evaluate_signal_conflicts as _eval_conflicts
except Exception:
    _eval_conflicts = None
try:
    from backend.analysis.ls_analyzer import LSAnalyzer as _LSAnalyzer
except Exception:
    _LSAnalyzer = None
try:
    from backend.trading.reflection_engine import ReflectionEngine
    _evo_engine = ReflectionEngine()
except Exception:
    _evo_engine = None


# ============================================================
# Helper functions (same as quick_analyze)
# ============================================================

def calc_ema(values: list, period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 20.0
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(-period, 0):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    atr = sum(tr_list) / period
    if atr == 0:
        return 20.0
    plus_di = sum(plus_dm) / period / atr * 100
    minus_di = sum(minus_dm) / period / atr * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return round(dx, 1)


def trend_direction(prices: list, ema_short: int = 20, ema_long: int = 50) -> int:
    if len(prices) < ema_long:
        return 0
    ema_s = calc_ema(prices, ema_short)
    ema_l = calc_ema(prices, ema_long)
    if ema_s > ema_l * 1.001:
        return 1
    elif ema_s < ema_l * 0.999:
        return -1
    return 0


# ============================================================
# Historical Data Fetcher
# ============================================================

class HistoricalDataFetcher:
    """从 Binance Futures 拉取历史 K线 + FR + L/S + OI（含重试）"""

    BASE = "https://fapi.binance.com"
    COINANK_BASE = "https://open-api.coinank.com"
    COINANK_KEY = "e643ebc71b624355a863c688235a87a6"

    async def _get_with_retry(self, client, url, params=None, retries=3, headers=None):
        """带重试的GET请求(支持自定义headers)"""
        for attempt in range(retries):
            try:
                resp = await client.get(url, params=params, headers=headers)
                return resp
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"  网络错误 {e.__class__.__name__}, {wait}s后重试 ({attempt+1}/{retries})")
                    await asyncio.sleep(wait)
                else:
                    raise

    async def fetch_klines(self, symbol: str, interval: str, start: datetime, end: datetime) -> List[Dict]:
        all_klines = []
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        async with httpx.AsyncClient(timeout=30.0) as client:
            current = start_ms
            while current < end_ms:
                resp = await self._get_with_retry(client, f"{self.BASE}/fapi/v1/klines", {
                    "symbol": symbol, "interval": interval,
                    "startTime": current, "limit": 1000,
                })
                if resp.status_code != 200:
                    break
                data = resp.json()
                if not data:
                    break
                for k in data:
                    all_klines.append({
                        "ts": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                    })
                current = int(data[-1][0]) + 1
                await asyncio.sleep(0.15)
        logger.info(f"  K线: {len(all_klines)} 条 ({symbol} {interval})")
        return all_klines

    async def fetch_funding_rate(self, symbol: str, start: datetime, end: datetime) -> Dict[int, float]:
        result = {}
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                current = start_ms
                while current < end_ms:
                    resp = await self._get_with_retry(client, f"{self.BASE}/fapi/v1/fundingRate", {
                        "symbol": symbol, "startTime": current, "limit": 1000,
                    })
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data:
                        break
                    for d in data:
                        result[int(d["fundingTime"])] = float(d["fundingRate"]) * 100
                    current = int(data[-1]["fundingTime"]) + 1
                    await asyncio.sleep(0.15)
        except Exception as e:
            logger.warning(f"  资金费率获取失败: {e}")
        logger.info(f"  资金费率: {len(result)} 条")
        return result

    async def fetch_long_short_ratio(self, symbol: str, start: datetime, end: datetime) -> Dict[int, float]:
        result = {}
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                current = start_ms
                while current < end_ms:
                    resp = await self._get_with_retry(client, f"{self.BASE}/futures/data/globalLongShortAccountRatio", {
                        "symbol": symbol, "period": "1h",
                        "startTime": current, "limit": 500,
                    })
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data:
                        break
                    for d in data:
                        result[int(d["timestamp"])] = float(d["longShortRatio"])
                    current = int(data[-1]["timestamp"]) + 1
                    await asyncio.sleep(0.15)
        except Exception as e:
            logger.warning(f"  多空比获取失败: {e}")
        logger.info(f"  多空比: {len(result)} 条")
        return result

    async def fetch_oi_history(self, symbol: str, start: datetime, end: datetime) -> Dict[int, float]:
        result = {}
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                current = start_ms
                while current < end_ms:
                    resp = await self._get_with_retry(client, f"{self.BASE}/futures/data/openInterestHist", {
                        "symbol": symbol, "period": "1h",
                        "startTime": current, "limit": 500,
                    })
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data:
                        break
                    for d in data:
                        result[int(d["timestamp"])] = float(d["sumOpenInterest"])
                    current = int(data[-1]["timestamp"]) + 1
                    await asyncio.sleep(0.15)
        except Exception as e:
            logger.warning(f"  OI获取失败: {e}")
        logger.info(f"  OI: {len(result)} 条")
        return result

    # === V5: CoinAnk Data Fetchers ===

    def _base_coin(self, symbol: str) -> str:
        """BTCUSDT -> BTC, ETHUSDT -> ETH, SOLUSDT -> SOL"""
        return symbol.replace("USDT", "").replace("BUSD", "")

    async def fetch_coinank_liq_history(self, symbol: str, start: datetime, end: datetime) -> Dict[int, Dict]:
        """CoinAnk 聚合爆仓历史 -> {ts: {longTurnover, shortTurnover}}"""
        result = {}
        base = self._base_coin(symbol)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                end_ms = int(end.timestamp() * 1000)
                resp = await self._get_with_retry(
                    client,
                    f"{self.COINANK_BASE}/api/liquidation/aggregated-history",
                    {"baseCoin": base, "interval": "1h", "endTime": end_ms, "size": 500},
                    headers={"apikey": self.COINANK_KEY},
                )
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
            logger.warning(f"  CoinAnk爆仓历史获取失败: {e}")
        logger.info(f"  CoinAnk爆仓历史: {len(result)} 条")
        return result

    async def fetch_coinank_oi_mc(self, symbol: str, start: datetime, end: datetime) -> Dict[int, float]:
        """CoinAnk OI/市值比历史 -> {ts: oi_mc_ratio}"""
        result = {}
        base = self._base_coin(symbol)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                end_ms = int(end.timestamp() * 1000)
                resp = await self._get_with_retry(
                    client,
                    f"{self.COINANK_BASE}/api/instruments/oiVsMc",
                    {"baseCoin": base, "endTime": end_ms, "size": 500, "interval": "1h"},
                    headers={"apikey": self.COINANK_KEY},
                )
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
            logger.warning(f"  CoinAnk OI/MC获取失败: {e}")
        logger.info(f"  CoinAnk OI/MC: {len(result)} 条")
        return result

    async def fetch_coinank_net_positions(self, symbol: str, start: datetime, end: datetime) -> Dict[int, float]:
        """CoinAnk 净持仓 -> {ts: net_position_value} (正=净多, 负=净空)"""
        result = {}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                end_ms = int(end.timestamp() * 1000)
                resp = await self._get_with_retry(
                    client,
                    f"{self.COINANK_BASE}/api/netPositions/getNetPositions",
                    {"exchange": "Binance", "symbol": symbol, "interval": "1h", "endTime": end_ms, "size": 500},
                    headers={"apikey": self.COINANK_KEY},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("data"):
                        for item in data["data"]:
                            ts = item.get("createTime", item.get("ts", 0))
                            net = item.get("netPosition", item.get("netValue", 0))
                            result[ts] = float(net) if net else 0.0
        except Exception as e:
            logger.warning(f"  CoinAnk净持仓获取失败: {e}")
        logger.info(f"  CoinAnk净持仓: {len(result)} 条")
        return result

    async def fetch_all(self, symbol: str, start: datetime, end: datetime) -> Dict:
        """并行拉取所有数据（含CoinAnk V5数据）"""
        logger.info(f"📥 拉取 {symbol} 历史数据: {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")
        lookback_start = start - timedelta(days=10)
        klines, fr, ls, oi, ca_liq, ca_oi_mc, ca_net = await asyncio.gather(
            self.fetch_klines(symbol, "1h", lookback_start, end),
            self.fetch_funding_rate(symbol, start, end),
            self.fetch_long_short_ratio(symbol, start, end),
            self.fetch_oi_history(symbol, start, end),
            self.fetch_coinank_liq_history(symbol, start, end),
            self.fetch_coinank_oi_mc(symbol, start, end),
            self.fetch_coinank_net_positions(symbol, start, end),
        )
        return {
            "klines": klines, "funding_rates": fr,
            "long_short_ratios": ls, "oi_history": oi,
            "coinank_liq": ca_liq, "coinank_oi_mc": ca_oi_mc, "coinank_net": ca_net,
        }


# ============================================================
# Offline 15-Layer Scoring Engine
# ============================================================

class _SortedLookup:
    """O(log n) 时间序列查找器（替代 O(n) 的 min()）"""
    def __init__(self, data_dict: Dict[int, float]):
        self.keys = sorted(data_dict.keys())
        self.data = data_dict
    
    def find(self, target_ts: int, tolerance_ms: int = 4 * 3600 * 1000) -> Optional[float]:
        if not self.keys:
            return None
        idx = bisect.bisect_left(self.keys, target_ts)
        candidates = []
        if idx < len(self.keys):
            candidates.append(self.keys[idx])
        if idx > 0:
            candidates.append(self.keys[idx - 1])
        best = min(candidates, key=lambda t: abs(t - target_ts))
        if abs(best - target_ts) <= tolerance_ms:
            return self.data[best]
        return None


def score_bar(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    opens: List[float],
    volumes: List[float],
    current_price: float,
    funding_rate: Optional[float] = None,
    ls_ratio: Optional[float] = None,
    oi_current: Optional[float] = None,
    oi_prev: Optional[float] = None,
    fng_value: int = 50,
    **kwargs,
) -> Dict:
    """
    离线版 15 层评分引擎 (V4: 含华尔街级策略升级)
    Returns: {score, direction, breakdown, atr, leverage_info, price_structure, score_delta}
    """
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    # --- Indicators ---
    rsi = calc_rsi(closes)
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = ema12 - ema26
    # Optimized MACD: incremental EMA (O(n) instead of O(n²))
    if len(closes) >= 26:
        k12, k26 = 2/13, 2/27
        ema12_run = sum(closes[:12]) / 12
        ema26_run = sum(closes[:26]) / 26
        macd_values = []
        for i in range(26, len(closes)):
            ema12_run = closes[i] * k12 + ema12_run * (1 - k12)
            ema26_run = closes[i] * k26 + ema26_run * (1 - k26)
            macd_values.append(ema12_run - ema26_run)
        macd_signal = calc_ema(macd_values, 9) if len(macd_values) >= 9 else macd_line
        macd_histogram = macd_values[-1] - macd_signal if macd_values else 0
        macd_hist_growing = len(macd_values) >= 2 and abs(macd_values[-1]) > abs(macd_values[-2])
    else:
        macd_values = []
        macd_signal = macd_line
        macd_histogram = 0
        macd_hist_growing = False

    ma7 = sum(closes[-7:]) / 7
    ma25 = sum(closes[-25:]) / 25
    ma99 = sum(closes[-99:]) / 99 if len(closes) >= 99 else ma25

    # Bollinger Bands
    bb_period = min(20, len(closes))
    bb_c = closes[-bb_period:]
    bb_sma = sum(bb_c) / bb_period
    bb_std = (sum((c - bb_sma) ** 2 for c in bb_c) / bb_period) ** 0.5
    bb_upper = bb_sma + 2 * bb_std
    bb_lower = bb_sma - 2 * bb_std
    bb_position = round((current_price - bb_lower) / (bb_upper - bb_lower) * 100, 1) if bb_upper != bb_lower else 50

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    # Multi-timeframe: use different lookback windows on 1h data
    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
    vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 1
    price_change_1h = round((closes[-1] / closes[-5] - 1) * 100, 2) if len(closes) >= 5 else 0

    # --- LAYER 1: TREND (±20 max) — V4: 4H dominant weighting ---
    # Top traders weight higher timeframes more: 4H is king, 1H confirms, 15m is noise
    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    trends_agree = (trend_15m == trend_1h == trend_4h) and trend_15m != 0
    if trends_agree:
        trend_score = int(trend_score * 1.2)  # V4: Bonus for full alignment
    if not trends_agree and abs(trend_score) > 8:
        penalty = int(trend_score * 0.5)
        trend_score -= penalty
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score
    if trend_score != 0:
        breakdown.append(f"趋势{'+' if trend_score > 0 else ''}{trend_score}")

    # --- V4: PRICE STRUCTURE ANALYSIS (higher-highs / lower-lows) ---
    # Professional price action: detect if making HH/HL (bullish) or LH/LL (bearish)
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count, ll_count = 0, 0
    for i in range(1, min(5, len(recent_highs))):
        if recent_highs[i - 1] > recent_highs[i]:
            hh_count += 1  # Higher high
        if recent_lows[i - 1] < recent_lows[i]:
            ll_count += 1  # Lower low
    if hh_count >= 3:
        price_structure = "bullish_structure"
        tech_score += 5
        breakdown.append(f"价格结构+5(HH={hh_count})")
    elif ll_count >= 3:
        price_structure = "bearish_structure"
        tech_score -= 5
        breakdown.append(f"价格结构-5(LL={ll_count})")
    else:
        price_structure = "no_structure"

    # --- LAYER 2: MOMENTUM (±15 max) ---
    momentum_score = 0
    if rsi < 30 and trend_15m >= 0:
        momentum_score += 5
    elif rsi > 70 and trend_15m <= 0:
        momentum_score -= 5
    elif rsi < 40 and trend_15m > 0:
        momentum_score += 3
    elif rsi > 60 and trend_15m < 0:
        momentum_score -= 3
    if macd_line > 0 and trend_15m > 0:
        momentum_score += 5
    elif macd_line < 0 and trend_15m < 0:
        momentum_score -= 5
    if macd_hist_growing and macd_histogram > 0:
        momentum_score += 5
    elif macd_hist_growing and macd_histogram < 0:
        momentum_score -= 5
    tech_score += momentum_score
    if momentum_score != 0:
        breakdown.append(f"动量{'+' if momentum_score > 0 else ''}{momentum_score}(RSI={rsi})")

    # --- LAYER 3: VOLUME (±10 max) ---
    vol_score = 0
    if vol_ratio > 1.5 and price_change_1h > 0.1:
        vol_score += 5
    elif vol_ratio > 1.5 and price_change_1h < -0.1:
        vol_score -= 5
    obv_trend = sum(1 if closes[i] > closes[i - 1] else -1 for i in range(-10, 0))
    if obv_trend > 5 and trend_15m > 0:
        vol_score += 5
    elif obv_trend < -5 and trend_15m < 0:
        vol_score -= 5
    tech_score += vol_score

    # --- LAYER 4: MARKET STRUCTURE (±5 max) ---
    if bb_position < 15 and trend_15m >= 0:
        tech_score += 3
    elif bb_position > 85 and trend_15m <= 0:
        tech_score -= 3

    # --- LAYER 5: FEAR & GREED (±10, contrarian) ---
    if fng_value <= 10:
        tech_score += 10
        breakdown.append(f"恐贪={fng_value}极度恐惧+10")
    elif fng_value <= 25:
        tech_score += 5
    elif fng_value >= 90:
        tech_score -= 10
        breakdown.append(f"恐贪={fng_value}极度贪婪-10")
    elif fng_value >= 75:
        tech_score -= 5

    # --- LAYER 6: SMART MONEY (±10) ---
    smc_structure = "unknown"
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc["score_adjustment"]
            tech_score += smc_adj
            smc_structure = smc.get("market_structure", "unknown")
            if smc_adj != 0:
                breakdown.append(f"SMC{'+' if smc_adj > 0 else ''}{smc_adj}")
        except Exception:
            pass

    # --- LAYER 7: EVOLUTION RULES (±5) ---
    if _evo_engine:
        try:
            evo_indicators = {
                'rsi': rsi, 'adx': adx, 'fng': fng_value,
                'smc_structure': smc_structure,
                'trend_agreement': trends_agree,
                'atr_pct': round(atr_approx / current_price * 100, 2) if current_price else 0,
            }
            evo_side = 'buy' if tech_score >= 60 else 'sell' if tech_score <= 40 else None
            evo_r = _evo_engine.get_score_adjustment(evo_indicators, side=evo_side, score=tech_score)
            if evo_r['adjustment'] != 0:
                tech_score += int(evo_r['adjustment'])
        except Exception:
            pass

    # --- LAYER 8: FUNDING RATE (±5) ---
    if funding_rate is not None:
        if funding_rate > 0.05 and tech_score >= 60:
            tech_score -= 5
            breakdown.append(f"FR={funding_rate:.3f}%做多拥挤-5")
        elif funding_rate < -0.05 and tech_score <= 40:
            tech_score -= 5
            breakdown.append(f"FR={funding_rate:.3f}%做空拥挤-5")
        elif abs(funding_rate) > 0.1:
            tech_score -= 3

    # --- LAYER 9: ENHANCED (±10) — optimized RSI calc ---
    enhanced_score = 0
    stoch_rsi_k = 50
    try:
        # Only compute StochRSI over the last 28 bars (14 RSI + 14 lookback)
        window = min(len(closes), 42)
        c_win = closes[-window:]
        rsi_values = []
        for i in range(14, len(c_win)):
            gains = [max(0, c_win[j] - c_win[j - 1]) for j in range(i - 13, i + 1)]
            losses_arr = [max(0, c_win[j - 1] - c_win[j]) for j in range(i - 13, i + 1)]
            avg_g = sum(gains) / 14
            avg_l = sum(losses_arr) / 14
            rsi_values.append(100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100)
        if len(rsi_values) >= 14:
            rsi_window = rsi_values[-14:]
            rsi_min, rsi_max = min(rsi_window), max(rsi_window)
            stoch_rsi_k = ((rsi_values[-1] - rsi_min) / (rsi_max - rsi_min) * 100) if rsi_max != rsi_min else 50
            if stoch_rsi_k < 20 and trend_15m >= 0:
                enhanced_score += 5
            elif stoch_rsi_k > 80 and trend_15m <= 0:
                enhanced_score -= 5
        if len(closes) >= 21:
            ema8 = calc_ema(closes[-30:], 8)
            ema21 = calc_ema(closes[-30:], 21)
            ema8_prev = calc_ema(closes[-31:-1], 8) if len(closes) >= 31 else ema8
            ema21_prev = calc_ema(closes[-31:-1], 21) if len(closes) >= 31 else ema21
            if ema8 > ema21 and ema8_prev <= ema21_prev:
                enhanced_score += 5
            elif ema8 < ema21 and ema8_prev >= ema21_prev:
                enhanced_score -= 5
        tech_score += max(-10, min(10, enhanced_score))
    except Exception:
        pass

    # --- LAYER 10: MARKET RESONANCE — skipped in backtest (±0) ---
    # --- LAYER 11: ORDER BOOK — skipped in backtest (±0) ---

    # --- ADX GATE ---
    market_regime = "trending" if adx >= 25 else "ranging" if adx < 20 else "transitioning"
    if adx < 20 and abs(tech_score - 50) > 10:
        tech_score = 50 + int((tech_score - 50) * 0.5)
        breakdown.append(f"ADX={adx}<20震荡减半")

    tech_score = max(0, min(100, tech_score))

    # --- LAYER 12: SIGNAL CONFLICT MATRIX (±8) ---
    if _eval_conflicts:
        try:
            conflict = _eval_conflicts({
                "rsi": rsi, "adx": adx, "trend_15m": trend_15m,
                "trend_1h": trend_1h, "trend_4h": trend_4h,
                "macd_growing": macd_hist_growing, "bb_position": bb_position,
                "volume_ratio": vol_ratio, "stoch_rsi": stoch_rsi_k,
                "market_regime": market_regime, "smc_structure": smc_structure,
                "orderbook_imbalance": 1.0,
            })
            if conflict["adjustment"] != 0:
                tech_score += conflict["adjustment"]
                breakdown.append(f"矩阵{'+' if conflict['adjustment'] > 0 else ''}{conflict['adjustment']}")
        except Exception:
            pass

    # --- LAYER 13: Simplified Liquidation (±5) ---
    if funding_rate is not None and oi_current is not None and oi_prev is not None:
        oi_chg_pct = (oi_current - oi_prev) / oi_prev * 100 if oi_prev > 0 else 0
        # High FR + rising OI = crowded → penalty
        if abs(funding_rate) > 0.05 and oi_chg_pct > 5:
            adj = -3 if funding_rate > 0 else 3
            tech_score += adj
            breakdown.append(f"清算FR+OI{'+' if adj > 0 else ''}{adj}")
        # Rising OI + price near round number → potential squeeze
        round_dist = min(current_price % 1000, 1000 - current_price % 1000) / current_price * 100
        if round_dist < 0.8 and abs(oi_chg_pct) > 3:
            tech_score -= 2
            breakdown.append(f"整数关口风险-2")

    # --- LAYER 14: Volume Profile (simplified for backtest, ±5) ---
    if len(closes) >= 100:
        poc_idx = 0
        max_vol = 0
        bins = 20
        price_min, price_max = min(closes[-100:]), max(closes[-100:])
        bin_width = (price_max - price_min) / bins if price_max > price_min else 1
        vol_profile = [0.0] * bins
        for i in range(-100, 0):
            b = min(int((closes[i] - price_min) / bin_width), bins - 1)
            vol_profile[b] += volumes[i] if i + len(volumes) >= 0 else 1
        poc_bin = vol_profile.index(max(vol_profile))
        poc_price = price_min + (poc_bin + 0.5) * bin_width
        dist_to_poc = (current_price - poc_price) / poc_price * 100
        if abs(dist_to_poc) < 0.5:
            tech_score += 3
            breakdown.append(f"VPVR:POC附近+3")
        elif dist_to_poc > 3:
            tech_score -= 2
            breakdown.append(f"VPVR:远离POC-2")

    tech_score = max(0, min(100, tech_score))

    # --- LAYER 15: LONG/SHORT RATIO (±12) ---
    if ls_ratio is not None and _LSAnalyzer:
        try:
            oi_chg = None
            if oi_current and oi_prev and oi_prev > 0:
                oi_chg = (oi_current - oi_prev) / oi_prev * 100
            fr_dict = {"binance": funding_rate} if funding_rate else {}
            ls_r = _LSAnalyzer.analyze_multi_exchange(
                long_short_ratios={"binance": {"ratio": ls_ratio, "long_pct": ls_ratio / (1 + ls_ratio) * 100, "short_pct": 100 / (1 + ls_ratio)}},
                funding_rates=fr_dict,
                oi_change_pct=oi_chg,
            )
            ls_adj = ls_r.get("score_adjustment", 0)
            if ls_adj != 0:
                tech_score += ls_adj
                breakdown.append(f"多空比{'+' if ls_adj > 0 else ''}{ls_adj}(L/S={ls_ratio:.2f})")
        except Exception:
            pass

    tech_score = max(0, min(100, tech_score))

    # --- V5: LAYER 16: COINANK LIQUIDATION PRESSURE (±8) ---
    ca_liq_long = kwargs.get("ca_liq_long", 0)
    ca_liq_short = kwargs.get("ca_liq_short", 0)
    total_liq = ca_liq_long + ca_liq_short
    if total_liq > 0:
        liq_ratio = ca_liq_long / total_liq  # 0=all short liq, 1=all long liq
        if liq_ratio > 0.75:  # Mostly longs liquidated → bearish
            liq_adj = -8
            breakdown.append(f"清算压力-8(多头爆仓{liq_ratio:.0%})")
        elif liq_ratio > 0.6:
            liq_adj = -4
        elif liq_ratio < 0.25:  # Mostly shorts liquidated → bullish
            liq_adj = 8
            breakdown.append(f"清算压力+8(空头爆仓{1-liq_ratio:.0%})")
        elif liq_ratio < 0.4:
            liq_adj = 4
        else:
            liq_adj = 0
        tech_score += liq_adj

    # --- V5: LAYER 17: OI/MARKET CAP LEVERAGE RISK (±5) ---
    ca_oi_mc = kwargs.get("ca_oi_mc", None)
    if ca_oi_mc is not None and ca_oi_mc > 0:
        if ca_oi_mc > 4.0:
            tech_score -= 5
            breakdown.append(f"杠杆过高-5(OI/MC={ca_oi_mc:.1f}%)")
        elif ca_oi_mc > 3.0:
            tech_score -= 3
        elif ca_oi_mc < 1.5:
            tech_score += 3

    # --- V5: LAYER 18: NET POSITION CONFIRMATION (±3) ---
    ca_net = kwargs.get("ca_net", None)
    if ca_net is not None and ca_net != 0:
        # Will be used after direction is set — store for post-direction adjustment
        pass  # Applied below after direction determination

    tech_score = max(0, min(100, tech_score))

    # === V4: DIRECTION by THRESHOLD ===
    bull_threshold = kwargs.get("score_threshold", 65)
    bear_threshold = 100 - bull_threshold
    if tech_score >= bull_threshold:
        direction = "bullish"
    elif tech_score <= bear_threshold:
        direction = "bearish"
    else:
        direction = "neutral"

    # === V4: 4H TREND GUARD ===
    if direction == "bullish" and trend_4h < 0 and trend_1h < 0:
        tech_score -= 5
        direction = "neutral"
        breakdown.append("4H+1H双空头→拒绝做多")
    elif direction == "bearish" and trend_4h > 0 and trend_1h > 0:
        tech_score += 5
        direction = "neutral"
        breakdown.append("4H+1H双多头→拒绝做空")

    # === V5: L18 NET POSITION CONFIRMATION (±3) ===
    if ca_net is not None and ca_net != 0 and direction != "neutral":
        if ca_net > 0 and direction == "bullish":
            tech_score += 3
            breakdown.append(f"净持仓确认+3(净多{ca_net:+.0f})")
        elif ca_net < 0 and direction == "bearish":
            tech_score += 3
            breakdown.append(f"净持仓确认+3(净空{ca_net:+.0f})")
        elif ca_net > 0 and direction == "bearish":
            tech_score -= 2
        elif ca_net < 0 and direction == "bullish":
            tech_score -= 2
        tech_score = max(0, min(100, tech_score))

    # === V4: ADX GATE (stronger) ===
    if adx < 15 and direction != "neutral":
        breakdown.append(f"ADX={adx}<15→强制观望")
        direction = "neutral"

    # === V4: ASYMMETRIC SL/TP PER REGIME ===
    atr_pct = atr_approx / current_price * 100 if current_price > 0 else 1
    if market_regime == "trending":
        # Trending: wider TP to capture runs, moderate SL
        sl_mult, tp_mult = 2.0, 4.5
    elif market_regime == "ranging":
        # Ranging: tight TP (mean-reversion), moderate SL
        sl_mult, tp_mult = 1.8, 2.5
    else:
        sl_mult, tp_mult = 2.0, 3.5

    if direction == "bullish":
        sl = current_price - atr_approx * sl_mult
        tp = current_price + atr_approx * tp_mult
    elif direction == "bearish":
        sl = current_price + atr_approx * sl_mult
        tp = current_price - atr_approx * tp_mult
    else:
        sl = current_price - atr_approx * sl_mult
        tp = current_price + atr_approx * tp_mult

    # --- R:R filter (regime-adjusted minimum) ---
    min_rr = 1.8 if market_regime == "trending" else 1.3
    rr = 0.0
    if direction != "neutral" and sl and tp:
        risk_d = abs(current_price - sl)
        reward_d = abs(tp - current_price)
        rr = round(reward_d / risk_d, 2) if risk_d > 0 else 0
        if rr < min_rr:
            direction = "neutral"
            breakdown.append(f"R:R={rr}<{min_rr}→观望")

    # --- Dynamic leverage ---
    confidence = abs(tech_score - 50) / 50
    if tech_score >= 80 or tech_score <= 20:
        base_lev = 5
    elif tech_score >= 70 or tech_score <= 30:
        base_lev = 3
    elif tech_score >= 60 or tech_score <= 40:
        base_lev = 2
    else:
        base_lev = 1
    if atr_pct > 3.0:
        vol_f = 0.5
    elif atr_pct > 2.0:
        vol_f = 0.7
    elif atr_pct > 1.0:
        vol_f = 0.85
    else:
        vol_f = 1.0
    rec_leverage = max(1, min(5, int(base_lev * vol_f)))

    if market_regime == "ranging":
        rec_leverage = max(1, rec_leverage - 1)

    return {
        "score": tech_score,
        "direction": direction,
        "breakdown": breakdown,
        "atr": atr_approx,
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "rr_ratio": rr,
        "leverage": rec_leverage,
        "rsi": rsi,
        "adx": adx,
        "bb_position": bb_position,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_sma": bb_sma,
        "trend_4h": trend_4h,
        "trend_1h": trend_1h,
        "market_regime": market_regime,
        "price_structure": price_structure,
        "vol_ratio": vol_ratio,
        "layer_votes": {
            "trend": 1 if trend_score > 0 else -1 if trend_score < 0 else 0,
            "momentum": 1 if momentum_score > 0 else -1 if momentum_score < 0 else 0,
            "volume": 1 if vol_score > 0 else -1 if vol_score < 0 else 0,
            "rsi_zone": 1 if rsi < 40 else -1 if rsi > 60 else 0,
            "macd": 1 if macd_line > 0 else -1 if macd_line < 0 else 0,
            "bb": 1 if bb_position < 30 else -1 if bb_position > 70 else 0,
            "structure": 1 if price_structure == "bullish_structure" else -1 if price_structure == "bearish_structure" else 0,
        },
    }


# ============================================================
# Backtest Engine
# ============================================================

class BacktesterV2:
    """专业回测引擎 — 15层评分 + 动态杠杆 + 完整交易模拟"""

    def __init__(self, initial_balance: float = 10000, risk_pct: float = 2.0):
        self.initial_balance = initial_balance
        self.risk_pct = risk_pct
        self.fetcher = HistoricalDataFetcher()

    async def run(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        score_threshold: int = 65,
        label: str = "",
    ) -> Dict:
        """
        执行回测
        Args:
            symbol: 交易对
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            score_threshold: 开仓阈值
            label: 回测标签
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end - start).days

        logger.info(f"\n{'='*60}")
        logger.info(f"🔬 回测: {symbol} | {start_date} → {end_date} ({days}天) | 阈值={score_threshold}")
        logger.info(f"{'='*60}")

        # Fetch historical data (with retry protection)
        try:
            data = await self.fetcher.fetch_all(symbol, start, end)
        except Exception as e:
            logger.error(f"数据拉取失败: {e}")
            return {"error": f"数据拉取失败: {e}", "label": label}
        klines = data["klines"]
        fr_data = data["funding_rates"]
        ls_data = data["long_short_ratios"]
        oi_data = data["oi_history"]
        ca_liq_data = data.get("coinank_liq", {})
        ca_oi_mc_data = data.get("coinank_oi_mc", {})
        ca_net_data = data.get("coinank_net", {})

        if len(klines) < 100:
            return {"error": f"K线不足: {len(klines)}条", "label": label}

        # Fetch historical Fear & Greed index (best effort)
        fng_history = await self._fetch_fng_history(start, end)

        # Simulation state
        balance = self.initial_balance
        position = None
        trades = []
        equity_curve = []
        score_history = []
        trade_count = 0
        start_ms = int(start.timestamp() * 1000)

        closes, highs, lows, opens, volumes = [], [], [], [], []
        last_trade_close_idx = -999
        prev_direction = "neutral"
        prev_score = 50
        whipsaw_counter = 0
        consecutive_losses = 0
        daily_pnl = 0.0          # V4: daily circuit breaker
        current_day = None       # V4: track current day
        fr_lookup = _SortedLookup(fr_data)
        ls_lookup = _SortedLookup(ls_data)
        oi_lookup = _SortedLookup(oi_data)

        # V5: CoinAnk data lookups (dict-based, ts -> value)
        # For liq data: ts -> {longTurnover, shortTurnover}
        # For oi_mc: ts -> float (percentage)
        # For net: ts -> float (positive=net long, negative=net short)
        ca_liq_lookup = _SortedLookup({ts: 1.0 for ts in ca_liq_data}) if ca_liq_data else None
        ca_oi_mc_lookup = _SortedLookup(ca_oi_mc_data) if ca_oi_mc_data else None
        ca_net_lookup = _SortedLookup(ca_net_data) if ca_net_data else None

        for idx, k in enumerate(klines):
            closes.append(k["close"])
            highs.append(k["high"])
            lows.append(k["low"])
            opens.append(k["open"])
            volumes.append(k["volume"])
            equity_curve.append(round(balance, 2))

            if len(closes) < 50:
                continue
            if k["ts"] < start_ms:
                continue

            ts = k["ts"]
            price = k["close"]
            high = k["high"]
            low = k["low"]

            # V4: Daily PnL circuit breaker reset
            trade_day = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            if trade_day != current_day:
                daily_pnl = 0.0
                current_day = trade_day

            # Check existing position SL/TP
            if position:
                sl_hit = (position["side"] == "buy" and low <= position["sl"]) or \
                         (position["side"] == "sell" and high >= position["sl"])
                tp_hit = (position["side"] == "buy" and high >= position["tp"]) or \
                         (position["side"] == "sell" and low <= position["tp"])

                # === V4: MAX HOLDING DURATION ===
                bars_held = idx - position["opened_idx"]
                max_hold = 36 if position.get("regime") == "trending" else 18
                if bars_held >= max_hold and not tp_hit:
                    # Force close stale position at current price
                    exit_price = price
                    if position["side"] == "buy":
                        pnl = (exit_price - position["entry"]) * position["amount"]
                    else:
                        pnl = (position["entry"] - exit_price) * position["amount"]
                    balance += pnl
                    daily_pnl += pnl
                    trades.append({
                        "side": position["side"], "entry": position["entry"],
                        "exit": round(exit_price, 2), "pnl": round(pnl, 2),
                        "reason": f"max_hold_{max_hold}bars",
                        "bars": bars_held,
                        "leverage": position["leverage"],
                        "ts": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
                    })
                    position = None
                    last_trade_close_idx = idx
                    if pnl <= 0:
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0
                elif sl_hit or tp_hit:
                    exit_price = position["sl"] if sl_hit else position["tp"]
                    if position["side"] == "buy":
                        pnl = (exit_price - position["entry"]) * position["amount"]
                    else:
                        pnl = (position["entry"] - exit_price) * position["amount"]

                    # === V4: PARTIAL TAKE-PROFIT ===
                    # On TP hit, close 60% and move SL to breakeven for remaining 40%
                    if tp_hit and not sl_hit:
                        partial_pnl = pnl * 0.6
                        balance += partial_pnl
                        daily_pnl += partial_pnl
                        trades.append({
                            "side": position["side"], "entry": position["entry"],
                            "exit": round(exit_price, 2), "pnl": round(partial_pnl, 2),
                            "reason": "partial_tp_60%",
                            "bars": bars_held,
                            "leverage": position["leverage"],
                            "ts": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
                        })
                        # Keep 40% running with SL at breakeven, TP extended 50%
                        position["amount"] = position["amount"] * 0.4
                        position["sl"] = position["entry"]  # Move SL to breakeven
                        tp_extension = abs(position["tp"] - position["entry"]) * 0.5
                        if position["side"] == "buy":
                            position["tp"] = round(position["tp"] + tp_extension, 2)
                        else:
                            position["tp"] = round(position["tp"] - tp_extension, 2)
                        trade_count += 1
                        consecutive_losses = 0
                    else:
                        balance += pnl
                        daily_pnl += pnl
                        trades.append({
                            "side": position["side"], "entry": position["entry"],
                            "exit": round(exit_price, 2), "pnl": round(pnl, 2),
                            "reason": "sl" if sl_hit else "tp_full",
                            "bars": bars_held,
                            "leverage": position["leverage"],
                            "ts": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
                        })
                        position = None
                        last_trade_close_idx = idx
                        if pnl <= 0:
                            consecutive_losses += 1
                        else:
                            consecutive_losses = 0
                else:
                    # Trailing stop: move SL after 40% of TP distance reached
                    if position["side"] == "buy":
                        target_dist = abs(position["tp"] - position["entry"])
                        if price >= position["entry"] + target_dist * 0.4:
                            new_sl = max(position["sl"], position["entry"] + target_dist * 0.15)
                            if new_sl > position["sl"]:
                                position["sl"] = round(new_sl, 2)
                    elif position["side"] == "sell":
                        target_dist = abs(position["entry"] - position["tp"])
                        if price <= position["entry"] - target_dist * 0.4:
                            new_sl = min(position["sl"], position["entry"] - target_dist * 0.15)
                            if new_sl < position["sl"]:
                                position["sl"] = round(new_sl, 2)

            # Score this bar
            fr = fr_lookup.find(ts, 8 * 3600 * 1000)
            ls = ls_lookup.find(ts, 2 * 3600 * 1000)
            oi_cur = oi_lookup.find(ts, 2 * 3600 * 1000)
            oi_prev = oi_lookup.find(ts - 3600 * 1000, 2 * 3600 * 1000)
            fng = fng_history.get(datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d"), 50)

            win = 200
            # V5: CoinAnk data lookup for this bar
            ca_liq_long_val, ca_liq_short_val = 0, 0
            if ca_liq_lookup and ca_liq_lookup.find(ts, 2 * 3600 * 1000) is not None:
                # Find closest ts in ca_liq_data
                closest_ts = min(ca_liq_data.keys(), key=lambda t: abs(t - ts)) if ca_liq_data else None
                if closest_ts and abs(closest_ts - ts) < 2 * 3600 * 1000:
                    liq_item = ca_liq_data[closest_ts]
                    ca_liq_long_val = liq_item.get("longTurnover", 0)
                    ca_liq_short_val = liq_item.get("shortTurnover", 0)
            ca_oi_mc_val = ca_oi_mc_lookup.find(ts, 2 * 3600 * 1000) if ca_oi_mc_lookup else None
            ca_net_val = ca_net_lookup.find(ts, 2 * 3600 * 1000) if ca_net_lookup else None

            result = score_bar(
                closes=closes[-win:], highs=highs[-win:], lows=lows[-win:],
                opens=opens[-win:], volumes=volumes[-win:],
                current_price=price,
                funding_rate=fr, ls_ratio=ls,
                oi_current=oi_cur, oi_prev=oi_prev,
                fng_value=fng,
                score_threshold=score_threshold,
                ca_liq_long=ca_liq_long_val,
                ca_liq_short=ca_liq_short_val,
                ca_oi_mc=ca_oi_mc_val,
                ca_net=ca_net_val,
            )

            score = result["score"]
            direction = result["direction"]
            regime = result.get("market_regime", "transitioning")
            layer_votes = result.get("layer_votes", {})
            vol_ratio_now = result.get("vol_ratio", 1.0)
            bb_upper = result.get("bb_upper", price * 1.02)
            bb_lower = result.get("bb_lower", price * 0.98)
            score_history.append({"ts": ts, "score": score, "direction": direction})

            # === V4: SCORE MOMENTUM (acceleration) ===
            score_delta = score - prev_score

            # Confluence
            if direction == "bullish":
                confluence = sum(1 for v in layer_votes.values() if v > 0)
            elif direction == "bearish":
                confluence = sum(1 for v in layer_votes.values() if v < 0)
            else:
                confluence = 0
            total_layers = max(len(layer_votes), 1)
            confluence_pct = confluence / total_layers * 100

            # Anti-whipsaw
            if direction != prev_direction and direction != "neutral" and prev_direction != "neutral":
                whipsaw_counter += 1
            elif direction == prev_direction and direction != "neutral":
                whipsaw_counter = max(0, whipsaw_counter - 1)

            # === V4: TRADE ENTRY DECISION ===
            if position is None and idx < len(klines) - 5:
                time_since_last = idx - last_trade_close_idx if last_trade_close_idx >= 0 else 999

                # V4: Daily circuit breaker — stop trading after 5% daily loss
                if daily_pnl < -(self.initial_balance * 0.05):
                    prev_direction = direction
                    prev_score = score
                    continue

                # Regime-specific params
                if regime == "trending":
                    cooldown = 6
                    min_confluence = 3
                    position_scale = 1.0
                elif regime == "ranging":
                    cooldown = 10
                    min_confluence = 4
                    position_scale = 0.5
                else:
                    cooldown = 8
                    min_confluence = 3
                    position_scale = 0.7

                # Circuit breaker
                if consecutive_losses >= 3:
                    cooldown = max(cooldown, 24)

                if time_since_last < cooldown:
                    prev_direction = direction
                    prev_score = score
                    continue

                # V4: Momentum persistence + score acceleration
                momentum_confirmed = (
                    direction != "neutral"
                    and prev_direction == direction
                )

                # V4: Score must be accelerating in trade direction
                score_accelerating = (
                    (direction == "bullish" and score_delta > 0) or
                    (direction == "bearish" and score_delta < 0)
                )

                # V4: Volume spike requirement — need above-average volume
                volume_confirmed = vol_ratio_now >= 1.2

                # Anti-whipsaw
                whipsaw_ok = whipsaw_counter < 3

                # Confluence
                confluence_ok = confluence >= min_confluence

                # === V4: BB OSCILLATION MODE for ranging markets ===
                bb_entry = False
                if regime == "ranging" and direction == "neutral":
                    # In ranging: buy near lower BB, sell near upper BB
                    if bb_lower > 0 and price <= bb_lower * 1.003:
                        direction = "bullish"
                        bb_entry = True
                        # Tight TP at mid-BB, SL below BB
                        result["tp"] = round(result.get("bb_sma", price * 1.01), 2)
                        result["sl"] = round(bb_lower * 0.995, 2)
                    elif bb_upper > 0 and price >= bb_upper * 0.997:
                        direction = "bearish"
                        bb_entry = True
                        result["tp"] = round(result.get("bb_sma", price * 0.99), 2)
                        result["sl"] = round(bb_upper * 1.005, 2)

                # Combined entry decision
                if bb_entry:
                    # BB oscillation trades bypass normal filters but use small position
                    should_trade = True
                    position_scale = 0.35  # Small position for mean-reversion
                else:
                    should_trade = (
                        momentum_confirmed
                        and (score_accelerating or confluence >= min_confluence + 1)
                        and whipsaw_ok
                        and confluence_ok
                        and volume_confirmed
                    )

                if should_trade:
                    side = "buy" if direction == "bullish" else "sell"
                    lev = result["leverage"]

                    # Adaptive sizing with V4 quality scaling
                    quality_scale = min(1.0, confluence_pct / 75)
                    final_scale = position_scale * quality_scale
                    # V4: Bonus scale for strong score acceleration
                    if abs(score_delta) > 5:
                        final_scale = min(1.0, final_scale * 1.3)
                    risk_amount = balance * (self.risk_pct / 100) * final_scale

                    sl_dist = abs(price - result["sl"])
                    amount = risk_amount / sl_dist if sl_dist > 0 else 0
                    if amount > 0:
                        position = {
                            "side": side, "entry": price, "amount": amount,
                            "sl": result["sl"], "tp": result["tp"],
                            "leverage": lev, "opened_idx": idx,
                            "regime": regime,
                        }
                        trade_count += 1

            prev_direction = direction
            prev_score = score

            equity_curve[-1] = round(balance, 2)

        # Close remaining position
        if position:
            exit_price = closes[-1]
            pnl = (exit_price - position["entry"]) * position["amount"] if position["side"] == "buy" else \
                  (position["entry"] - exit_price) * position["amount"]
            balance += pnl
            trades.append({
                "side": position["side"], "entry": position["entry"],
                "exit": round(exit_price, 2), "pnl": round(pnl, 2),
                "reason": "end", "bars": len(klines) - position["opened_idx"],
                "leverage": position["leverage"],
                "ts": "end",
            })

        equity_curve.append(round(balance, 2))

        # Statistics
        return self._calc_stats(trades, equity_curve, balance, symbol, start_date, end_date, days, score_threshold, label, score_history)

    def _calc_stats(self, trades, equity_curve, final_balance, symbol, start_date, end_date, days, threshold, label, score_history) -> Dict:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in trades)

        # Max drawdown
        max_dd = 0
        peak = self.initial_balance
        for eq in equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 1

        # Profit factor
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999

        # Sharpe
        if len(equity_curve) >= 2:
            returns = [(equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
                       for i in range(1, len(equity_curve)) if equity_curve[i - 1] > 0]
            avg_ret = sum(returns) / len(returns) if returns else 0
            std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 1
            sharpe = round(avg_ret / std_ret * (252 ** 0.5), 2) if std_ret > 0 else 0
        else:
            sharpe = 0

        # Leverage stats
        leverages = [t.get("leverage", 1) for t in trades]
        avg_lev = round(sum(leverages) / len(leverages), 1) if leverages else 0

        win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0

        stats = {
            "label": label,
            "symbol": symbol,
            "period": f"{start_date} → {end_date}",
            "days": days,
            "threshold": threshold,
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / self.initial_balance * 100, 2),
            "profit_factor": pf,
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": sharpe,
            "rr_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_leverage": avg_lev,
            "initial_balance": self.initial_balance,
            "final_balance": round(final_balance, 2),
            "trades": trades[-30:],
            "equity_curve": equity_curve[-300:],
        }

        # Status emoji
        if win_rate >= 55 and pf >= 1.5 and max_dd <= 15:
            grade = "🏆 优秀"
        elif win_rate >= 45 and pf >= 1.2 and max_dd <= 20:
            grade = "✅ 合格"
        elif win_rate >= 40 and total_pnl > 0:
            grade = "⚠️ 一般"
        else:
            grade = "❌ 不合格"

        stats["grade"] = grade

        logger.info(
            f"  {grade} | {len(trades)}笔 | 胜率{win_rate}% | PnL ${total_pnl:+,.2f} ({total_pnl / self.initial_balance * 100:+.1f}%) "
            f"| 回撤{max_dd:.1f}% | Sharpe {sharpe} | PF {pf} | R:R {stats['rr_ratio']} | 均杠杆{avg_lev}x"
        )

        return stats

    async def _fetch_fng_history(self, start: datetime, end: datetime) -> Dict[str, int]:
        """拉取历史 Fear & Greed Index"""
        days_count = (end - start).days + 10
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"https://api.alternative.me/fng/?limit={days_count}&format=json")
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    result = {}
                    for d in data:
                        ts = int(d["timestamp"])
                        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                        result[date_str] = int(d["value"])
                    logger.info(f"  恐贪指数: {len(result)} 天")
                    return result
        except Exception as e:
            logger.warning(f"  恐贪指数获取失败: {e}")
        return {}

    async def run_full_suite(self) -> List[Dict]:
        """运行完整回测套件: 3币种 × 3时段 × 3阈值"""
        scenarios = [
            # (symbol, start, end, label)
            ("BTCUSDT", "2024-10-01", "2024-12-31", "BTC牛市"),
            ("BTCUSDT", "2025-01-15", "2025-02-28", "BTC震荡"),
            ("BTCUSDT", "2025-02-22", "2025-03-11", "BTC暴跌"),
            ("ETHUSDT", "2024-10-01", "2024-12-31", "ETH牛市"),
            ("ETHUSDT", "2025-01-15", "2025-02-28", "ETH震荡"),
            ("ETHUSDT", "2025-02-22", "2025-03-11", "ETH暴跌"),
            ("SOLUSDT", "2024-10-01", "2024-12-31", "SOL牛市"),
            ("SOLUSDT", "2025-01-15", "2025-02-28", "SOL震荡"),
            ("SOLUSDT", "2025-02-22", "2025-03-11", "SOL暴跌"),
        ]
        thresholds = [65, 60, 55]

        all_results = []
        for sym, s, e, lbl in scenarios:
            # Fetch data once per scenario
            for thr in thresholds:
                result = await self.run(sym, s, e, score_threshold=thr, label=f"{lbl}/阈值{thr}")
                all_results.append(result)

        # Print summary table
        print("\n" + "=" * 120)
        print(f"{'标签':<16} {'交易':>4} {'胜率':>6} {'PnL($)':>10} {'PnL%':>7} {'回撤%':>6} {'Sharpe':>7} {'PF':>5} {'R:R':>5} {'杠杆':>5} {'评级':>6}")
        print("-" * 120)
        for r in all_results:
            if "error" in r:
                print(f"  {r.get('label', '?'):<14} ERROR: {r['error']}")
                continue
            print(
                f"  {r['label']:<14} {r['total_trades']:>4} {r['win_rate']:>5.1f}% "
                f"${r['total_pnl']:>+9,.2f} {r['total_pnl_pct']:>+6.1f}% "
                f"{r['max_drawdown_pct']:>5.1f}% {r['sharpe_ratio']:>6.2f} "
                f"{r['profit_factor']:>5.2f} {r['rr_ratio']:>4.2f} "
                f"{r['avg_leverage']:>4.1f}x {r['grade']}"
            )
        print("=" * 120)

        return all_results


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

    async def main():
        bt = BacktesterV2(initial_balance=10000, risk_pct=2.0)
        results = await bt.run_full_suite()
        
        # Save results
        output = {
            "timestamp": datetime.now().isoformat(),
            "results": [{k: v for k, v in r.items() if k not in ("trades", "equity_curve")} for r in results],
        }
        out_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n📊 结果已保存: {out_path}")

    asyncio.run(main())
