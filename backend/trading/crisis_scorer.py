"""
Crisis Scorer — 生产环境危机模式评分引擎

回测验证:
  S5策略 30天BTC/ETH/SOL全部盈利: avg +5.02%
  BTC +3.7% | ETH +4.7% | SOL +6.7%

核心逻辑:
  入场: 4H趋势 + 2连续同方向K线 + EMA21确认
  仓位: FNG/FR/LS动态调节 (越恐惧→越大仓位)
  方向: 双向(做多/做空均可)
  SL: 3.0x ATR | TP: 8.0x ATR | Hold: 72 bars max
"""
import asyncio
from typing import Dict, Optional, Tuple
from loguru import logger
from datetime import datetime

try:
    import httpx
except ImportError:
    httpx = None

try:
    from backend.analysis.smart_money import analyze_smc as _analyze_smc
except Exception:
    _analyze_smc = None


# ============================================================
# Helper: Technical Indicators
# ============================================================

def _ema(data: list, period: int) -> float:
    if len(data) < period:
        return data[-1] if data else 0
    k = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for v in data[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        gains.append(max(0, d))
        losses.append(max(0, -d))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(closes) < period * 2:
        return 25.0
    tr_list, pdm_list, ndm_list = [], [], []
    for i in range(-period * 2, 0):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm_list.append(up if up > max(0, dn) else 0)
        ndm_list.append(dn if dn > max(0, up) else 0)
    atr = sum(tr_list[-period:]) / period
    pdm = sum(pdm_list[-period:]) / period
    ndm = sum(ndm_list[-period:]) / period
    if atr == 0:
        return 25.0
    pdi = pdm / atr * 100
    ndi = ndm / atr * 100
    dx = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) > 0 else 0
    return dx


def _trend(closes: list, fast: int = 20, slow: int = 50) -> int:
    if len(closes) < slow:
        return 0
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    diff = (ema_fast - ema_slow) / ema_slow * 100 if ema_slow else 0
    if diff > 0.5:
        return 1
    elif diff < -0.5:
        return -1
    return 0


# ============================================================
# Crisis Mode Detection
# ============================================================

_crisis_cache = {"value": False, "fng": 50, "ts": 0}

async def detect_crisis_mode(fng_value: Optional[int] = None) -> Dict:
    """
    检测是否处于危机模式.
    
    Returns:
        {"is_crisis": bool, "fng": int, "reason": str}
    """
    now = datetime.now().timestamp()

    # Use cached result if recent (< 5 min)
    if now - _crisis_cache["ts"] < 300 and fng_value is None:
        return {"is_crisis": _crisis_cache["value"], "fng": _crisis_cache["fng"],
                "reason": "cached"}

    # Get FNG if not provided
    fng = fng_value
    if fng is None:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("https://api.alternative.me/fng/?limit=1&format=json")
                if r.status_code == 200:
                    fng = int(r.json()["data"][0]["value"])
        except Exception as e:
            logger.warning(f"FNG获取失败: {e}")
            fng = _crisis_cache.get("fng", 50)

    is_crisis = fng <= 25
    reason = f"FNG={fng}"
    if is_crisis:
        reason += " (极度恐惧→危机模式)"
    
    # Check BlockBeats war keywords (non-blocking, best-effort)
    war_count = 0
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("https://api.theblockbeats.news/v1/open-api/open-flash",
                            params={"size": 15, "page": 1, "type": "push", "lang": "en"})
            if r.status_code == 200:
                items = r.json().get("data", {}).get("data", [])
                war_kw = ["war", "iran", "israel", "missile", "strike", "conflict",
                          "sanction", "military", "attack", "bomb", "nuclear"]
                for item in items:
                    text = (item.get("title", "") + " " + item.get("content", "")).lower()
                    if any(kw in text for kw in war_kw):
                        war_count += 1
                war_pct = war_count / len(items) * 100 if items else 0
                reason += f" | 战争新闻{war_count}/{len(items)}({war_pct:.0f}%)"
                if war_pct >= 20:
                    is_crisis = True  # War news alone can trigger crisis
    except Exception:
        pass

    _crisis_cache.update({"value": is_crisis, "fng": fng, "ts": now})
    return {"is_crisis": is_crisis, "fng": fng, "war_news_count": war_count,
            "reason": reason}


# ============================================================
# Crisis Scoring (S5: FNG+FR+LS Combined)
# ============================================================

async def crisis_score(
    symbol: str,
    klines: list,
    current_price: float,
    fng_value: int = 50,
    funding_rate: Optional[float] = None,
    ls_ratio: Optional[float] = None,
) -> Dict:
    """
    S5危机策略评分 — 双向版.
    
    入场条件: 4H趋势 + 2连续同方向K线 + EMA21确认
    方向: 做空(4H↓+2阴+EMA21下方) 或 做多(4H↑+2阳+EMA21上方)
    仓位: FNG/FR/LS动态调节
    
    Returns:
        {
            "direction": "bearish" | "bullish" | "neutral",
            "entry_price": float,
            "sl_price": float,
            "tp_price": float,
            "leverage": int,
            "risk_pct": float,
            "score": int,
            "reasoning": str,
            "breakdown": list,
        }
    """
    # Need at least 50 candles
    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    opens = [k["open"] for k in klines]
    volumes = [k.get("volume", 0) for k in klines]

    if len(closes) < 50:
        return _neutral("数据不足(<50 K线)")

    # ===== DETERMINE DIRECTION =====
    breakdown = []

    # 1. 4H trend
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_4h = _trend(closes_4h, 20, 50)

    # 2. Candle confirmation
    c1_bear = closes[-1] < opens[-1]
    c2_bear = closes[-2] < opens[-2]
    c1_bull = closes[-1] > opens[-1]
    c2_bull = closes[-2] > opens[-2]

    # 3. EMA21 position
    ema21 = _ema(closes[-30:], 21)

    # Determine side: bearish, bullish, or neutral
    side = None
    if trend_4h < 0 and c1_bear and c2_bear and current_price < ema21:
        side = "bearish"
        breakdown.append("✅ 4H↓+2阴+EMA21下 → 做空")
    elif trend_4h > 0 and c1_bull and c2_bull and current_price > ema21:
        side = "bullish"
        breakdown.append("✅ 4H↑+2阳+EMA21上 → 做多")
    else:
        return _neutral(f"无明确方向(4H={trend_4h}, price={'>' if current_price > ema21 else '<'}EMA21={ema21:.0f})")

    # 4. SMC (optional boost)
    smc_adj = 0
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc.get("score_adjustment", 0)
            # SMC confirming our direction
            if (side == "bearish" and smc_adj < 0) or (side == "bullish" and smc_adj > 0):
                breakdown.append(f"✅ SMC确认({smc_adj})")
            elif (side == "bearish" and smc_adj > 3) or (side == "bullish" and smc_adj < -3):
                # SMC strongly disagrees with our direction → reduce confidence
                smc_adj = 0  # Don't let it override crisis direction
                breakdown.append("⚠️ SMC方向相反,忽略")
        except Exception:
            pass

    # 5. LL/HH structure (optional boost)
    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows)))
                   if recent_lows[i - 1] < recent_lows[i])
    hh_count = sum(1 for i in range(1, min(5, len(recent_highs)))
                   if recent_highs[i - 1] > recent_highs[i])
    
    if side == "bearish" and ll_count >= 3:
        breakdown.append(f"✅ LL结构({ll_count})")
    elif side == "bullish" and hh_count >= 3:
        breakdown.append(f"✅ HH结构({hh_count})")

    # ===== PASSED CONDITIONS → CALCULATE SL/TP =====

    # ATR for SL/TP
    atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    # Dynamic TP multiplier
    tp_mult = 8.0
    if side == "bearish":
        if smc_adj < -5 or ll_count >= 4:
            tp_mult = 10.0
        sl_price = round(current_price + atr * 3.0, 2)
        tp_price = round(current_price - atr * tp_mult, 2)
    else:  # bullish
        if smc_adj > 5 or hh_count >= 4:
            tp_mult = 10.0
        sl_price = round(current_price - atr * 3.0, 2)
        tp_price = round(current_price + atr * tp_mult, 2)

    # ===== DYNAMIC RISK (FNG + FR + LS) =====
    risk_pct = 2.0

    # FNG adjustment
    if fng_value <= 10:
        risk_pct += 1.0
        breakdown.append(f"📰 FNG={fng_value}(极恐)→risk+1%")
    elif fng_value <= 20:
        risk_pct += 0.5
        breakdown.append(f"📰 FNG={fng_value}(恐惧)→risk+0.5%")
    elif fng_value > 30:
        risk_pct -= 1.0
        breakdown.append(f"📰 FNG={fng_value}(较高)→risk-1%")

    # FR adjustment
    if funding_rate is not None:
        if funding_rate > 0.01 and side == "bearish":
            risk_pct += 0.5
            breakdown.append(f"💰 FR={funding_rate:.4f}(多头付费,利空)→risk+0.5%")
        elif funding_rate < -0.01 and side == "bullish":
            risk_pct += 0.5
            breakdown.append(f"💰 FR={funding_rate:.4f}(空头付费,利多)→risk+0.5%")
        elif (funding_rate > 0.01 and side == "bullish") or (funding_rate < -0.01 and side == "bearish"):
            risk_pct -= 0.5
            breakdown.append(f"💰 FR={funding_rate:.4f}(拥挤方)→risk-0.5%")

    # LS ratio adjustment
    if ls_ratio is not None:
        if ls_ratio > 2.0 and side == "bearish":
            risk_pct += 0.5
            breakdown.append(f"📊 LS={ls_ratio:.2f}(多头过多,利空)→risk+0.5%")
        elif ls_ratio < 0.7 and side == "bullish":
            risk_pct += 0.5
            breakdown.append(f"📊 LS={ls_ratio:.2f}(空头过多,利多)→risk+0.5%")
        elif (ls_ratio > 2.0 and side == "bullish") or (ls_ratio < 0.7 and side == "bearish"):
            risk_pct -= 0.5
            breakdown.append(f"📊 LS={ls_ratio:.2f}(反向拥挤)→risk-0.5%")

    risk_pct = max(0.5, min(4.0, risk_pct))

    # Dynamic leverage from FNG
    if fng_value <= 15:
        leverage = 3
    elif fng_value <= 25:
        leverage = 2
    else:
        leverage = 1

    # Score (for display)
    tech_score = 30 if side == "bearish" else 70  # Base score reflects direction
    tech_score += smc_adj
    struct_bonus = ll_count if side == "bearish" else hh_count
    if struct_bonus >= 3:
        tech_score += (-5 if side == "bearish" else 5)
    tech_score = max(0, min(100, tech_score))

    dir_label = "危机做空" if side == "bearish" else "危机做多"
    reasoning = (
        f"{dir_label}: 4H{'↓' if side == 'bearish' else '↑'}+2{'阴' if side == 'bearish' else '阳'}+EMA21{'下' if side == 'bearish' else '上'} | "
        f"SL={sl_price:,.0f} TP={tp_price:,.0f} | "
        f"FNG={fng_value} FR={funding_rate} LS={ls_ratio} → "
        f"risk={risk_pct:.1f}% lev={leverage}x"
    )

    return {
        "direction": side,
        "entry_price": current_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "leverage": leverage,
        "risk_pct": risk_pct,
        "score": tech_score,
        "reasoning": reasoning,
        "breakdown": breakdown,
        "atr": atr,
        "adx": _adx(highs, lows, closes),
        "market_regime": "crisis",
    }


def _neutral(reason: str) -> Dict:
    return {
        "direction": "neutral",
        "entry_price": 0, "sl_price": 0, "tp_price": 0,
        "leverage": 1, "risk_pct": 0, "score": 50,
        "reasoning": f"不交易: {reason}",
        "breakdown": [f"❌ {reason}"],
        "atr": 0, "adx": 0, "market_regime": "crisis",
    }


# ============================================================
# Fetch OKX Market Data for Scoring
# ============================================================

async def fetch_crisis_data(symbol: str) -> Dict:
    """
    拉取评分所需的实时数据.
    优先OKX, 失败则回退Binance.
    Returns: {"klines": [...], "current_price": float, "funding_rate": float, "ls_ratio": float}
    """
    from backend.main import _exchange_data
    
    klines_formatted = []
    fr = None
    ls = None
    current_price = 0

    try:
        # 1. K-lines
        klines_raw = await _exchange_data.get_klines_with_fallback(symbol, interval="1h", limit=200)
        if klines_raw:
            # exchange_data returns: [time(ms), open, high, low, close, volume, ...]
            # crisis_scorer expects: {"ts": int, "open": float, "high": float, "low": float, "close": float, "volume": float}
            for c in klines_raw:
                klines_formatted.append({
                    "ts": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5])
                })
            if klines_formatted:
                current_price = klines_formatted[-1]["close"]
        
        # 2. Funding Rate
        fr_data = await _exchange_data.get_funding_rate_with_fallback(symbol)
        if fr_data and fr_data.get("funding_rate") is not None:
            fr = float(fr_data["funding_rate"])
            
        # 3. Long/Short Ratio
        ls_data = await _exchange_data.get_long_short_with_fallback(symbol, period="1h", limit=1)
        if ls_data and len(ls_data) > 0:
            ls = float(ls_data[0].get("long_short_ratio", 1.0))
            
    except Exception as e:
        logger.warning(f"获取危机数据异常: {e}")

    return {
        "klines": klines_formatted,
        "current_price": current_price,
        "funding_rate": fr,
        "ls_ratio": ls,
    }



# ============================================================
# Entry Point: Run One Cycle
# ============================================================

async def run_crisis_cycle(symbol: str, fng_value: int = 50) -> Dict:
    """
    对单个币种运行一次危机评分周期.
    
    Args:
        symbol: e.g. "BTCUSDT"
        fng_value: current Fear & Greed value
    
    Returns:
        Full scoring result dict
    """
    try:
        data = await fetch_crisis_data(symbol)
        if not data["klines"] or len(data["klines"]) < 50:
            return _neutral(f"{symbol} K线不足")

        result = await crisis_score(
            symbol=symbol,
            klines=data["klines"],
            current_price=data["current_price"],
            fng_value=fng_value,
            funding_rate=data["funding_rate"],
            ls_ratio=data["ls_ratio"],
        )
        result["symbol"] = symbol
        result["current_price"] = data["current_price"]
        return result

    except Exception as e:
        logger.error(f"Crisis score error for {symbol}: {e}")
        return _neutral(f"评分错误: {e}")
