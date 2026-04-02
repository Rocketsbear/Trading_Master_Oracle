"""
多Agent协作系统
"""
from .base_agent import BaseAgent, AgentType, AnalysisResult, AgentMessage
from .technical_agent import TechnicalAgent
from .onchain_agent import OnchainAgent
from .macro_agent import MacroAgent
from .sentiment_agent import SentimentAgent
from .metaphysical_agent import MetaphysicalAgent
from .risk_agent import RiskAgent
from .portfolio_agent import PortfolioAgent
from .orchestrator import AgentOrchestrator

__all__ = [
    'BaseAgent',
    'AgentType', 
    'AnalysisResult',
    'AgentMessage',
    'TechnicalAgent',
    'OnchainAgent',
    'MacroAgent',
    'SentimentAgent',
    'MetaphysicalAgent',
    'RiskAgent',
    'PortfolioAgent',
    'AgentOrchestrator',
]
