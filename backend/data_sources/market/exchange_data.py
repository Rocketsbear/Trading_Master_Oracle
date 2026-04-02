"""
多交易所市场数据采集 — Binance, OKX, Bybit, Hyperliquid
提供：多空比（持仓人数）、持仓量(OI)、资金费率
全部使用公共 API，无需 API Key
"""
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None


class ExchangeDataSource:
    """统一多交易所数据采集"""
    
    def __init__(self):
        if not httpx:
            raise ImportError("httpx not installed: pip install httpx")
        self._client: Optional[httpx.AsyncClient] = None
        logger.info("多交易所数据源初始化完成 (Binance/OKX/Bybit/Hyperliquid)")
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client
    
    async def _get(self, url: str, params: dict = None) -> Optional[dict]:
        try:
            client = await self._get_client()
            resp = await client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API 调用失败 [{url}]: {e}")
            return None
    
    async def _post(self, url: str, body: dict) -> Optional[dict]:
        try:
            client = await self._get_client()
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API POST 失败 [{url}]: {e}")
            return None
    
    # ==================== BINANCE ====================
    
    async def binance_long_short_ratio(self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 10) -> Optional[List]:
        """Binance 持仓人数多空比"""
        data = await self._get(
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period, "limit": limit}
        )
        if data and isinstance(data, list):
            return [
                {
                    "long_ratio": float(d.get("longAccount", 0)),
                    "short_ratio": float(d.get("shortAccount", 0)),
                    "long_short_ratio": float(d.get("longShortRatio", 1)),
                    "timestamp": int(d.get("timestamp", 0)),
                }
                for d in data
            ]
        return None
    
    async def binance_open_interest(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """Binance 持仓量"""
        data = await self._get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            {"symbol": symbol}
        )
        if data:
            return {
                "oi": float(data.get("openInterest", 0)),
                "symbol": data.get("symbol"),
            }
        return None
    
    async def binance_oi_history(self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 12) -> Optional[List]:
        """Binance OI 历史 (用于监控变化趋势)"""
        data = await self._get(
            "https://fapi.binance.com/futures/data/openInterestHist",
            {"symbol": symbol, "period": period, "limit": limit}
        )
        if data and isinstance(data, list):
            return [
                {
                    "oi": float(d.get("sumOpenInterest", 0)),
                    "oi_value_usd": float(d.get("sumOpenInterestValue", 0)),
                    "timestamp": int(d.get("timestamp", 0)),
                }
                for d in data
            ]
        return None
    
    async def binance_funding_rate(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """Binance 资金费率"""
        data = await self._get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": 1}
        )
        if data and isinstance(data, list) and len(data) > 0:
            return {"funding_rate": float(data[0].get("fundingRate", 0))}
        return None
    
    # ==================== OKX ====================
    
    async def okx_long_short_ratio(self, ccy: str = "BTC", period: str = "1H") -> Optional[List]:
        """OKX 合约持仓人数多空比"""
        data = await self._get(
            "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": ccy, "period": period}
        )
        if data and data.get("code") == "0" and data.get("data"):
            results = []
            for d in data["data"]:
                # OKX format: [timestamp, ratio] where ratio = long/short
                if len(d) >= 2:
                    ts = int(d[0])
                    ratio = float(d[1])
                    # Convert ratio to percentages: ratio = L/S, L + S = 1
                    # L = ratio * S, L + S = 1 → S = 1/(1+ratio), L = ratio/(1+ratio)
                    long_pct = ratio / (1 + ratio) if ratio > 0 else 0.5
                    short_pct = 1 / (1 + ratio) if ratio > 0 else 0.5
                    results.append({
                        "long_ratio": long_pct,
                        "short_ratio": short_pct,
                        "long_short_ratio": ratio,
                        "timestamp": ts,
                    })
            return results if results else None
        return None
    
    async def okx_open_interest(self, inst_id: str = "BTC-USDT-SWAP") -> Optional[Dict]:
        """OKX 持仓量"""
        data = await self._get(
            "https://www.okx.com/api/v5/public/open-interest",
            {"instType": "SWAP", "instId": inst_id}
        )
        if data and data.get("code") == "0" and data.get("data"):
            d = data["data"][0]
            return {
                "oi": float(d.get("oi", 0)),
                "oi_ccy": float(d.get("oiCcy", 0)),
            }
        return None
    
    async def okx_funding_rate(self, inst_id: str = "BTC-USDT-SWAP") -> Optional[Dict]:
        """OKX 资金费率"""
        data = await self._get(
            "https://www.okx.com/api/v5/public/funding-rate",
            {"instId": inst_id}
        )
        if data and data.get("code") == "0" and data.get("data"):
            d = data["data"][0]
            return {
                "funding_rate": float(d.get("fundingRate", 0)),
                "next_funding_rate": float(d.get("nextFundingRate", 0)) if d.get("nextFundingRate") else None,
            }
        return None
    
    # ==================== BYBIT ====================
    
    async def bybit_long_short_ratio(self, symbol: str = "BTCUSDT", period: str = "1h") -> Optional[List]:
        """Bybit 持仓人数多空比"""
        data = await self._get(
            "https://api.bybit.com/v5/market/account-ratio",
            {"category": "linear", "symbol": symbol, "period": period, "limit": 10}
        )
        if data and data.get("retCode") == 0 and data.get("result", {}).get("list"):
            return [
                {
                    "long_ratio": float(d.get("buyRatio", 0)),
                    "short_ratio": float(d.get("sellRatio", 0)),
                    "long_short_ratio": float(d.get("buyRatio", 0.5)) / float(d.get("sellRatio", 0.5)) if float(d.get("sellRatio", 0)) > 0 else 1,
                    "timestamp": int(d.get("timestamp", 0)),
                }
                for d in data["result"]["list"]
            ]
        return None
    
    async def bybit_open_interest(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 12) -> Optional[List]:
        """Bybit 持仓量（含历史）"""
        data = await self._get(
            "https://api.bybit.com/v5/market/open-interest",
            {"category": "linear", "symbol": symbol, "intervalTime": interval, "limit": limit}
        )
        if data and data.get("retCode") == 0 and data.get("result", {}).get("list"):
            return [
                {
                    "oi": float(d.get("openInterest", 0)),
                    "timestamp": int(d.get("timestamp", 0)),
                }
                for d in data["result"]["list"]
            ]
        return None
    
    async def bybit_funding_rate(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """Bybit 资金费率"""
        data = await self._get(
            "https://api.bybit.com/v5/market/funding/history",
            {"category": "linear", "symbol": symbol, "limit": 1}
        )
        if data and data.get("retCode") == 0 and data.get("result", {}).get("list"):
            d = data["result"]["list"][0]
            return {"funding_rate": float(d.get("fundingRate", 0))}
        return None
    
    # ==================== HYPERLIQUID ====================
    
    async def hyperliquid_meta(self) -> Optional[Dict]:
        """Hyperliquid 元数据 + 资产上下文 (OI, funding)"""
        data = await self._post(
            "https://api.hyperliquid.xyz/info",
            {"type": "metaAndAssetCtxs"}
        )
        if data and isinstance(data, list) and len(data) >= 2:
            return {
                "meta": data[0],       # universe (资产列表)
                "asset_ctxs": data[1],  # 资产上下文 (OI, funding, price)
            }
        return None
    
    async def hyperliquid_oi_and_funding(self, coin: str = "BTC") -> Optional[Dict]:
        """Hyperliquid 特定币种的 OI + 资金费率"""
        meta = await self.hyperliquid_meta()
        if not meta:
            return None
        
        universe = meta.get("meta", {}).get("universe", [])
        ctxs = meta.get("asset_ctxs", [])
        
        for i, asset in enumerate(universe):
            if asset.get("name", "").upper() == coin.upper() and i < len(ctxs):
                ctx = ctxs[i]
                return {
                    "oi": float(ctx.get("openInterest", 0)),
                    "funding_rate": float(ctx.get("funding", 0)),
                    "mark_price": float(ctx.get("markPx", 0)),
                    "volume_24h": float(ctx.get("dayNtlVlm", 0)),
                }
        return None
    
    # ==================== 综合接口 ====================
    
    def _symbol_to_parts(self, symbol: str):
        """BTCUSDT → BTC, BTC-USDT-SWAP, etc."""
        coin = symbol.replace("USDT", "").replace("USD", "")
        return {
            "binance": symbol,
            "okx_ccy": coin,
            "okx_inst": f"{coin}-USDT-SWAP",
            "bybit": symbol,
            "hl_coin": coin,
        }
    
    async def get_comprehensive_exchange_data(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """
        综合多交易所数据采集 — 全部并行
        返回：多空比(3所) + OI(4所) + 资金费率(4所) + OI历史变化
        """
        parts = self._symbol_to_parts(symbol)
        
        # 并行发起所有请求
        tasks = {
            # 多空比 (Binance, OKX, Bybit)
            "bn_ls": self.binance_long_short_ratio(parts["binance"]),
            "okx_ls": self.okx_long_short_ratio(parts["okx_ccy"]),
            "bybit_ls": self.bybit_long_short_ratio(parts["bybit"]),
            # OI (4所)
            "bn_oi": self.binance_open_interest(parts["binance"]),
            "bn_oi_hist": self.binance_oi_history(parts["binance"]),
            "okx_oi": self.okx_open_interest(parts["okx_inst"]),
            "bybit_oi": self.bybit_open_interest(parts["bybit"]),
            "hl_oi": self.hyperliquid_oi_and_funding(parts["hl_coin"]),
            # 资金费率 (4所)
            "bn_fr": self.binance_funding_rate(parts["binance"]),
            "okx_fr": self.okx_funding_rate(parts["okx_inst"]),
            "bybit_fr": self.bybit_funding_rate(parts["bybit"]),
        }
        
        keys = list(tasks.keys())
        values = await asyncio.gather(*tasks.values(), return_exceptions=True)
        raw = {}
        for k, v in zip(keys, values):
            raw[k] = v if not isinstance(v, Exception) else None
        
        # ---- 整理多空比 ----
        long_short_ratios = {}
        for name, key in [("binance", "bn_ls"), ("okx", "okx_ls"), ("bybit", "bybit_ls")]:
            data = raw.get(key)
            if data and len(data) > 0:
                latest = data[0]  # 最新一条
                long_short_ratios[name] = {
                    "long_pct": round(latest["long_ratio"] * 100, 1) if latest["long_ratio"] <= 1 else round(latest["long_ratio"], 1),
                    "short_pct": round(latest["short_ratio"] * 100, 1) if latest["short_ratio"] <= 1 else round(latest["short_ratio"], 1),
                    "ratio": round(latest["long_short_ratio"], 3),
                }
        
        # 计算平均多空比
        avg_long_pct = None
        if long_short_ratios:
            longs = [v["long_pct"] for v in long_short_ratios.values()]
            avg_long_pct = round(sum(longs) / len(longs), 1)
        
        # ---- 整理 OI ----
        open_interests = {}
        bn_oi = raw.get("bn_oi")
        if bn_oi:
            open_interests["binance"] = bn_oi.get("oi", 0)
        
        okx_oi = raw.get("okx_oi")
        if okx_oi:
            open_interests["okx"] = okx_oi.get("oi_ccy", okx_oi.get("oi", 0))
        
        bybit_oi_data = raw.get("bybit_oi")
        if bybit_oi_data and isinstance(bybit_oi_data, list) and len(bybit_oi_data) > 0:
            open_interests["bybit"] = bybit_oi_data[0].get("oi", 0)
        
        hl_data = raw.get("hl_oi")
        if hl_data:
            open_interests["hyperliquid"] = hl_data.get("oi", 0)
        
        # ---- OI 变化趋势 (Binance 历史) ----
        oi_change = None
        oi_trend = "unknown"
        bn_oi_hist = raw.get("bn_oi_hist")
        if bn_oi_hist and len(bn_oi_hist) >= 2:
            latest_oi = bn_oi_hist[0]["oi_value_usd"]
            oldest_oi = bn_oi_hist[-1]["oi_value_usd"]
            if oldest_oi > 0:
                oi_change = round((latest_oi - oldest_oi) / oldest_oi * 100, 2)
                if oi_change > 5:
                    oi_trend = "increasing"
                elif oi_change < -5:
                    oi_trend = "decreasing"
                else:
                    oi_trend = "stable"
        
        # ---- 整理资金费率 ----
        funding_rates = {}
        for name, key in [("binance", "bn_fr"), ("okx", "okx_fr"), ("bybit", "bybit_fr")]:
            fr = raw.get(key)
            if fr:
                funding_rates[name] = fr.get("funding_rate", 0)
        if hl_data:
            funding_rates["hyperliquid"] = hl_data.get("funding_rate", 0)
        
        avg_funding = None
        if funding_rates:
            rates = list(funding_rates.values())
            avg_funding = round(sum(rates) / len(rates), 6)
        
        # 成功统计
        ls_count = len(long_short_ratios)
        oi_count = len(open_interests)
        fr_count = len(funding_rates)
        logger.info(f"多交易所数据: 多空比{ls_count}所, OI{oi_count}所, 费率{fr_count}所")
        
        return {
            "source": "multi_exchange_real_data",
            "long_short_ratios": long_short_ratios,
            "avg_long_pct": avg_long_pct,
            "open_interests": open_interests,
            "oi_change_pct": oi_change,
            "oi_trend": oi_trend,
            "funding_rates": funding_rates,
            "avg_funding_rate": avg_funding,
            "exchanges_count": {"ls": ls_count, "oi": oi_count, "fr": fr_count},
        }
    # ==================== K-LINE DATA ====================
    
    # Interval mappings for each exchange
    _BINANCE_INTERVALS = {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d","1w":"1w"}
    _OKX_INTERVALS = {"1m":"1m","5m":"5m","15m":"15m","1h":"1H","4h":"4H","1d":"1D","1w":"1W"}
    _BYBIT_INTERVALS = {"1m":"1","5m":"5","15m":"15","1h":"60","4h":"240","1d":"D","1w":"W"}
    
    @staticmethod
    def _parse_kline_array(data_list):
        """通用 K线数组解析 (Binance 格式: [ts, o, h, l, c, vol, ...])"""
        return [
            {"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in data_list
        ]
    
    async def binance_klines(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200, market_type: str = "futures") -> Optional[List]:
        """Binance K线获取"""
        # Map standardized symbols to Binance Futures 1000x symbols
        if market_type == "futures":
            meme_1000x = ["PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT", "SATSUSDT", "LUNCUSDT", "RATSUSDT", "XECUSDT", "MOGUSDT", "CATIUSDT"]
            if symbol in meme_1000x:
                symbol = f"1000{symbol}"
                
        bar = self._BINANCE_INTERVALS.get(interval, "1h")
        base_url = "https://fapi.binance.com" if market_type == "futures" else "https://api.binance.com"
        endpoint = "/fapi/v1/klines" if market_type == "futures" else "/api/v3/klines"
        url = f"{base_url}{endpoint}"
        params = {"symbol": symbol, "interval": bar, "limit": limit}
        data = await self._get(url, params)
        if data and isinstance(data, list):
            return self._parse_kline_array(data)
        return None
    
    async def okx_klines(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200, market_type: str = "spot") -> Optional[List]:
        """OKX K线 (现货 or 永续合约)"""
        coin = symbol.replace("USDT", "").replace("USD", "")
        if market_type == "futures":
            inst_id = f"{coin}-USDT-SWAP"
        else:
            inst_id = f"{coin}-USDT"
        bar = self._OKX_INTERVALS.get(interval, "1H")
        data = await self._get(
            "https://www.okx.com/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": str(min(limit, 300))}
        )
        if data and data.get("code") == "0" and data.get("data"):
            candles = self._parse_kline_array(data["data"])
            candles.reverse()  # OKX returns newest first
            return candles
        return None
    
    async def bybit_klines(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200, market_type: str = "spot") -> Optional[List]:
        """Bybit K线 (现货 or 合约)"""
        bar = self._BYBIT_INTERVALS.get(interval, "60")
        category = "linear" if market_type == "futures" else "spot"
        data = await self._get(
            "https://api.bybit.com/v5/market/kline",
            {"category": category, "symbol": symbol, "interval": bar, "limit": limit}
        )
        if data and data.get("retCode") == 0 and data.get("result", {}).get("list"):
            candles = [
                {"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                for k in data["result"]["list"]
            ]
            candles.reverse()  # Bybit returns newest first
            return candles
        return None
    
    async def hyperliquid_klines(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200, market_type: str = "futures") -> Optional[List]:
        """Hyperliquid K线 (仅永续合约)"""
        coin = symbol.replace("USDT", "").replace("USD", "")
        interval_secs = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
        secs = interval_secs.get(interval, 3600)
        
        import time
        end_time = int(time.time() * 1000)
        start_time = end_time - (limit * secs * 1000)
        
        data = await self._post(
            "https://api.hyperliquid.xyz/info",
            {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": start_time, "endTime": end_time}}
        )
        if data and isinstance(data, list):
            return [
                {"time": int(k.get("t", 0)) // 1000, "open": float(k.get("o", 0)), "high": float(k.get("h", 0)),
                 "low": float(k.get("l", 0)), "close": float(k.get("c", 0)), "volume": float(k.get("v", 0))}
                for k in data
            ]
        return None
    
    async def get_klines(self, exchange: str, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200, market_type: str = "spot") -> Optional[List]:
        """统一 K线接口 — 根据 exchange + market_type 分发"""
        methods = {
            "binance": self.binance_klines,
            "okx": self.okx_klines,
            "bybit": self.bybit_klines,
            "hyperliquid": self.hyperliquid_klines,
        }
        method = methods.get(exchange.lower())
        if method:
            # Hyperliquid 只有永续合约
            mt = "futures" if exchange.lower() == "hyperliquid" else market_type
            return await method(symbol, interval, limit, mt)
        return None

    # ==================== DYNAMIC MARKET RADAR ====================
    async def get_top_volume_symbols(self, limit: int = 10) -> List[str]:
        """
        全平台热力雷达：聚合 Binance, OKX, Bybit, Hyperliquid 的 24h 交易量
        返回：去重后的 Top N 高迷度活跃山寨币 (格式如 BTCUSDT)
        """
        # 存放每个币种的总交易额 {"BTCUSDT": 50000000.0, "SOLUSDT": ...}
        aggregated_volumes = {}
        
        async def fetch_binance():
            try:
                data = await self._get("https://fapi.binance.com/fapi/v1/ticker/24hr")
                if data and isinstance(data, list):
                    for t in data:
                        sym = t.get("symbol", "")
                        if sym.endswith("USDT") and not sym.startswith("USDC"):
                            norm_sym = sym
                            # Normalize 1000x meme coins to base name for cross-exchange aggregation
                            if sym.startswith("1000") and len(sym) >= 8:
                                norm_sym = sym.replace("1000", "", 1)
                            vol = float(t.get("quoteVolume", 0))
                            aggregated_volumes[norm_sym] = aggregated_volumes.get(norm_sym, 0) + vol
            except Exception as e:
                logger.warning(f"Radar Binance Error: {e}")

        # 2. OKX Swap Tickers
        async def fetch_okx():
            try:
                data = await self._get("https://www.okx.com/api/v5/market/tickers", {"instType": "SWAP"})
                if data and data.get("code") == "0" and data.get("data"):
                    for t in data["data"]:
                        inst = t.get("instId", "")
                        if inst.endswith("-USDT-SWAP"):
                            sym = inst.replace("-USDT-SWAP", "USDT")
                            # OKX volCcy24h is in quote currency
                            vol = float(t.get("volCcy24h", 0))
                            aggregated_volumes[sym] = aggregated_volumes.get(sym, 0) + vol
            except Exception as e:
                logger.warning(f"Radar OKX Error: {e}")

        # 3. Bybit Linear Tickers
        async def fetch_bybit():
            try:
                data = await self._get("https://api.bybit.com/v5/market/tickers", {"category": "linear"})
                if data and data.get("retCode") == 0 and data.get("result", {}).get("list"):
                    for t in data["result"]["list"]:
                        sym = t.get("symbol", "")
                        if sym.endswith("USDT") and not sym.startswith("USDC"):
                            vol = float(t.get("turnover24h", 0))
                            aggregated_volumes[sym] = aggregated_volumes.get(sym, 0) + vol
            except Exception as e:
                logger.warning(f"Radar Bybit Error: {e}")
                
        # 4. Hyperliquid Meta
        async def fetch_hl():
            try:
                meta = await self.hyperliquid_meta()
                if meta:
                    universe = meta.get("meta", {}).get("universe", [])
                    ctxs = meta.get("asset_ctxs", [])
                    for i, asset in enumerate(universe):
                        if i < len(ctxs):
                            coin = asset.get("name", "")
                            if coin:
                                sym = f"{coin}USDT"
                                vol = float(ctxs[i].get("dayNtlVlm", 0))
                                aggregated_volumes[sym] = aggregated_volumes.get(sym, 0) + vol
            except Exception as e:
                logger.warning(f"Radar HL Error: {e}")

        # 并行拉取
        await asyncio.gather(fetch_binance(), fetch_okx(), fetch_bybit(), fetch_hl())
        
        # 过滤与排序
        # 过滤稳定币和一些异常对
        blacklist = {"USDCUSDT", "BTCSTUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT", "EURUSDT"}
        sorted_pairs = sorted(
            [(sym, vol) for sym, vol in aggregated_volumes.items() if sym not in blacklist],
            key=lambda x: x[1], 
            reverse=True
        )
        
        # 提取 Symbol
        top_symbols = [p[0] for p in sorted_pairs[:limit]]
        logger.info(f"动态雷达 (多所聚合) 探测到 Top {limit} 活跃货币: {', '.join(top_symbols)}")
        return top_symbols
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
