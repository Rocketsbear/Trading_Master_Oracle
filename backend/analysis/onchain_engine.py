"""
链上数据分析引擎
整合链上数据，生成链上分析报告
"""
import asyncio
from typing import Dict, Any
from datetime import datetime
from loguru import logger

from ..data_sources.onchain.onchainos import OnchainDataSource


class OnchainAnalysisEngine:
    """链上数据分析引擎"""
    
    def __init__(self, mcp_path: str = None):
        """
        初始化链上分析引擎
        
        Args:
            mcp_path: onchainos MCP 路径
        """
        self.onchain = OnchainDataSource(mcp_path)
        logger.info("链上分析引擎初始化完成")
    
    async def analyze(self, symbol: str = "BTC") -> Dict[str, Any]:
        """
        执行完整的链上分析
        
        Args:
            symbol: 币种
            
        Returns:
            完整的链上分析报告
        """
        try:
            logger.info(f"开始链上分析: {symbol}")
            
            # 获取综合链上数据
            data = await self.onchain.get_comprehensive_onchain_data(symbol)
            
            # 分析各个维度
            exchange_analysis = self._analyze_exchange_flows(data['exchange_flows'])
            whale_analysis = self._analyze_whale_movements(data['whale_movements'])
            network_analysis = self._analyze_network_activity(data['network_activity'])
            holder_analysis = self._analyze_holder_distribution(data['holder_distribution'])
            miner_analysis = self._analyze_miner_data(data['miner_data'])
            
            # 综合评分
            score = self._calculate_onchain_score(
                exchange_analysis,
                whale_analysis,
                network_analysis,
                holder_analysis,
                miner_analysis
            )
            
            # 生成建议
            recommendation = self._generate_recommendation(score, exchange_analysis, holder_analysis)
            
            report = {
                "symbol": symbol,
                "score": score,
                "exchange_flows": exchange_analysis,
                "whale_movements": whale_analysis,
                "network_activity": network_analysis,
                "holder_distribution": holder_analysis,
                "miner_data": miner_analysis,
                "recommendation": recommendation,
                "timestamp": datetime.now(),
                "data_source": "onchainos_mcp"
            }
            
            logger.info(f"链上分析完成，评分: {score}")
            return report
            
        except Exception as e:
            logger.error(f"链上分析失败: {e}")
            raise
    
    def _analyze_exchange_flows(self, flows: Dict) -> Dict[str, Any]:
        """分析交易所资金流动"""
        net_flow = flows['net_flow']
        
        score = 0
        signal = ""
        details = []
        
        if net_flow < -5000:
            score = 20
            signal = "强烈看多"
            details.append(f"大量 {abs(net_flow):.0f} BTC 流出交易所，筹码锁定")
        elif net_flow < -1000:
            score = 10
            signal = "看多"
            details.append(f"{abs(net_flow):.0f} BTC 流出交易所，减少抛压")
        elif net_flow > 5000:
            score = -20
            signal = "强烈看空"
            details.append(f"大量 {net_flow:.0f} BTC 流入交易所，可能抛售")
        elif net_flow > 1000:
            score = -10
            signal = "看空"
            details.append(f"{net_flow:.0f} BTC 流入交易所，增加抛压")
        else:
            score = 0
            signal = "中性"
            details.append("交易所流动平衡")
        
        return {
            "score": score,
            "signal": signal,
            "net_flow": net_flow,
            "inflow": flows['inflow'],
            "outflow": flows['outflow'],
            "details": " | ".join(details)
        }
    
    def _analyze_whale_movements(self, whales: list) -> Dict[str, Any]:
        """分析巨鲸动向"""
        if not whales:
            return {"score": 0, "signal": "无数据", "details": "暂无巨鲸动向"}
        
        # 统计巨鲸行为
        deposits = [w for w in whales if w['type'] == 'exchange_deposit']
        withdrawals = [w for w in whales if w['type'] == 'exchange_withdrawal']
        
        deposit_amount = sum(w['amount'] for w in deposits)
        withdrawal_amount = sum(w['amount'] for w in withdrawals)
        
        score = 0
        signal = ""
        details = []
        
        if withdrawal_amount > deposit_amount * 1.5:
            score = 15
            signal = "看多"
            details.append(f"巨鲸提币 {withdrawal_amount:.0f} BTC > 充币 {deposit_amount:.0f} BTC")
        elif deposit_amount > withdrawal_amount * 1.5:
            score = -15
            signal = "看空"
            details.append(f"巨鲸充币 {deposit_amount:.0f} BTC > 提币 {withdrawal_amount:.0f} BTC")
        else:
            signal = "中性"
            details.append("巨鲸充提平衡")
        
        return {
            "score": score,
            "signal": signal,
            "deposit_count": len(deposits),
            "withdrawal_count": len(withdrawals),
            "deposit_amount": deposit_amount,
            "withdrawal_amount": withdrawal_amount,
            "details": " | ".join(details)
        }
    
    def _analyze_network_activity(self, network: Dict) -> Dict[str, Any]:
        """分析网络活跃度"""
        active_change = network['active_addresses_change_24h']
        tx_change = network['transactions_change_24h']
        
        score = 0
        signal = ""
        details = []
        
        if active_change > 10 and tx_change > 10:
            score = 10
            signal = "活跃度激增"
            details.append(f"活跃地址 +{active_change:.1f}%，交易量 +{tx_change:.1f}%")
        elif active_change > 5 and tx_change > 5:
            score = 5
            signal = "活跃度上升"
            details.append(f"活跃地址 +{active_change:.1f}%，交易量 +{tx_change:.1f}%")
        elif active_change < -10 or tx_change < -10:
            score = -10
            signal = "活跃度下降"
            details.append(f"活跃地址 {active_change:+.1f}%，交易量 {tx_change:+.1f}%")
        else:
            signal = "活跃度稳定"
            details.append("网络活跃度正常")
        
        return {
            "score": score,
            "signal": signal,
            "active_addresses": network['active_addresses'],
            "active_change": active_change,
            "transactions": network['transactions_count'],
            "tx_change": tx_change,
            "details": " | ".join(details)
        }
    
    def _analyze_holder_distribution(self, holder: Dict) -> Dict[str, Any]:
        """分析持仓分布"""
        long_term = holder['long_term_holders']
        top_100_change = holder['top_100_change_7d']
        utxo_age = holder['utxo_age_1y_plus']
        
        score = 0
        signal = ""
        details = []
        
        # 长期持有者占比
        if long_term > 70:
            score += 10
            details.append(f"长期持有者 {long_term:.1f}%，筹码稳定")
        elif long_term < 60:
            score -= 5
            details.append(f"长期持有者仅 {long_term:.1f}%，筹码不稳")
        
        # 巨鲸持仓变化
        if top_100_change > 0.5:
            score += 5
            details.append(f"Top100 地址增持 +{top_100_change:.1f}%")
        elif top_100_change < -0.5:
            score -= 5
            details.append(f"Top100 地址减持 {top_100_change:.1f}%")
        
        # UTXO 年龄
        if utxo_age > 65:
            score += 5
            details.append(f"{utxo_age:.1f}% 币龄 >1年，供应紧张")
        
        if score > 10:
            signal = "筹码稳定"
        elif score < -5:
            signal = "筹码松动"
        else:
            signal = "筹码中性"
        
        return {
            "score": score,
            "signal": signal,
            "long_term_holders": long_term,
            "top_100_change": top_100_change,
            "utxo_age": utxo_age,
            "details": " | ".join(details)
        }
    
    def _analyze_miner_data(self, miner: Dict) -> Dict[str, Any]:
        """分析矿工数据"""
        position_change = miner['miner_net_position_change_7d']
        hashrate_change = miner['hashrate_change_30d']
        
        score = 0
        signal = ""
        details = []
        
        # 矿工持仓变化
        if position_change < -1000:
            score = -10
            signal = "矿工抛售"
            details.append(f"矿工净卖出 {abs(position_change):.0f} BTC")
        elif position_change < -500:
            score = -5
            signal = "矿工减持"
            details.append(f"矿工净卖出 {abs(position_change):.0f} BTC")
        elif position_change > 500:
            score = 5
            signal = "矿工增持"
            details.append(f"矿工净买入 {position_change:.0f} BTC")
        else:
            signal = "矿工持仓稳定"
            details.append("矿工持仓变化不大")
        
        # 算力变化
        if hashrate_change > 10:
            score += 5
            details.append(f"算力增长 +{hashrate_change:.1f}%，网络安全性提升")
        elif hashrate_change < -10:
            score -= 5
            details.append(f"算力下降 {hashrate_change:.1f}%，部分矿工关机")
        
        return {
            "score": score,
            "signal": signal,
            "position_change": position_change,
            "hashrate_change": hashrate_change,
            "miner_reserve": miner['miner_reserve'],
            "details": " | ".join(details)
        }
    
    def _calculate_onchain_score(
        self,
        exchange: Dict,
        whale: Dict,
        network: Dict,
        holder: Dict,
        miner: Dict
    ) -> int:
        """计算链上综合评分"""
        score = 50  # 基准分
        
        score += exchange['score']
        score += whale['score']
        score += network['score']
        score += holder['score']
        score += miner['score']
        
        return max(0, min(100, score))
    
    def _generate_recommendation(
        self,
        score: int,
        exchange: Dict,
        holder: Dict
    ) -> Dict[str, Any]:
        """生成链上建议"""
        if score >= 70:
            direction = "看多"
            confidence = "高"
            reason = f"{exchange['signal']}，{holder['signal']}"
        elif score >= 55:
            direction = "偏多"
            confidence = "中"
            reason = "链上数据偏多但不强"
        elif score <= 30:
            direction = "看空"
            confidence = "高"
            reason = f"{exchange['signal']}，筹码松动"
        elif score <= 45:
            direction = "偏空"
            confidence = "中"
            reason = "链上数据偏空但不强"
        else:
            direction = "中性"
            confidence = "低"
            reason = "链上数据中性"
        
        return {
            "direction": direction,
            "confidence": confidence,
            "reason": reason
        }


# 测试代码
if __name__ == "__main__":
    async def test():
        engine = OnchainAnalysisEngine()
        
        report = await engine.analyze("BTC")
        
        print(f"链上分析报告:")
        print(f"  评分: {report['score']}/100")
        print(f"  交易所流动: {report['exchange_flows']['signal']}")
        print(f"  巨鲸动向: {report['whale_movements']['signal']}")
        print(f"  建议: {report['recommendation']['direction']} (置信度: {report['recommendation']['confidence']})")
    
    asyncio.run(test())
