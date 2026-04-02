"""
Binance API 封装
提供 K线、技术指标、多空比、资金费率等数据
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from loguru import logger


class BinanceDataSource:
    """Binance 数据源（使用公共 API）"""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        初始化 Binance 客户端
        
        Args:
            api_key: API Key（可选，公共数据不需要）
            api_secret: API Secret（可选）
        """
        self.client = Client(api_key, api_secret) if api_key else Client()
        logger.info("Binance 数据源初始化完成")
    
    async def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> pd.DataFrame:
        """
        获取 K 线数据
        
        Args:
            symbol: 交易对（如 BTCUSDT）
            interval: 时间间隔（1m, 5m, 15m, 1h, 4h, 1d）
            limit: 数据条数
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # 转换数据类型
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
            # 只保留需要的列
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            logger.info(f"获取 {symbol} K线数据成功，{len(df)} 条")
            return df
            
        except BinanceAPIException as e:
            logger.error(f"获取 K线数据失败: {e}")
            raise
    
    async def get_ticker_24h(self, symbol: str) -> Dict[str, Any]:
        """
        获取 24 小时价格变动数据
        
        Args:
            symbol: 交易对
            
        Returns:
            包含价格、成交量、涨跌幅等信息的字典
        """
        try:
            ticker = self.client.get_ticker(symbol=symbol)
            
            result = {
                "symbol": ticker['symbol'],
                "price": float(ticker['lastPrice']),
                "price_change": float(ticker['priceChange']),
                "price_change_percent": float(ticker['priceChangePercent']),
                "high_24h": float(ticker['highPrice']),
                "low_24h": float(ticker['lowPrice']),
                "volume_24h": float(ticker['volume']),
                "quote_volume_24h": float(ticker['quoteVolume']),
                "timestamp": datetime.fromtimestamp(ticker['closeTime'] / 1000)
            }
            
            logger.info(f"获取 {symbol} 24h 数据成功")
            return result
            
        except BinanceAPIException as e:
            logger.error(f"获取 24h 数据失败: {e}")
            raise
    
    async def get_long_short_ratio(
        self,
        symbol: str,
        period: str = "5m",
        limit: int = 30
    ) -> pd.DataFrame:
        """
        获取多空比数据（期货）
        
        Args:
            symbol: 交易对
            period: 时间周期（5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d）
            limit: 数据条数
            
        Returns:
            DataFrame with columns: timestamp, long_short_ratio, long_account, short_account
        """
        try:
            # 使用 Binance Futures API
            from binance.client import Client
            
            data = self.client.futures_global_long_short_account_ratio(
                symbol=symbol,
                period=period,
                limit=limit
            )
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['longShortRatio'] = df['longShortRatio'].astype(float)
            df['longAccount'] = df['longAccount'].astype(float)
            df['shortAccount'] = df['shortAccount'].astype(float)
            
            df = df.rename(columns={
                'longShortRatio': 'long_short_ratio',
                'longAccount': 'long_account',
                'shortAccount': 'short_account'
            })
            
            logger.info(f"获取 {symbol} 多空比数据成功，{len(df)} 条")
            return df
            
        except Exception as e:
            logger.error(f"获取多空比数据失败: {e}")
            raise
    
    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """
        获取资金费率（期货）
        
        Args:
            symbol: 交易对
            
        Returns:
            包含当前资金费率和下次结算时间的字典
        """
        try:
            funding_rate = self.client.futures_funding_rate(symbol=symbol, limit=1)
            
            if funding_rate:
                latest = funding_rate[0]
                result = {
                    "symbol": latest['symbol'],
                    "funding_rate": float(latest['fundingRate']),
                    "funding_time": datetime.fromtimestamp(latest['fundingTime'] / 1000),
                    "timestamp": datetime.now()
                }
                
                logger.info(f"获取 {symbol} 资金费率成功: {result['funding_rate']}")
                return result
            else:
                raise ValueError("未获取到资金费率数据")
                
        except Exception as e:
            logger.error(f"获取资金费率失败: {e}")
            raise
    
    async def get_open_interest(self, symbol: str) -> Dict[str, Any]:
        """
        获取持仓量（期货）
        
        Args:
            symbol: 交易对
            
        Returns:
            包含持仓量信息的字典
        """
        try:
            oi = self.client.futures_open_interest(symbol=symbol)
            
            result = {
                "symbol": oi['symbol'],
                "open_interest": float(oi['openInterest']),
                "timestamp": datetime.fromtimestamp(oi['time'] / 1000)
            }
            
            logger.info(f"获取 {symbol} 持仓量成功: {result['open_interest']}")
            return result
            
        except Exception as e:
            logger.error(f"获取持仓量失败: {e}")
            raise
    
    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """
        获取订单簿（深度数据）
        
        Args:
            symbol: 交易对
            limit: 档位数量（5, 10, 20, 50, 100, 500, 1000, 5000）
            
        Returns:
            包含买卖盘数据的字典
        """
        try:
            depth = self.client.get_order_book(symbol=symbol, limit=limit)
            
            result = {
                "symbol": symbol,
                "bids": [[float(price), float(qty)] for price, qty in depth['bids']],
                "asks": [[float(price), float(qty)] for price, qty in depth['asks']],
                "timestamp": datetime.now()
            }
            
            # 计算买卖压力
            bid_volume = sum([qty for _, qty in result['bids']])
            ask_volume = sum([qty for _, qty in result['asks']])
            
            result['bid_volume'] = bid_volume
            result['ask_volume'] = ask_volume
            result['bid_ask_ratio'] = bid_volume / ask_volume if ask_volume > 0 else 0
            
            logger.info(f"获取 {symbol} 订单簿成功，买卖比: {result['bid_ask_ratio']:.2f}")
            return result
            
        except BinanceAPIException as e:
            logger.error(f"获取订单簿失败: {e}")
            raise


# 测试代码
if __name__ == "__main__":
    async def test():
        binance = BinanceDataSource()
        
        # 测试获取 K 线
        klines = await binance.get_klines("BTCUSDT", "1h", 24)
        print("K线数据:")
        print(klines.tail())
        
        # 测试获取 24h 数据
        ticker = await binance.get_ticker_24h("BTCUSDT")
        print(f"\n24h 数据: {ticker}")
        
        # 测试获取多空比
        try:
            ls_ratio = await binance.get_long_short_ratio("BTCUSDT", "5m", 10)
            print(f"\n多空比数据:")
            print(ls_ratio.tail())
        except Exception as e:
            print(f"多空比获取失败（可能需要期货 API）: {e}")
    
    asyncio.run(test())
