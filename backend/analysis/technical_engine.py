"""
技术面分析引擎
整合所有技术指标，生成详细的技术分析报告
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd
from loguru import logger

from ..data_sources.exchanges.binance_api import BinanceDataSource
from ..data_sources.technical.coinank import CoinAnkDataSource
from .technical import TechnicalIndicators
from ..utils.validator import DataValidator


class TechnicalAnalysisEngine:
    """技术面分析引擎"""
    
    def __init__(
        self,
        binance_api_key: Optional[str] = None,
        binance_api_secret: Optional[str] = None,
        coinank_api_key: Optional[str] = None
    ):
        """
        初始化技术面分析引擎
        
        Args:
            binance_api_key: Binance API Key（可选）
            binance_api_secret: Binance API Secret（可选）
            coinank_api_key: CoinAnk API Key（可选）
        """
        self.binance = BinanceDataSource(binance_api_key, binance_api_secret)
        self.coinank = CoinAnkDataSource(coinank_api_key) if coinank_api_key else None
        self.validator = DataValidator()
        logger.info("技术面分析引擎初始化完成")
    
    async def analyze(
        self,
        symbol: str,
        interval: str = "1h",
        lookback: int = 200
    ) -> Dict[str, Any]:
        """
        执行完整的技术面分析
        
        Args:
            symbol: 交易对（如 BTCUSDT）
            interval: 时间间隔
            lookback: 回溯周期数
            
        Returns:
            完整的技术分析报告
        """
        try:
            logger.info(f"开始技术面分析: {symbol} {interval}")
            
            # 1. 获取 K 线数据
            klines = await self.binance.get_klines(symbol, interval, lookback)
            
            # 2. 计算所有技术指标
            df_with_indicators = TechnicalIndicators.calculate_all_indicators(klines)
            
            # 3. 分析技术指标
            indicators_analysis = TechnicalIndicators.analyze_indicators(df_with_indicators)
            
            # 4. 获取 24h 数据
            ticker_24h = await self.binance.get_ticker_24h(symbol)
            
            # 5. 获取多空比（如果可用）
            try:
                ls_ratio = await self.binance.get_long_short_ratio(symbol, "5m", 30)
                latest_ls = ls_ratio.iloc[-1]
                long_short_data = {
                    "ratio": float(latest_ls['long_short_ratio']),
                    "long_account": float(latest_ls['long_account']),
                    "short_account": float(latest_ls['short_account']),
                    "timestamp": latest_ls['timestamp']
                }
            except Exception as e:
                logger.warning(f"获取多空比失败: {e}")
                long_short_data = None
            
            # 6. 获取资金费率
            try:
                funding = await self.binance.get_funding_rate(symbol)
                funding_data = funding
            except Exception as e:
                logger.warning(f"获取资金费率失败: {e}")
                funding_data = None
            
            # 7. 获取订单簿
            order_book = await self.binance.get_order_book(symbol, 20)
            
            # 8. 获取爆仓数据（如果 CoinAnk 可用）
            if self.coinank:
                try:
                    liquidation = await self.coinank.get_liquidation_data(
                        symbol.replace("USDT", ""), "24h"
                    )
                    liquidation_data = liquidation
                except Exception as e:
                    logger.warning(f"获取爆仓数据失败: {e}")
                    liquidation_data = None
            else:
                liquidation_data = None
            
            # 9. 生成详细报告
            report = self._generate_detailed_report(
                symbol=symbol,
                interval=interval,
                ticker_24h=ticker_24h,
                indicators=indicators_analysis,
                df=df_with_indicators,
                long_short=long_short_data,
                funding=funding_data,
                order_book=order_book,
                liquidation=liquidation_data
            )
            
            logger.info(f"技术面分析完成，评分: {report['score']}")
            return report
            
        except Exception as e:
            logger.error(f"技术面分析失败: {e}")
            raise
    
    def _generate_detailed_report(
        self,
        symbol: str,
        interval: str,
        ticker_24h: Dict,
        indicators: Dict,
        df: pd.DataFrame,
        long_short: Optional[Dict],
        funding: Optional[Dict],
        order_book: Dict,
        liquidation: Optional[Dict]
    ) -> Dict[str, Any]:
        """生成详细的技术分析报告"""
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 趋势判断
        trend_analysis = self._analyze_trend(df, indicators)
        
        # 动量分析
        momentum_analysis = self._analyze_momentum(indicators, latest, prev)
        
        # 成交量分析
        volume_analysis = self._analyze_volume(indicators, latest, df)
        
        # 多空比分析
        ls_analysis = self._analyze_long_short(long_short) if long_short else None
        
        # 资金费率分析
        funding_analysis = self._analyze_funding(funding) if funding else None
        
        # 订单簿分析
        orderbook_analysis = self._analyze_orderbook(order_book)
        
        # 爆仓分析
        liquidation_analysis = self._analyze_liquidation(liquidation) if liquidation else None
        
        # 关键价位
        key_levels = self._identify_key_levels(df, latest)
        
        # 综合评分
        score = self._calculate_technical_score(
            trend_analysis,
            momentum_analysis,
            volume_analysis,
            ls_analysis,
            funding_analysis,
            liquidation_analysis
        )
        
        # 生成建议
        recommendation = self._generate_recommendation(score, trend_analysis, momentum_analysis)
        
        report = {
            "symbol": symbol,
            "interval": interval,
            "score": score,
            "trend": trend_analysis["overall"],
            "price_info": {
                "current": float(latest['close']),
                "change_24h": ticker_24h['price_change'],
                "change_24h_percent": ticker_24h['price_change_percent'],
                "high_24h": ticker_24h['high_24h'],
                "low_24h": ticker_24h['low_24h'],
                "volume_24h": ticker_24h['volume_24h']
            },
            "trend_analysis": trend_analysis,
            "momentum_analysis": momentum_analysis,
            "volume_analysis": volume_analysis,
            "long_short_analysis": ls_analysis,
            "funding_analysis": funding_analysis,
            "orderbook_analysis": orderbook_analysis,
            "liquidation_analysis": liquidation_analysis,
            "key_levels": key_levels,
            "recommendation": recommendation,
            "timestamp": datetime.now(),
            "data_source": "binance + coinank"
        }
        
        return report
    
    def _analyze_trend(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, Any]:
        """趋势分析"""
        latest = df.iloc[-1]
        
        # 判断趋势
        ma_trend = indicators['moving_averages']['trend']
        
        # 价格相对 MA 位置
        above_ma20 = latest['close'] > latest['ma_20']
        above_ma50 = latest['close'] > latest['ma_50']
        above_ma200 = latest['close'] > latest['ma_200']
        
        # 高点低点分析
        recent_highs = df['high'].tail(20)
        recent_lows = df['low'].tail(20)
        higher_highs = recent_highs.iloc[-1] > recent_highs.iloc[-10]
        higher_lows = recent_lows.iloc[-1] > recent_lows.iloc[-10]
        
        if ma_trend == 'bullish' and higher_highs and higher_lows:
            overall = "强势上升趋势"
            score = 15
        elif ma_trend == 'bullish':
            overall = "上升趋势"
            score = 10
        elif ma_trend == 'bearish' and not higher_highs and not higher_lows:
            overall = "强势下降趋势"
            score = -15
        elif ma_trend == 'bearish':
            overall = "下降趋势"
            score = -10
        else:
            overall = "震荡整理"
            score = 0
        
        return {
            "overall": overall,
            "score": score,
            "ma_alignment": ma_trend,
            "above_ma20": above_ma20,
            "above_ma50": above_ma50,
            "above_ma200": above_ma200,
            "higher_highs": higher_highs,
            "higher_lows": higher_lows,
            "support": float(latest['ma_20']),
            "details": f"价格位于 MA20/MA50/MA200 {'上方' if above_ma20 else '下方'}，"
                      f"{'高点逐步抬高' if higher_highs else '高点下移'}，"
                      f"{'低点逐步抬高' if higher_lows else '低点下移'}"
        }
    
    def _analyze_momentum(self, indicators: Dict, latest: pd.Series, prev: pd.Series) -> Dict[str, Any]:
        """动量分析"""
        macd = indicators['macd']
        rsi = indicators['rsi']
        
        score = 0
        details = []
        
        # MACD 分析
        if macd['cross'] == 'golden':
            score += 15
            details.append("MACD 金叉（DIF 上穿 DEA），动能增强")
        elif macd['cross'] == 'death':
            score -= 15
            details.append("MACD 死叉（DIF 下穿 DEA），动能减弱")
        elif macd['trend'] == 'bullish':
            score += 5
            details.append("MACD 位于零轴上方，多头占优")
        else:
            score -= 5
            details.append("MACD 位于零轴下方，空头占优")
        
        # RSI 分析
        if rsi['status'] == 'oversold':
            score += 10
            details.append(f"RSI {rsi['value']:.1f} 超卖，可能反弹")
        elif rsi['status'] == 'overbought':
            score -= 10
            details.append(f"RSI {rsi['value']:.1f} 超买，可能回调")
        else:
            details.append(f"RSI {rsi['value']:.1f} 中性区域")
        
        return {
            "score": score,
            "macd": macd,
            "rsi": rsi,
            "details": " | ".join(details)
        }
    
    def _analyze_volume(self, indicators: Dict, latest: pd.Series, df: pd.DataFrame) -> Dict[str, Any]:
        """成交量分析"""
        volume = indicators['volume']
        
        score = 0
        details = []
        
        volume_ratio = volume['volume_ratio']
        
        if volume_ratio > 1.5:
            if volume['trend'] == 'increasing':
                score += 5
                details.append(f"成交量放大 {volume_ratio:.1f}x，资金流入")
            else:
                score -= 5
                details.append(f"成交量放大但 OBV 下降，可能是出货")
        elif volume_ratio < 0.7:
            details.append("成交量萎缩，观望情绪浓厚")
        else:
            details.append("成交量正常")
        
        return {
            "score": score,
            "volume_ratio": volume_ratio,
            "obv_trend": volume['trend'],
            "details": " | ".join(details)
        }
    
    def _analyze_long_short(self, long_short: Dict) -> Dict[str, Any]:
        """多空比分析"""
        ratio = long_short['ratio']
        
        score = 0
        details = []
        
        if ratio > 1.5:
            score -= 5
            details.append(f"多空比 {ratio:.2f}，多头过度拥挤，反向指标")
        elif ratio > 1.2:
            score += 10
            details.append(f"多空比 {ratio:.2f}，多头占优但未过度")
        elif ratio < 0.8:
            score += 5
            details.append(f"多空比 {ratio:.2f}，空头过度，可能反弹")
        else:
            details.append(f"多空比 {ratio:.2f}，多空平衡")
        
        return {
            "score": score,
            "ratio": ratio,
            "long_percent": long_short['long_account'] * 100,
            "short_percent": long_short['short_account'] * 100,
            "details": " | ".join(details)
        }
    
    def _analyze_funding(self, funding: Dict) -> Dict[str, Any]:
        """资金费率分析"""
        rate = funding['funding_rate']
        
        score = 0
        details = []
        
        if rate > 0.01:
            score -= 10
            details.append(f"资金费率 {rate:.4%}，多头过度，可能回调")
        elif rate > 0.005:
            score -= 5
            details.append(f"资金费率 {rate:.4%}，略偏多头")
        elif rate < -0.01:
            score += 10
            details.append(f"资金费率 {rate:.4%}，空头过度，可能反弹")
        elif rate < -0.005:
            score += 5
            details.append(f"资金费率 {rate:.4%}，略偏空头")
        else:
            details.append(f"资金费率 {rate:.4%}，中性")
        
        return {
            "score": score,
            "rate": rate,
            "details": " | ".join(details)
        }
    
    def _analyze_orderbook(self, order_book: Dict) -> Dict[str, Any]:
        """订单簿分析"""
        bid_ask_ratio = order_book['bid_ask_ratio']
        
        score = 0
        details = []
        
        if bid_ask_ratio > 1.2:
            score += 5
            details.append(f"买卖比 {bid_ask_ratio:.2f}，买盘强劲")
        elif bid_ask_ratio < 0.8:
            score -= 5
            details.append(f"买卖比 {bid_ask_ratio:.2f}，卖盘压力大")
        else:
            details.append(f"买卖比 {bid_ask_ratio:.2f}，买卖平衡")
        
        return {
            "score": score,
            "bid_ask_ratio": bid_ask_ratio,
            "details": " | ".join(details)
        }
    
    def _analyze_liquidation(self, liquidation: Dict) -> Dict[str, Any]:
        """爆仓分析"""
        long_liq = liquidation['long_liquidation']
        short_liq = liquidation['short_liquidation']
        
        score = 0
        details = []
        
        if short_liq > long_liq * 1.5:
            score += 10
            details.append(f"空头爆仓 ${short_liq/1e6:.1f}M > 多头 ${long_liq/1e6:.1f}M，看多信号")
        elif long_liq > short_liq * 1.5:
            score -= 10
            details.append(f"多头爆仓 ${long_liq/1e6:.1f}M > 空头 ${short_liq/1e6:.1f}M，看空信号")
        else:
            details.append(f"多空爆仓相当，市场平衡")
        
        return {
            "score": score,
            "long_liquidation": long_liq,
            "short_liquidation": short_liq,
            "details": " | ".join(details)
        }
    
    def _identify_key_levels(self, df: pd.DataFrame, latest: pd.Series) -> Dict[str, Any]:
        """识别关键价位"""
        # 阻力位（近期高点）
        recent_highs = df['high'].tail(50).nlargest(3)
        resistance = [float(h) for h in recent_highs if h > latest['close']]
        
        # 支撑位（近期低点）
        recent_lows = df['low'].tail(50).nsmallest(3)
        support = [float(l) for l in recent_lows if l < latest['close']]
        
        return {
            "resistance": resistance[:2] if resistance else [float(latest['bb_upper'])],
            "support": support[:2] if support else [float(latest['bb_lower'])],
            "current_price": float(latest['close'])
        }
    
    def _calculate_technical_score(
        self,
        trend: Dict,
        momentum: Dict,
        volume: Dict,
        long_short: Optional[Dict],
        funding: Optional[Dict],
        liquidation: Optional[Dict]
    ) -> int:
        """计算技术面综合评分"""
        score = 50  # 基准分
        
        score += trend['score']
        score += momentum['score']
        score += volume['score']
        
        if long_short:
            score += long_short['score']
        if funding:
            score += funding['score']
        if liquidation:
            score += liquidation['score']
        
        return max(0, min(100, score))
    
    def _generate_recommendation(
        self,
        score: int,
        trend: Dict,
        momentum: Dict
    ) -> Dict[str, Any]:
        """生成交易建议"""
        if score >= 70:
            direction = "做多"
            confidence = "高"
            reason = f"{trend['overall']}，{momentum['details']}"
        elif score >= 55:
            direction = "谨慎做多"
            confidence = "中"
            reason = "技术面偏多但不强"
        elif score <= 30:
            direction = "做空"
            confidence = "高"
            reason = f"{trend['overall']}，动能减弱"
        elif score <= 45:
            direction = "谨慎做空"
            confidence = "中"
            reason = "技术面偏空但不强"
        else:
            direction = "观望"
            confidence = "低"
            reason = "技术面中性，等待方向明确"
        
        return {
            "direction": direction,
            "confidence": confidence,
            "reason": reason
        }


# 测试代码
if __name__ == "__main__":
    async def test():
        engine = TechnicalAnalysisEngine()
        
        report = await engine.analyze("BTCUSDT", "1h", 200)
        
        print(f"技术面分析报告:")
        print(f"  评分: {report['score']}/100")
        print(f"  趋势: {report['trend']}")
        print(f"  建议: {report['recommendation']['direction']} (置信度: {report['recommendation']['confidence']})")
        print(f"  理由: {report['recommendation']['reason']}")
    
    asyncio.run(test())
