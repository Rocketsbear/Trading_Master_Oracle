"""
数据验证器
确保所有数据真实可靠，防止编造数据
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from loguru import logger


class DataValidator:
    """数据验证器，确保不编造数据"""
    
    # 数据时效性阈值（秒）
    MAX_AGE = {
        "realtime": 60,          # 实时数据：1分钟
        "minute": 300,           # 分钟级：5分钟
        "hourly": 3600,          # 小时级：1小时
        "daily": 86400,          # 日级：1天
        "weekly": 604800,        # 周级：7天
        "monthly": 2592000,      # 月级：30天
    }
    
    @staticmethod
    def validate_data(
        data_source: str,
        data: Any,
        data_type: str = "hourly"
    ) -> Dict[str, Any]:
        """
        验证数据来源和时效性
        
        Args:
            data_source: 数据源名称
            data: 数据内容
            data_type: 数据类型（realtime, minute, hourly, daily, weekly, monthly）
            
        Returns:
            验证结果字典
        """
        if data is None:
            return {
                "valid": False,
                "message": f"❌ {data_source} 数据获取失败，无法提供分析",
                "data": None
            }
        
        # 检查数据时效性
        if isinstance(data, dict) and "timestamp" in data:
            timestamp = data["timestamp"]
            if isinstance(timestamp, datetime):
                age = (datetime.now() - timestamp).total_seconds()
                max_age = DataValidator.MAX_AGE.get(data_type, 3600)
                
                if age > max_age:
                    return {
                        "valid": False,
                        "message": f"⚠️ {data_source} 数据过期（超过 {max_age}秒），建议刷新",
                        "data": data,
                        "age": age
                    }
        
        return {
            "valid": True,
            "data": data,
            "source": data_source,
            "timestamp": datetime.now()
        }
    
    @staticmethod
    def format_output(section: str, data_status: Dict[str, Any]) -> str:
        """
        格式化输出，标注数据状态
        
        Args:
            section: 分析板块名称
            data_status: 数据验证状态
            
        Returns:
            格式化的输出字符串
        """
        if not data_status["valid"]:
            return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{section} | ❌ 数据不可用
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{data_status["message"]}

建议: 
1. 跳过此维度，或等待数据恢复后再分析
2. 或使用缓存数据（如果可用）
3. 或降低此维度的权重

⚠️ 警告: 缺少此维度数据可能导致判断偏差
"""
        
        # 标注数据时间戳和来源
        timestamp_str = data_status["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{section} | ✅ 数据有效
数据时间: {timestamp_str}
数据来源: {data_status["source"]}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    @staticmethod
    def check_data_completeness(data_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        检查数据完整性
        
        Args:
            data_dict: 包含多个数据源的字典
            
        Returns:
            完整性检查结果
        """
        total = len(data_dict)
        valid = sum(1 for v in data_dict.values() if v is not None)
        missing = [k for k, v in data_dict.items() if v is None]
        
        completeness = (valid / total * 100) if total > 0 else 0
        
        result = {
            "total": total,
            "valid": valid,
            "missing": missing,
            "completeness": completeness,
            "status": "good" if completeness >= 80 else "warning" if completeness >= 60 else "poor"
        }
        
        if missing:
            logger.warning(f"数据不完整: 缺失 {missing}")
        
        return result
    
    @staticmethod
    def create_data_report(
        section: str,
        data: Any,
        source: str,
        analysis: str,
        data_type: str = "hourly"
    ) -> str:
        """
        创建带数据验证的分析报告
        
        Args:
            section: 板块名称
            data: 原始数据
            source: 数据源
            analysis: 分析内容
            data_type: 数据类型
            
        Returns:
            完整的分析报告
        """
        # 验证数据
        validation = DataValidator.validate_data(source, data, data_type)
        
        if not validation["valid"]:
            return DataValidator.format_output(section, validation)
        
        # 生成报告头部
        header = DataValidator.format_output(section, validation)
        
        # 组合完整报告
        return f"{header}\n{analysis}"


# 测试代码
if __name__ == "__main__":
    import sys
    import io
    
    # 设置输出编码为 UTF-8
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    # 测试数据验证
    validator = DataValidator()
    
    # 测试有效数据
    valid_data = {
        "value": 100,
        "timestamp": datetime.now()
    }
    result = validator.validate_data("Binance", valid_data, "realtime")
    print("有效数据验证:")
    print(result)
    
    # 测试过期数据
    stale_data = {
        "value": 100,
        "timestamp": datetime.now() - timedelta(hours=2)
    }
    result = validator.validate_data("FRED", stale_data, "hourly")
    print("\n过期数据验证:")
    print(result)
    
    # 测试缺失数据
    result = validator.validate_data("API", None)
    print("\n缺失数据验证:")
    print(result)
    
    # 测试数据完整性
    data_dict = {
        "binance": {"value": 1},
        "coinank": {"value": 2},
        "fred": None,
        "news": {"value": 3}
    }
    completeness = validator.check_data_completeness(data_dict)
    print(f"\n数据完整性: {completeness}")
