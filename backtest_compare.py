# -*- coding: utf-8 -*-
"""
====================================================================
Professional Strategy Comparison Backtest
  Normal (18-Layer Trend) vs Crisis (S5 Bidirectional)
  BTC / ETH / SOL  ×  30 days / 90 days
  初始资金 1000 USDT  |  Binance Futures data (15m K-lines)
====================================================================
"""
import asyncio, sys, os, json, time, math
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

sys.path.insert(0, r"D:\All_in_AI\Trading_system")

from backend.archive.trading.backtester_v2 import (
    HistoricalDataFetcher, score_bar, _SortedLookup,
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

# ═══════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PERIODS = [30, 90]              # 30d and 90d
INTERVAL = "15m"                # 15-minute candles
INITIAL_BALANCE = 1000.0        # 1000 USDT
RISK_PCT = 2.0                  # 2% per trade
NORMAL_THRESHOLD = 62           # score >= 62 bullish, <= 38 bearish
CRISIS_MAX_HOLD = 72            # crisis max hold = 72 bars (18h on 15m)
NORMAL_MAX_HOLD = 144           # normal max hold = 144 bars (36h on 15m)
COOLDOWN_BARS = 12              # 3 hours cooldown (12 × 15m)
EVAL_INTERVAL = 4               # evaluate signals every 4 bars = 1 hour

CANDLES_PER_HOUR = 4  # 15m bars


# ═══════════════════════════════════════════════════
#  Trade & Stats Dataclasses
# ═══════════════════════════════════════════════════

@dataclass
class Trade:
    side: str           # buy / sell
    entry: float
    exit_price: float
    pnl: float
    pnl_pct: float      # pnl as % of balance at entry
    leverage: int
    bars_held: int
    reason: str          # tp / sl / timeout / end
    score: int = 0
    direction: str = ""


@dataclass
class StrategyResult:
    strategy: str
    symbol: str
    period_days: int
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    roi_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_rr: float = 0.0
    avg_bars_held: float = 0.0
    avg_leverage: float = 0.0
    sharpe_ratio: float = 0.0
    final_balance: float = 0.0
    candles: int = 0
    trades: List = field(default_factory=list)
    equity_curve: List = field(default_factory=list)


# ═══════════════════════════════════════════════════
#  Crisis S5 Strategy — Offline Version
# ═══════════════════════════════════════════════════

def crisis_score_offline(
    closes, highs, lows, opens, volumes, current_price,
    fng_value=50, funding_rate=None, ls_ratio=None,
):
    """
    S5 bidirectional crisis strategy — offline backtest version.
    Returns dict compatible with score_bar output.
    """
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    # 4H trend (subsample 15m → 4H = every 16th bar)
    closes_4h = closes[::16] if len(closes) >= 200 else closes[::4]
    trend_4h = trend_direction(closes_4h, 20, 50)

    # Last 2 candles
    c1_bear = closes[-1] < opens[-1]
    c2_bear = closes[-2] < opens[-2]
    c1_bull = closes[-1] > opens[-1]
    c2_bull = closes[-2] > opens[-2]

    # EMA21
    ema21 = calc_ema(closes[-30:], 21)

    # Determine side
    side = None
    if trend_4h < 0 and c1_bear and c2_bear and current_price < ema21:
        side = "bearish"
    elif trend_4h > 0 and c1_bull and c2_bull and current_price > ema21:
        side = "bullish"
    else:
        return {"score": 50, "direction": "neutral", "breakdown": ["无危机信号"], "atr": 0}

    breakdown = []

    # ATR
    atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    # LL/HH structure
    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows)))
                   if recent_lows[i - 1] < recent_lows[i])
    hh_count = sum(1 for i in range(1, min(5, len(recent_highs)))
                   if recent_highs[i - 1] > recent_highs[i])

    # SL/TP
    tp_mult = 8.0
    if side == "bearish":
        if ll_count >= 4:
            tp_mult = 10.0
        sl = round(current_price + atr * 3.0, 2)
        tp = round(current_price - atr * tp_mult, 2)
    else:
        if hh_count >= 4:
            tp_mult = 10.0
        sl = round(current_price - atr * 3.0, 2)
        tp = round(current_price + atr * tp_mult, 2)

    # Dynamic risk from FNG
    risk_pct = 2.0
    if fng_value <= 10:
        risk_pct += 1.0
    elif fng_value <= 20:
        risk_pct += 0.5
    elif fng_value > 30:
        risk_pct -= 1.0

    if funding_rate is not None:
        if (funding_rate > 0.01 and side == "bearish") or (funding_rate < -0.01 and side == "bullish"):
            risk_pct += 0.5
        elif (funding_rate > 0.01 and side == "bullish") or (funding_rate < -0.01 and side == "bearish"):
            risk_pct -= 0.5

    if ls_ratio is not None:
        if (ls_ratio > 2.0 and side == "bearish") or (ls_ratio < 0.7 and side == "bullish"):
            risk_pct += 0.5
        elif (ls_ratio > 2.0 and side == "bullish") or (ls_ratio < 0.7 and side == "bearish"):
            risk_pct -= 0.5

    risk_pct = max(0.5, min(4.0, risk_pct))

    # Leverage from FNG
    if fng_value <= 15:
        leverage = 3
    elif fng_value <= 25:
        leverage = 2
    else:
        leverage = 1

    # Score
    tech_score = 30 if side == "bearish" else 70
    struct_bonus = ll_count if side == "bearish" else hh_count
    if struct_bonus >= 3:
        tech_score += (-5 if side == "bearish" else 5)
    tech_score = max(0, min(100, tech_score))

    return {
        "score": tech_score,
        "direction": side,
        "breakdown": breakdown,
        "atr": atr,
        "sl": sl,
        "tp": tp,
        "leverage": leverage,
        "risk_pct": risk_pct,
        "market_regime": "crisis",
    }


# ═══════════════════════════════════════════════════
#  PnL Calculator
# ═══════════════════════════════════════════════════

def calc_pnl(side, entry, exit_price, amount, leverage=1):
    """Calculate PnL with leverage."""
    if side == "buy":
        return (exit_price - entry) / entry * amount * leverage
    else:
        return (entry - exit_price) / entry * amount * leverage


# ═══════════════════════════════════════════════════
#  Backtest Runner (generic)
# ═══════════════════════════════════════════════════

async def run_strategy(
    strategy_name: str,
    symbol: str,
    klines: List[Dict],
    fr_lookup: _SortedLookup,
    ls_lookup: _SortedLookup,
    oi_lookup: _SortedLookup,
    ca_liq_lookup=None,
    ca_oi_mc_lookup=None,
    ca_net_lookup=None,
    fng_history: Dict = None,
    start_ms: int = 0,
    period_days: int = 30,
) -> StrategyResult:
    """Generic simulation loop for any strategy."""

    result = StrategyResult(
        strategy=strategy_name, symbol=symbol, period_days=period_days,
        final_balance=INITIAL_BALANCE, candles=len(klines),
    )
    balance = INITIAL_BALANCE
    position = None
    last_trade_idx = -999
    consecutive_losses = 0
    peak_balance = INITIAL_BALANCE

    closes, highs, lows, opens, volumes = [], [], [], [], []
    max_hold = CRISIS_MAX_HOLD if strategy_name == "Crisis_S5" else NORMAL_MAX_HOLD

    for idx, k in enumerate(klines):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])

        if len(closes) < 100 or k["ts"] < start_ms:
            continue

        ts = k["ts"]
        price = k["close"]
        high = k["high"]
        low = k["low"]

        # --- Check existing position ---
        if position:
            sl_hit = (position["side"] == "buy" and low <= position["sl"]) or \
                     (position["side"] == "sell" and high >= position["sl"])
            tp_hit = (position["side"] == "buy" and high >= position["tp"]) or \
                     (position["side"] == "sell" and low <= position["tp"])
            bars_held = idx - position["opened_idx"]

            if bars_held >= max_hold and not tp_hit:
                pnl = calc_pnl(position["side"], position["entry"], price,
                               position["amount"], position["leverage"])
                balance += pnl
                pnl_pct = pnl / position["balance_at_entry"] * 100
                result.trades.append(Trade(
                    side=position["side"], entry=position["entry"],
                    exit_price=price, pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
                    leverage=position["leverage"], bars_held=bars_held,
                    reason="timeout", score=position.get("score", 0),
                    direction=position.get("dir_label", ""),
                ))
                position = None
                last_trade_idx = idx
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0

            elif sl_hit or tp_hit:
                exit_p = position["sl"] if sl_hit else position["tp"]
                pnl = calc_pnl(position["side"], position["entry"], exit_p,
                               position["amount"], position["leverage"])
                balance += pnl
                pnl_pct = pnl / position["balance_at_entry"] * 100
                result.trades.append(Trade(
                    side=position["side"], entry=position["entry"],
                    exit_price=round(exit_p, 2), pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
                    leverage=position["leverage"], bars_held=bars_held,
                    reason="sl" if sl_hit else "tp", score=position.get("score", 0),
                    direction=position.get("dir_label", ""),
                ))
                position = None
                last_trade_idx = idx
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0

            else:
                # Trailing stop (only for Normal strategy)
                if strategy_name != "Crisis_S5":
                    if position["side"] == "buy":
                        dist = abs(position["tp"] - position["entry"])
                        if price >= position["entry"] + dist * 0.4:
                            new_sl = max(position["sl"], position["entry"] + dist * 0.15)
                            position["sl"] = round(new_sl, 2)
                    else:
                        dist = abs(position["entry"] - position["tp"])
                        if price <= position["entry"] - dist * 0.4:
                            new_sl = min(position["sl"], position["entry"] - dist * 0.15)
                            position["sl"] = round(new_sl, 2)

        # Track equity
        equity_val = balance
        if position:
            unrealized = calc_pnl(position["side"], position["entry"], price,
                                  position["amount"], position["leverage"])
            equity_val = balance + unrealized
        result.equity_curve.append(equity_val)

        # Track drawdown
        peak_balance = max(peak_balance, equity_val)
        dd = (peak_balance - equity_val) / peak_balance * 100
        result.max_drawdown_pct = max(result.max_drawdown_pct, dd)

        # Only evaluate at intervals
        if idx % EVAL_INTERVAL != 0:
            continue
        if idx - last_trade_idx < COOLDOWN_BARS:
            continue
        if consecutive_losses >= 3:
            consecutive_losses = 0
            continue
        if position:
            continue
        if balance <= 0:
            continue

        # --- Get auxiliary data ---
        fr_val = fr_lookup.find(ts)
        ls_val = ls_lookup.find(ts)
        oi_curr = oi_lookup.find(ts)
        oi_prev = oi_lookup.find(ts - 3600000)

        fng_value = 50
        if fng_history:
            day_key = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            fng_value = fng_history.get(day_key, 50)

        # --- Score ---
        if strategy_name == "Crisis_S5":
            sig = crisis_score_offline(
                closes, highs, lows, opens, volumes, price,
                fng_value=fng_value, funding_rate=fr_val, ls_ratio=ls_val,
            )
        else:
            # CoinAnk data
            ca_liq_long, ca_liq_short = 0, 0
            ca_oi_mc_val, ca_net_val = None, None
            if ca_liq_lookup:
                liq = ca_liq_lookup.find(ts)
                if liq and isinstance(liq, dict):
                    ca_liq_long = liq.get("longTurnover", 0)
                    ca_liq_short = liq.get("shortTurnover", 0)
            if ca_oi_mc_lookup:
                ca_oi_mc_val = ca_oi_mc_lookup.find(ts)
            if ca_net_lookup:
                ca_net_val = ca_net_lookup.find(ts)

            sig = score_bar(
                closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
                current_price=price,
                funding_rate=fr_val, ls_ratio=ls_val,
                oi_current=oi_curr, oi_prev=oi_prev,
                fng_value=fng_value,
                score_threshold=NORMAL_THRESHOLD,
                ca_liq_long=ca_liq_long, ca_liq_short=ca_liq_short,
                ca_oi_mc=ca_oi_mc_val, ca_net=ca_net_val,
            )

        direction = sig.get("direction", "neutral")
        score = sig.get("score", 50)

        if direction == "neutral":
            continue

        # --- Open position ---
        trade_side = "buy" if direction == "bullish" else "sell"
        lev = sig.get("leverage", 2)
        sl_price = sig.get("sl", price * (0.97 if trade_side == "buy" else 1.03))
        tp_price = sig.get("tp", price * (1.06 if trade_side == "buy" else 0.94))

        # Position sizing: risk-based
        use_risk_pct = sig.get("risk_pct", RISK_PCT)
        risk_amount = balance * use_risk_pct / 100
        sl_dist = abs(price - sl_price)
        if sl_dist <= 0:
            continue
        # Amount in quote (USDT value of position / price)
        pos_value = risk_amount / (sl_dist / price) * lev
        pos_amount = min(pos_value, balance * lev)  # Cap at available margin × leverage

        position = {
            "side": trade_side, "entry": price,
            "amount": pos_amount, "sl": sl_price, "tp": tp_price,
            "leverage": lev, "opened_idx": idx,
            "balance_at_entry": balance, "score": score,
            "dir_label": direction,
        }
        last_trade_idx = idx

    # Close remaining position at last price
    if position:
        pnl = calc_pnl(position["side"], position["entry"], closes[-1],
                        position["amount"], position["leverage"])
        balance += pnl
        pnl_pct = pnl / position["balance_at_entry"] * 100
        bars_held = len(klines) - 1 - position["opened_idx"]
        result.trades.append(Trade(
            side=position["side"], entry=position["entry"],
            exit_price=closes[-1], pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            leverage=position["leverage"], bars_held=bars_held,
            reason="end", score=position.get("score", 0),
            direction=position.get("dir_label", ""),
        ))

    # Compute stats
    result.final_balance = round(balance, 2)
    result.total_trades = len(result.trades)
    wins = [t for t in result.trades if t.pnl > 0]
    losses = [t for t in result.trades if t.pnl <= 0]
    result.wins = len(wins)
    result.losses = len(losses)

    if result.total_trades > 0:
        result.win_rate = round(len(wins) / result.total_trades * 100, 1)
        result.total_pnl = round(sum(t.pnl for t in result.trades), 2)
        result.roi_pct = round(result.total_pnl / INITIAL_BALANCE * 100, 1)
        result.avg_win = round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0
        result.avg_loss = round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0
        total_win_pnl = sum(t.pnl for t in wins)
        total_loss_pnl = abs(sum(t.pnl for t in losses))
        result.profit_factor = round(total_win_pnl / total_loss_pnl, 2) if total_loss_pnl > 0 else 999
        result.avg_bars_held = round(sum(t.bars_held for t in result.trades) / result.total_trades, 1)
        result.avg_leverage = round(sum(t.leverage for t in result.trades) / result.total_trades, 1)

        # Average R:R
        rr_values = []
        for t in result.trades:
            if t.pnl > 0 and result.avg_loss != 0:
                rr_values.append(abs(t.pnl / result.avg_loss))
        result.avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0

        # Sharpe ratio (annualized, based on per-trade returns)
        if len(result.trades) >= 3:
            returns = [t.pnl_pct for t in result.trades]
            mean_r = sum(returns) / len(returns)
            std_r = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5
            if std_r > 0:
                trades_per_year = 365 / period_days * len(result.trades)
                result.sharpe_ratio = round(mean_r / std_r * math.sqrt(trades_per_year), 2)

    result.max_drawdown_pct = round(result.max_drawdown_pct, 1)
    return result


# ═══════════════════════════════════════════════════
#  FNG History Fetcher
# ═══════════════════════════════════════════════════

async def fetch_fng_history(days: int) -> Dict[str, int]:
    """Fetch historical Fear & Greed index."""
    import httpx
    fng = {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.alternative.me/fng/?limit={days + 5}")
            if r.status_code == 200:
                for d in r.json().get("data", []):
                    ts = int(d["timestamp"])
                    date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                    fng[date_str] = int(d["value"])
    except Exception as e:
        logger.warning(f"FNG历史获取失败: {e}")
    return fng


# ═══════════════════════════════════════════════════
#  CoinAnk Lookup Wrapper
# ═══════════════════════════════════════════════════

class DictSortedLookup:
    """Lookup for CoinAnk dict-valued data."""
    def __init__(self, data_dict):
        import bisect
        self.keys = sorted(data_dict.keys())
        self.data = data_dict

    def find(self, target_ts, tolerance_ms=4*3600*1000):
        if not self.keys:
            return None
        import bisect
        idx = bisect.bisect_left(self.keys, target_ts)
        candidates = []
        if idx < len(self.keys):
            candidates.append(self.keys[idx])
        if idx > 0:
            candidates.append(self.keys[idx - 1])
        if not candidates:
            return None
        best = min(candidates, key=lambda t: abs(t - target_ts))
        if abs(best - target_ts) <= tolerance_ms:
            return self.data[best]
        return None


# ═══════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════

async def main():
    fetcher = HistoricalDataFetcher()
    end = datetime.utcnow()
    all_results = []

    print("╔" + "═" * 70 + "╗")
    print("║  PROFESSIONAL BACKTEST: Normal (18-Layer) vs Crisis (S5 Bidi)       ║")
    print("║  Coins: BTC / ETH / SOL  |  Periods: 30d / 90d  |  15m candles     ║")
    print("║  Initial: $1,000  |  Risk: 2%/trade  |  Data: Binance Futures       ║")
    print("╚" + "═" * 70 + "╝")

    # Fetch FNG history (max 90 days)
    print("\n📊 Fetching Fear & Greed Index history...")
    fng_history = await fetch_fng_history(95)
    print(f"   Got {len(fng_history)} days of FNG data")

    for days in PERIODS:
        start = end - timedelta(days=days)
        print(f"\n{'━' * 72}")
        print(f"  📅 PERIOD: {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({days} days)")
        print(f"{'━' * 72}")

        for symbol in SYMBOLS:
            print(f"\n  📈 {symbol} ({days}d)")
            t0 = time.time()

            # Fetch data with lookback for indicators
            lookback_start = start - timedelta(days=15)
            start_ms = int(start.timestamp() * 1000)

            try:
                # Parallel data fetch
                print("    ⏳ Fetching klines + aux data...", end=" ", flush=True)
                klines, fr, ls, oi = await asyncio.gather(
                    fetcher.fetch_klines(symbol, INTERVAL, lookback_start, end),
                    fetcher.fetch_funding_rate(symbol, start, end),
                    fetcher.fetch_long_short_ratio(symbol, start, end),
                    fetcher.fetch_oi_history(symbol, start, end),
                )
                # CoinAnk data (best effort)
                try:
                    ca_liq, ca_oi_mc, ca_net = await asyncio.gather(
                        fetcher.fetch_coinank_liq_history(symbol, start, end),
                        fetcher.fetch_coinank_oi_mc(symbol, start, end),
                        fetcher.fetch_coinank_net_positions(symbol, start, end),
                    )
                except Exception:
                    ca_liq, ca_oi_mc, ca_net = {}, {}, {}

                print(f"{len(klines)} candles | FR={len(fr)} LS={len(ls)} OI={len(oi)}")

                if len(klines) < 200:
                    print(f"    ❌ Insufficient data ({len(klines)} candles), skipping")
                    continue

                fr_lookup = _SortedLookup(fr)
                ls_lookup = _SortedLookup(ls)
                oi_lookup = _SortedLookup(oi)
                ca_liq_lookup = DictSortedLookup(ca_liq)
                ca_oi_mc_lookup = _SortedLookup(ca_oi_mc) if ca_oi_mc else None
                ca_net_lookup = _SortedLookup(ca_net) if ca_net else None

                # Run both strategies on same data
                normal_result = await run_strategy(
                    "Normal_18L", symbol, klines,
                    fr_lookup, ls_lookup, oi_lookup,
                    ca_liq_lookup, ca_oi_mc_lookup, ca_net_lookup,
                    fng_history, start_ms, days,
                )
                crisis_result = await run_strategy(
                    "Crisis_S5", symbol, klines,
                    fr_lookup, ls_lookup, oi_lookup,
                    None, None, None,
                    fng_history, start_ms, days,
                )

                elapsed = time.time() - t0

                # Print comparison
                for r in [normal_result, crisis_result]:
                    pnl_icon = "🟢" if r.total_pnl >= 0 else "🔴"
                    print(f"    {r.strategy:12s} | {r.total_trades:3d} trades | "
                          f"WR {r.win_rate:5.1f}% | "
                          f"{pnl_icon} PnL ${r.total_pnl:>+8.2f} ({r.roi_pct:>+6.1f}%) | "
                          f"DD {r.max_drawdown_pct:5.1f}% | "
                          f"PF {r.profit_factor:5.2f} | "
                          f"Sharpe {r.sharpe_ratio:5.2f}")
                    all_results.append(r)

                print(f"    ⏱️ {elapsed:.1f}s")

            except Exception as e:
                print(f"    ❌ Error: {e}")
                import traceback
                traceback.print_exc()

            await asyncio.sleep(0.5)  # Rate limiting

    # ═══ SUMMARY TABLE ═══
    print(f"\n\n{'═' * 95}")
    print(f"  COMPREHENSIVE COMPARISON RESULTS")
    print(f"{'═' * 95}")
    print(f"{'Strategy':14s} {'Symbol':8s} {'Days':5s} {'Trades':7s} {'WinRate':8s} "
          f"{'PnL($)':10s} {'ROI%':8s} {'MaxDD%':7s} {'PF':6s} {'Sharpe':7s} "
          f"{'AvgLev':7s} {'AvgHold':8s}")
    print(f"{'─' * 95}")

    for r in all_results:
        pnl_mark = "+" if r.total_pnl >= 0 else ""
        print(f"{r.strategy:14s} {r.symbol:8s} {r.period_days:5d} {r.total_trades:7d} "
              f"{r.win_rate:7.1f}% {pnl_mark}{r.total_pnl:>9.2f} "
              f"{pnl_mark}{r.roi_pct:>7.1f}% {r.max_drawdown_pct:6.1f}% "
              f"{r.profit_factor:6.2f} {r.sharpe_ratio:7.2f} "
              f"{r.avg_leverage:6.1f}x {r.avg_bars_held:7.1f}b")

    # ═══ AGGREGATED (per strategy per period) ═══
    print(f"\n{'─' * 95}")
    print(f"  AGGREGATED BY STRATEGY × PERIOD")
    print(f"{'─' * 95}")

    for strat in ["Normal_18L", "Crisis_S5"]:
        for days in PERIODS:
            subset = [r for r in all_results if r.strategy == strat and r.period_days == days]
            if not subset:
                continue
            total_trades = sum(r.total_trades for r in subset)
            total_wins = sum(r.wins for r in subset)
            avg_wr = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0
            avg_roi = round(sum(r.roi_pct for r in subset) / len(subset), 1)
            avg_dd = round(sum(r.max_drawdown_pct for r in subset) / len(subset), 1)
            avg_pf = round(sum(r.profit_factor for r in subset) / len(subset), 2)
            total_pnl = round(sum(r.total_pnl for r in subset), 2)
            avg_sharpe = round(sum(r.sharpe_ratio for r in subset) / len(subset), 2)
            pnl_mark = "+" if total_pnl >= 0 else ""
            print(f"  {strat:14s} {days:3d}d | {total_trades:4d} trades | "
                  f"WR {avg_wr:5.1f}% | "
                  f"Avg ROI {pnl_mark}{avg_roi:.1f}% | "
                  f"Total PnL {pnl_mark}${total_pnl:.2f} | "
                  f"Avg DD {avg_dd:.1f}% | "
                  f"PF {avg_pf:.2f} | "
                  f"Sharpe {avg_sharpe:.2f}")

    # ═══ HEAD-TO-HEAD ═══
    print(f"\n{'─' * 95}")
    print(f"  HEAD-TO-HEAD WINNER")
    print(f"{'─' * 95}")

    for days in PERIODS:
        n_set = [r for r in all_results if r.strategy == "Normal_18L" and r.period_days == days]
        c_set = [r for r in all_results if r.strategy == "Crisis_S5" and r.period_days == days]
        if not n_set or not c_set:
            continue
        n_roi = sum(r.roi_pct for r in n_set) / len(n_set)
        c_roi = sum(r.roi_pct for r in c_set) / len(c_set)
        n_wr = sum(r.win_rate for r in n_set) / len(n_set)
        c_wr = sum(r.win_rate for r in c_set) / len(c_set)
        n_pf = sum(r.profit_factor for r in n_set) / len(n_set)
        c_pf = sum(r.profit_factor for r in c_set) / len(c_set)

        roi_winner = "Normal_18L" if n_roi > c_roi else "Crisis_S5"
        wr_winner = "Normal_18L" if n_wr > c_wr else "Crisis_S5"
        pf_winner = "Normal_18L" if n_pf > c_pf else "Crisis_S5"

        print(f"  {days}d  ROI: {roi_winner} ({n_roi:+.1f}% vs {c_roi:+.1f}%) | "
              f"WinRate: {wr_winner} ({n_wr:.1f}% vs {c_wr:.1f}%) | "
              f"PF: {pf_winner} ({n_pf:.2f} vs {c_pf:.2f})")

    # Save results
    save_data = {
        "config": {
            "initial_balance": INITIAL_BALANCE,
            "risk_pct": RISK_PCT,
            "normal_threshold": NORMAL_THRESHOLD,
            "interval": INTERVAL,
            "symbols": SYMBOLS,
            "periods": PERIODS,
            "run_at": datetime.utcnow().isoformat(),
        },
        "results": []
    }
    for r in all_results:
        rd = {
            "strategy": r.strategy, "symbol": r.symbol, "period_days": r.period_days,
            "total_trades": r.total_trades, "wins": r.wins, "losses": r.losses,
            "win_rate": r.win_rate, "total_pnl": r.total_pnl, "roi_pct": r.roi_pct,
            "max_drawdown_pct": r.max_drawdown_pct, "profit_factor": r.profit_factor,
            "avg_win": r.avg_win, "avg_loss": r.avg_loss,
            "sharpe_ratio": r.sharpe_ratio, "final_balance": r.final_balance,
            "avg_leverage": r.avg_leverage, "avg_bars_held": r.avg_bars_held,
        }
        save_data["results"].append(rd)

    os.makedirs(r"D:\All_in_AI\Trading_system\data", exist_ok=True)
    save_path = r"D:\All_in_AI\Trading_system\data\backtest_compare_results.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 Results saved to {save_path}")

    print(f"\n{'═' * 95}")
    print(f"  BACKTEST COMPLETE")
    print(f"{'═' * 95}")


if __name__ == "__main__":
    asyncio.run(main())
