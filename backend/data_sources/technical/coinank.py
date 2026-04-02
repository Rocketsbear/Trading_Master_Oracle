"""
CoinAnk API 封装
提供爆仓数据、多空比、资金费率等数据
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import httpx
from loguru import logger


class CoinAnkDataSource:
    """CoinAnk 数据源"""
    
    BASE_URL = "https://api.coinank.com/api/v1"
    
    def __init__(self, api_key: str):
        """
        初始化 CoinAnk 客户端
        
        Args:
            api_key: CoinAnk API Key
        """
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        logger.info("CoinAnk 数据源初始化完成")
    
    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        发送 HTTP 请求
        
        Args:
            endpoint: API 端点
            params: 查询参数
            
        Returns:
            API 响应数据
        """
        url = f"{self.BASE_URL}/{endpoint}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") == 0:
                    return data.get("data", {})
                else:
                    raise ValueError(f"API 错误: {data.get('message')}")
                    
            except httpx.HTTPError as e:
                logger.error(f"HTTP 请求失败: {e}")
                raise
    
    async def get_liquidation_data(
        self,
        symbol: str = "BTC",
        interval: str = "24h"
    ) -> Dict[str, Any]:
        """
        获取爆仓数据
        
        Args:
            symbol: 币种（BTC, ETH, etc.）
            interval: 时间间隔（1h, 4h, 12h, 24h）
            
        Returns:
            包含多空爆仓金额的字典
        """
        try:
            data = await self._request("liquidation/summary", {
                "symbol": symbol,
                "interval": interval
            })
            
            result = {
                "symbol": symbol,
                "interval": interval,
                "long_liquidation": float(data.get("longLiquidation", 0)),
                "short_liquidation": float(data.get("shortLiquidation", 0)),
                "total_liquidation": float(data.get("totalLiquidation", 0)),
                "long_ratio": float(data.get("longRatio", 0)),
                "short_ratio": float(data.get("shortRatio", 0)),
                "timestamp": datetime.now()
            }
            
            logger.info(
                f"获取 {symbol} 爆仓数据成功: "
                f"多头 ${result['long_liquidation']/1e6:.2f}M, "
                f"空头 ${result['short_liquidation']/1e6:.2f}M"
            )
            return result
            
        except Exception as e:
            logger.error(f"获取爆仓数据失败: {e}")
            raise
    
    async def get_long_short_ratio(
        self,
        symbol: str = "BTC",
        exchange: str = "Binance"
    ) -> Dict[str, Any]:
        """
        获取多空比数据
        
        Args:
            symbol: 币种
            exchange: 交易所（Binance, OKX, Bybit, etc.）
            
        Returns:
            包含多空比信息的字典
        """
        try:
            data = await self._request("long-short-ratio", {
                "symbol": symbol,
                "exchange": exchange
            })
            
            result = {
                "symbol": symbol,
                "exchange": exchange,
                "long_ratio": float(data.get("longRatio", 0)),
                "short_ratio": float(data.get("shortRatio", 0)),
                "long_short_ratio": float(data.get("longShortRatio", 0)),
                "timestamp": datetime.now()
            }
            
            logger.info(
                f"获取 {symbol} 多空比成功: {result['long_short_ratio']:.2f}"
            )
            return result
            
        except Exception as e:
            logger.error(f"获取多空比失败: {e}")
            raise
    
    async def get_funding_rate(
        self,
        symbol: str = "BTC",
        exchange: str = "Binance"
    ) -> Dict[str, Any]:
        """
        获取资金费率
        
        Args:
            symbol: 币种
            exchange: 交易所
            
        Returns:
            包含资金费率信息的字典
        """
        try:
            data = await self._request("funding-rate", {
                "symbol": symbol,
                "exchange": exchange
            })
            
            result = {
                "symbol": symbol,
                "exchange": exchange,
                "funding_rate": float(data.get("fundingRate", 0)),
                "next_funding_time": data.get("nextFundingTime"),
                "timestamp": datetime.now()
            }
            
            logger.info(
                f"获取 {symbol} 资金费率成功: {result['funding_rate']:.4%}"
            )
            return result
            
        except Exception as e:
            logger.error(f"获取资金费率失败: {e}")
            raise
    
    async def get_open_interest(
        self,
        symbol: str = "BTC"
    ) -> Dict[str, Any]:
        """
        获取全网持仓量
        
        Args:
            symbol: 币种
            
        Returns:
            包含持仓量信息的字典
        """
        try:
            data = await self._request("open-interest", {
                "symbol": symbol
            })
            
            result = {
                "symbol": symbol,
                "open_interest": float(data.get("openInterest", 0)),
                "open_interest_value": float(data.get("openInterestValue", 0)),
                "change_24h": float(data.get("change24h", 0)),
                "timestamp": datetime.now()
            }
            
            logger.info(
                f"获取 {symbol} 持仓量成功: "
                f"${result['open_interest_value']/1e9:.2f}B"
            )
            return result
            
        except Exception as e:
            logger.error(f"获取持仓量失败: {e}")
            raise
    
    async def get_market_sentiment(self, symbol: str = "BTC") -> Dict[str, Any]:
        """
        获取市场情绪指标（综合）
        
        Args:
            symbol: 币种
            
        Returns:
            包含多个情绪指标的字典
        """
        try:
            # 并发获取多个指标
            liquidation, ls_ratio, funding, oi = await asyncio.gather(
                self.get_liquidation_data(symbol, "24h"),
                self.get_long_short_ratio(symbol),
                self.get_funding_rate(symbol),
                self.get_open_interest(symbol),
                return_exceptions=True
            )
            
            result = {
                "symbol": symbol,
                "liquidation": liquidation if not isinstance(liquidation, Exception) else None,
                "long_short_ratio": ls_ratio if not isinstance(ls_ratio, Exception) else None,
                "funding_rate": funding if not isinstance(funding, Exception) else None,
                "open_interest": oi if not isinstance(oi, Exception) else None,
                "timestamp": datetime.now()
            }
            
            # 计算综合情绪评分（0-100）
            score = 50  # 中性
            
            if result["liquidation"]:
                # 空头爆仓多 = 看多信号
                if result["liquidation"]["short_liquidation"] > result["liquidation"]["long_liquidation"]:
                    score += 10
                else:
                    score -= 10
            
            if result["long_short_ratio"]:
                # 多空比 > 1.5 = 过度看多，反向指标
                ratio = result["long_short_ratio"]["long_short_ratio"]
                if ratio > 1.5:
                    score -= 5
                elif ratio < 0.8:
                    score += 5
            
            if result["funding_rate"]:
                # 资金费率过高 = 过度看多
                rate = result["funding_rate"]["funding_rate"]
                if rate > 0.01:
                    score -= 10
                elif rate < -0.01:
                    score += 10
            
            result["sentiment_score"] = max(0, min(100, score))
            
            logger.info(f"获取 {symbol} 市场情绪成功，评分: {result['sentiment_score']}")
            return result
            
        except Exception as e:
            logger.error(f"获取市场情绪失败: {e}")
            raise


# 测试代码
if __name__ == "__main__":
    async def test():
        # 使用提供的 API Key
        coinank = CoinAnkDataSource("e643ebc71b624355a863c688235a87a6")
        
        # 注意：CoinAnk API 端点可能需要调整
        # 暂时注释掉测试，等待 API 文档确认
        print("CoinAnk 数据源已初始化")
        print("注意：需要确认正确的 API 端点和认证方式")
        
        # # 测试获取爆仓数据
        # liquidation = await coinank.get_liquidation_data("BTC", "24h")
        # print("爆仓数据:")
        # print(liquidation)
        
        # # 测试获取市场情绪
        # sentiment = await coinank.get_market_sentiment("BTC")
        # print(f"\n市场情绪评分: {sentiment['sentiment_score']}")
    
    asyncio.run(test())
