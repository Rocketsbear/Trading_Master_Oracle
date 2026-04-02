"""
链上数据集成模块 — OnchainOS v6 REST API + OKX CEX API
真实链上数据: DEX交易, 聪明钱信号, 聚合价格, Token信息
"""
import asyncio
import hashlib
import hmac
import base64
import time
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None

# ===== API Endpoints =====
ONCHAINOS_BASE = "https://web3.okx.com/api/v6/dex/market"
OKX_CEX_BASE = "https://www.okx.com/api/v5"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Token address mappings (chain → address)
TOKEN_MAP = {
    "BTC": {
        "coingecko": "bitcoin",
        "chains": {
            "1": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC on Ethereum
        }
    },
    "ETH": {
        "coingecko": "ethereum",
        "chains": {
            "1": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",  # Native ETH
        }
    },
    "SOL": {
        "coingecko": "solana",
        "chains": {
            "501": "So11111111111111111111111111111111111111112",  # wSOL
        }
    },
}

# Signal chains that OnchainOS supports
SIGNAL_CHAINS = {"1": "ethereum", "501": "solana", "8453": "base", "56": "bsc", "42161": "arbitrum"}


class OnchainDataSource:
    """链上数据源 — OnchainOS v6 + OKX CEX REST API"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", passphrase: str = ""):
        if not httpx:
            logger.warning("httpx not installed, onchain data will be limited")
        self._client: Optional[httpx.AsyncClient] = None
        
        # OnchainOS API credentials
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._has_onchainos_keys = bool(api_key and api_secret and passphrase)
        
        if self._has_onchainos_keys:
            logger.info("✅ OnchainOS API 已配置 (真实链上数据)")
        else:
            logger.info("⚠️ OnchainOS API 未配置 — 聪明钱信号/DEX交易将使用CEX数据替代")
        
        logger.info("链上数据源初始化完成 (OnchainOS v6 + OKX CEX)")
    
    async def _get_client(self) -> Optional[httpx.AsyncClient]:
        if not httpx:
            return None
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        return self._client
    
    # ===== OnchainOS HMAC Signing =====
    def _sign_request(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """Generate signed headers for OnchainOS v6 API"""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        
        # HMAC SHA256 sign: timestamp + METHOD + path + body
        prehash_string = timestamp + method.upper() + request_path + body
        signature = base64.b64encode(
            hmac.new(
                self._api_secret.encode("utf-8"),
                prehash_string.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode("utf-8")
        
        return {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
    
    async def _signed_request(self, method: str, full_url: str, sign_path: str,
                              params: dict = None, body: Any = None) -> dict:
        """Generic signed request for any OnchainOS endpoint"""
        if not self._has_onchainos_keys:
            return {}
        try:
            client = await self._get_client()
            if not client:
                return {}
            
            body_str = json.dumps(body) if body is not None else ""
            headers = self._sign_request(method.upper(), sign_path,
                                          body_str if method.upper() == "POST" else "")
            
            if method.upper() == "GET":
                resp = await client.get(full_url, params=params or {}, headers=headers)
            else:
                resp = await client.post(full_url, content=body_str, headers=headers)
            
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "0":
                return data
            logger.warning(f"OnchainOS {method} {sign_path} error: code={data.get('code')}, msg={data.get('msg')}")
            return {}
        except Exception as e:
            logger.warning(f"OnchainOS {method} {sign_path} failed: {e}")
            return {}
    
    async def _onchainos_get(self, path: str, params: dict = None) -> dict:
        """OnchainOS v6 GET /dex/market/* — sign path WITHOUT query params"""
        sign_path = f"/api/v6/dex/market{path}"
        url = f"{ONCHAINOS_BASE}{path}"
        return await self._signed_request("GET", url, sign_path, params=params)
    
    async def _onchainos_post(self, path: str, body: Any = None) -> dict:
        """OnchainOS v6 POST /dex/market/*"""
        sign_path = f"/api/v6/dex/market{path}"
        url = f"{ONCHAINOS_BASE}{path}"
        return await self._signed_request("POST", url, sign_path, body=body)
    
    async def _cex_get(self, url: str, params: dict = None) -> dict:
        """Simple GET for OKX CEX or CoinGecko (no signing needed)"""
        try:
            client = await self._get_client()
            if not client:
                return {}
            resp = await client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"CEX API failed [{url}]: {e}")
            return {}
    
    def _resolve_token(self, symbol: str) -> dict:
        """BTCUSDT → token info"""
        coin = symbol.replace("USDT", "").replace("USD", "").upper()
        return TOKEN_MAP.get(coin, TOKEN_MAP.get("ETH"))
    
    # ===== 1. DEX 交易数据 (OnchainOS) =====
    async def get_dex_trades(self, symbol: str, chain: str = "1", limit: int = 50) -> Dict:
        """获取真实 DEX 链上交易数据"""
        token = self._resolve_token(symbol)
        chain_id = chain
        address = token.get("chains", {}).get(chain_id)
        
        if not address:
            return {"total_trades": 0, "buys": 0, "sells": 0, "buy_ratio": 50, "total_volume_usd": 0}
        
        data = await self._onchainos_get("/trades", {
            "chainIndex": chain_id,
            "tokenContractAddress": address,
            "limit": str(limit),
        })
        
        if not data or not data.get("data"):
            return {"total_trades": 0, "buys": 0, "sells": 0, "buy_ratio": 50, "total_volume_usd": 0}
        
        trades = data["data"]
        buys = sum(1 for t in trades if t.get("type") == "buy")
        sells = sum(1 for t in trades if t.get("type") == "sell")
        total = len(trades)
        total_vol = sum(float(t.get("volume", 0)) for t in trades)
        buy_ratio = (buys / total * 100) if total > 0 else 50
        
        # 提取最大交易
        top_trades = sorted(trades, key=lambda t: float(t.get("volume", 0)), reverse=True)[:5]
        top_list = [{
            "type": t.get("type"),
            "volume_usd": float(t.get("volume", 0)),
            "dex": t.get("dexName", "unknown"),
            "wallet": t.get("userAddress", "")[:8] + "...",
        } for t in top_trades]
        
        return {
            "total_trades": total,
            "buys": buys,
            "sells": sells,
            "buy_ratio": round(buy_ratio, 1),
            "total_volume_usd": round(total_vol, 2),
            "top_trades": top_list,
            "source": "OnchainOS DEX",
        }
    
    # ===== 2. 聪明钱信号 (OnchainOS Signal API) =====
    async def get_smart_money_signals(self, chain_ids: List[str] = None) -> Dict:
        """获取真实聪明钱/鲸鱼/KOL信号"""
        if chain_ids is None:
            chain_ids = ["1", "501"]  # Ethereum + Solana
        
        all_signals = []
        smart_money_count = 0
        whale_count = 0
        kol_count = 0
        total_amount = 0
        
        for chain_id in chain_ids:
            body = [{
                "chainIndex": chain_id,
                "walletType": "1,2,3",  # Smart Money + KOL + Whale
                "minAmountUsd": "500",
            }]
            
            data = await self._onchainos_post("/signal/list", body)
            
            if data and data.get("data"):
                for sig in data["data"]:
                    wt = sig.get("walletType", "")
                    amount = float(sig.get("amountUsd", 0))
                    total_amount += amount
                    
                    if wt == "1":  # Smart Money
                        smart_money_count += 1
                    elif wt == "2":  # KOL
                        kol_count += 1
                    elif wt == "3":  # Whale
                        whale_count += 1
                    
                    all_signals.append({
                        "wallet_type": {"1": "SMART_MONEY", "2": "KOL", "3": "WHALE"}.get(wt, wt),
                        "amount_usd": amount,
                        "chain": SIGNAL_CHAINS.get(chain_id, chain_id),
                        "token_symbol": sig.get("token", {}).get("symbol", "?"),
                        "token_address": sig.get("token", {}).get("tokenAddress", ""),
                        "market_cap": float(sig.get("token", {}).get("marketCapUsd", 0)),
                        "holders": int(sig.get("token", {}).get("holders", 0)),
                        "top10_pct": float(sig.get("token", {}).get("top10HolderPercent", 0)),
                        "sold_ratio": float(sig.get("soldRatioPercent", 0)),
                        "trigger_wallets": int(sig.get("triggerWalletCount", 0)),
                        "timestamp": sig.get("timestamp", ""),
                    })
        
        # Sort by amount, take top signals
        all_signals.sort(key=lambda s: s["amount_usd"], reverse=True)
        
        return {
            "total_signals": len(all_signals),
            "smart_money_count": smart_money_count,
            "whale_count": whale_count,
            "kol_count": kol_count,
            "total_amount_usd": round(total_amount, 2),
            "top_signals": all_signals[:10],
            "source": "OnchainOS Signal API",
        }
    
    # ===== 3. Index Price (抗操纵聚合价格) =====
    async def get_index_price(self, symbol: str) -> Dict:
        """获取多源聚合抗操纵价格 (CEX+DEX+Oracle)"""
        token = self._resolve_token(symbol)
        # Index Price API lives at /api/v6/dex/index/ (NOT /dex/market/index/)
        for chain_id, address in token.get("chains", {}).items():
            body = [{"chainIndex": chain_id, "tokenContractAddress": address}]
            url = "https://web3.okx.com/api/v6/dex/index/current-price"
            sign_path = "/api/v6/dex/index/current-price"
            data = await self._signed_request("POST", url, sign_path, body=body)
            
            if data and data.get("data"):
                entry = data["data"][0] if isinstance(data["data"], list) else data["data"]
                return {
                    "index_price": float(entry.get("price", 0)),
                    "chain": chain_id,
                    "source": "OnchainOS Index (CEX+DEX+Oracle)",
                }
        
        return {}
    
    # ===== 4. 链上价格 (DEX Market Price) =====
    async def get_dex_price(self, symbol: str) -> Dict:
        """获取链上DEX聚合价格"""
        token = self._resolve_token(symbol)
        for chain_id, address in token.get("chains", {}).items():
            body = [{"chainIndex": chain_id, "tokenContractAddress": address}]
            data = await self._onchainos_post("/price", body)
            
            if data and data.get("data"):
                entry = data["data"][0] if isinstance(data["data"], list) else data["data"]
                return {
                    "price": float(entry.get("price", 0)),
                    "chain": chain_id,
                    "source": "OnchainOS DEX",
                }
        
        return {}
    
    # ===== 5. CoinGecko Token Price (免费后备) =====
    async def get_token_price(self, symbol: str) -> Dict:
        """获取代币价格 (CoinGecko — 无需API Key)"""
        token = self._resolve_token(symbol)
        data = await self._cex_get(
            f"{COINGECKO_BASE}/simple/price",
            {"ids": token["coingecko"], "vs_currencies": "usd", "include_24hr_change": "true",
             "include_24hr_vol": "true", "include_market_cap": "true"}
        )
        if data and token["coingecko"] in data:
            info = data[token["coingecko"]]
            return {
                "price": info.get("usd", 0),
                "change_24h": info.get("usd_24h_change", 0),
                "volume_24h": info.get("usd_24h_vol", 0),
                "market_cap": info.get("usd_market_cap", 0),
            }
        return {"price": 0, "change_24h": 0, "volume_24h": 0, "market_cap": 0}
    
    # ===== 6. OKX CEX 衍生品数据 =====
    async def get_funding_and_oi(self, symbol: str) -> Dict:
        """获取 OKX 合约资金费率 + OI"""
        coin = symbol.replace("USDT", "").replace("USD", "").upper()
        inst_id = f"{coin}-USDT-SWAP"
        
        fr_data = await self._cex_get(f"{OKX_CEX_BASE}/public/funding-rate", {"instId": inst_id})
        funding_rate = 0
        if fr_data.get("code") == "0" and fr_data.get("data"):
            funding_rate = float(fr_data["data"][0].get("fundingRate", 0))
        
        oi_data = await self._cex_get(f"{OKX_CEX_BASE}/public/open-interest",
                                       {"instType": "SWAP", "instId": inst_id})
        oi = 0
        if oi_data.get("code") == "0" and oi_data.get("data"):
            oi = float(oi_data["data"][0].get("oiCcy", 0))
        
        return {"funding_rate": funding_rate, "open_interest": oi}
    
    # ===== 7. OKX CEX 多空比 =====
    async def get_long_short_ratio(self, symbol: str) -> Dict:
        """获取 OKX 多空比"""
        coin = symbol.replace("USDT", "").replace("USD", "").upper()
        data = await self._cex_get(
            f"{OKX_CEX_BASE}/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": coin, "period": "1H"}
        )
        if data.get("code") == "0" and data.get("data") and len(data["data"]) > 0:
            latest = data["data"][0]
            ratio = float(latest[1]) if len(latest) >= 2 else 1.0
            long_pct = ratio / (1 + ratio) * 100 if ratio > 0 else 50
            return {"long_pct": round(long_pct, 1), "short_pct": round(100 - long_pct, 1), "ratio": round(ratio, 3)}
        return {"long_pct": 50, "short_pct": 50, "ratio": 1.0}
    
    # ===== 综合数据 (Agent 用) =====
    async def get_comprehensive_onchain_data(self, symbol: str) -> Dict:
        """获取综合链上数据（用于 Agent 分析）"""
        # 并行获取所有数据
        tasks = {
            "price": self.get_token_price(symbol),
            "funding_oi": self.get_funding_and_oi(symbol),
            "ls_ratio": self.get_long_short_ratio(symbol),
        }
        
        # OnchainOS 数据 (需要 API key)
        if self._has_onchainos_keys:
            tasks["dex_trades"] = self.get_dex_trades(symbol)
            tasks["signals"] = self.get_smart_money_signals()
            tasks["index_price"] = self.get_index_price(symbol)
        
        keys = list(tasks.keys())
        values = await asyncio.gather(*tasks.values(), return_exceptions=True)
        raw = {}
        for k, v in zip(keys, values):
            raw[k] = v if not isinstance(v, Exception) else {}
        
        price_data = raw.get("price", {})
        funding_oi = raw.get("funding_oi", {})
        ls_ratio = raw.get("ls_ratio", {})
        
        # DEX trades — 真实 OnchainOS 数据 or CEX 替代
        dex_trades = raw.get("dex_trades", {})
        if dex_trades and dex_trades.get("total_trades", 0) > 0:
            trades_data = dex_trades
        else:
            # Fallback: 用多空比估算 (与之前一致)
            buy_ratio = ls_ratio.get("long_pct", 50)
            trades_data = {
                "total_trades": 0,
                "buys": 0,
                "sells": 0,
                "buy_ratio": buy_ratio,
                "total_volume_usd": price_data.get("volume_24h", 0),
                "source": "CEX L/S ratio (fallback)",
            }
        
        # Signals — 真实 OnchainOS 数据 or 空
        signals_raw = raw.get("signals", {})
        signals_data = {
            "total_signals": signals_raw.get("total_signals", 0),
            "smart_money_count": signals_raw.get("smart_money_count", 0),
            "whale_count": signals_raw.get("whale_count", 0),
            "kol_count": signals_raw.get("kol_count", 0),
            "total_amount_usd": signals_raw.get("total_amount_usd", 0),
            "top_signals": signals_raw.get("top_signals", []),
            "funding_rate": funding_oi.get("funding_rate", 0),
            "open_interest": funding_oi.get("open_interest", 0),
            "ls_ratio": ls_ratio,
            "source": signals_raw.get("source", "N/A (no OnchainOS keys)"),
        }
        
        # Index price deviation check
        index_data = raw.get("index_price", {})
        price_deviation = None
        if index_data.get("index_price") and price_data.get("price"):
            cex_price = price_data["price"]
            idx_price = index_data["index_price"]
            if cex_price > 0:
                price_deviation = round((cex_price - idx_price) / idx_price * 100, 3)
        
        # Data quality summary
        onchainos_active = self._has_onchainos_keys
        data_points = sum(1 for v in [
            price_data.get("price"),
            funding_oi.get("funding_rate"),
            ls_ratio.get("ratio"),
            dex_trades.get("total_trades"),
            signals_raw.get("total_signals"),
        ] if v)
        
        source_label = (
            f"OnchainOS + OKX + CoinGecko ({data_points}项真实数据)"
            if onchainos_active
            else f"OKX CEX + CoinGecko ({data_points}项数据, 无链上信号)"
        )
        
        return {
            "source": source_label,
            "onchainos_active": onchainos_active,
            "price": price_data,
            "trades": trades_data,
            "signals": signals_data,
            "index_price": index_data,
            "price_deviation_pct": price_deviation,
        }
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
