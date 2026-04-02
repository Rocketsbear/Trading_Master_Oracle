"""
FRED API 封装 — 100% 真实数据
从美联储经济数据库获取 GDP、CPI、失业率、利率等宏观指标
"""
import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from functools import partial
from loguru import logger

try:
    import pandas as pd
    from fredapi import Fred
except ImportError:
    pd = None
    Fred = None


class FREDDataSource:
    """FRED 数据源（美联储经济数据）- 纯真实 API 调用"""
    
    # 核心宏观指标 Series IDs
    SERIES = {
        "fed_funds_rate": "FEDFUNDS",       # 联邦基金利率
        "unemployment":   "UNRATE",          # 失业率
        "cpi":            "CPIAUCSL",        # CPI 指数
        "core_pce":       "PCEPILFE",        # 核心 PCE (Fed 首选通胀指标)
        "gdp":            "GDP",             # GDP (季度)
        "m2":             "M2SL",            # M2 货币供应
        "10y_treasury":   "DGS10",           # 10年期国债收益率
        "2y_treasury":    "DGS2",            # 2年期国债收益率
        "nonfarm":        "PAYEMS",          # 非农就业人数
        "retail_sales":   "RSXFS",           # 零售销售
        "industrial":     "INDPRO",          # 工业生产指数
        "consumer_sent":  "UMCSENT",         # 密歇根消费者信心
    }
    
    def __init__(self, api_key: str):
        if not Fred:
            raise ImportError("fredapi not installed: pip install fredapi")
        self.fred = Fred(api_key=api_key)
        self._api_key = api_key
        logger.info("FRED 数据源初始化完成")
    
    def _get_series_sync(self, series_id: str, lookback_days: int = 400):
        """同步获取 FRED 时间序列（在线程中运行）"""
        start = datetime.now() - timedelta(days=lookback_days)
        return self.fred.get_series(series_id, observation_start=start)
    
    async def _get_series(self, series_id: str, lookback_days: int = 400):
        """异步获取 FRED 序列（线程池执行，避免阻塞）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, partial(self._get_series_sync, series_id, lookback_days)
        )
    
    async def _safe_get_latest(self, series_id: str, lookback_days: int = 400) -> Optional[float]:
        """安全获取最新值，失败返回 None"""
        try:
            data = await self._get_series(series_id, lookback_days)
            if data is not None and len(data) > 0:
                # 跳过 NaN
                valid = data.dropna()
                if len(valid) > 0:
                    return float(valid.iloc[-1])
        except Exception as e:
            logger.warning(f"FRED {series_id} 获取失败: {e}")
        return None
    
    async def _safe_get_yoy_change(self, series_id: str) -> Optional[float]:
        """安全计算同比变化率 (%)"""
        try:
            data = await self._get_series(series_id, lookback_days=500)
            if data is not None and len(data) > 13:
                valid = data.dropna()
                if len(valid) > 13:
                    current = float(valid.iloc[-1])
                    year_ago = float(valid.iloc[-13])
                    if year_ago != 0:
                        return round((current - year_ago) / year_ago * 100, 2)
        except Exception as e:
            logger.warning(f"FRED {series_id} YoY 计算失败: {e}")
        return None
    
    async def get_comprehensive_macro_data(self) -> Dict[str, Any]:
        """获取综合宏观数据 — 全部来自 FRED API 真实数据"""
        
        # 并行获取所有指标
        tasks = {
            "fed_rate":     self._safe_get_latest("FEDFUNDS"),
            "unemployment": self._safe_get_latest("UNRATE"),
            "cpi_yoy":      self._safe_get_yoy_change("CPIAUCSL"),
            "core_pce_yoy": self._safe_get_yoy_change("PCEPILFE"),
            "gdp_yoy":      self._safe_get_yoy_change("GDP"),
            "m2_yoy":       self._safe_get_yoy_change("M2SL"),
            "treasury_10y": self._safe_get_latest("DGS10"),
            "treasury_2y":  self._safe_get_latest("DGS2"),
            "consumer_sent": self._safe_get_latest("UMCSENT"),
            "nonfarm":      self._safe_get_latest("PAYEMS"),
        }
        
        # 并行执行
        keys = list(tasks.keys())
        values = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results = {}
        for k, v in zip(keys, values):
            results[k] = v if not isinstance(v, Exception) else None
        
        # 计算衍生指标
        t10 = results.get("treasury_10y")
        t2 = results.get("treasury_2y")
        yield_spread = round(t10 - t2, 2) if t10 is not None and t2 is not None else None
        
        # 判断经济周期
        gdp = results.get("gdp_yoy")
        ue = results.get("unemployment")
        fed_rate = results.get("fed_rate")
        
        if gdp is not None and ue is not None:
            if gdp > 2.0 and ue < 5.0:
                cycle_phase = "expansion"
            elif gdp > 0 and fed_rate and fed_rate > 4.5:
                cycle_phase = "peak"
            elif gdp is not None and gdp < 0:
                cycle_phase = "contraction"
            else:
                cycle_phase = "moderate_growth"
        else:
            cycle_phase = "unknown"
        
        # 统计成功获取的指标数量
        real_count = sum(1 for v in results.values() if v is not None)
        total_count = len(results)
        logger.info(f"FRED 数据获取完成: {real_count}/{total_count} 指标成功")
        
        return {
            "source": "FRED_API_real_data",
            "fed_funds_rate": {"value": results.get("fed_rate")},
            "unemployment_rate": {"value": results.get("unemployment")},
            "cpi": {"change_yoy": results.get("cpi_yoy")},
            "core_pce": {"change_yoy": results.get("core_pce_yoy")},
            "gdp": {"change_yoy": results.get("gdp_yoy")},
            "m2_money_supply": {"change_yoy": results.get("m2_yoy")},
            "treasury_10y": {"value": results.get("treasury_10y")},
            "treasury_2y": {"value": results.get("treasury_2y")},
            "yield_curve_spread": {"value": yield_spread, "inverted": yield_spread < 0 if yield_spread is not None else None},
            "consumer_sentiment": {"value": results.get("consumer_sent")},
            "nonfarm_payrolls": {"value": results.get("nonfarm")},
            "economic_cycle": {"phase": cycle_phase},
            "data_quality": f"{real_count}/{total_count} real indicators",
        }
