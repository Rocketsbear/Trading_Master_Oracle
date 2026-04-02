"""
Trading Oracle - 数据源 & LLM 完整验证脚本
逐一测试每个组件，输出真实状态
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


async def test_all():
    results = {}

    # ═══ 1. MiniMax LLM ═══
    print("\n" + "="*60)
    print("🧠 TEST 1: MiniMax LLM (MiniMax-M1)")
    print("="*60)
    try:
        from backend.ai.llm_client import LLMClient
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'api_keys.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        mm = config.get('minimax', {})
        client = LLMClient(
            api_key=mm['api_key'],
            base_url=mm.get('base_url', 'https://api.minimaxi.com/v1'),
            model=mm.get('model', 'MiniMax-M1'),
        )
        reply = await client.chat(
            messages=[{"role": "user", "content": "用一句话回答：BTC是什么？"}],
            max_tokens=100,
        )
        print(f"  ✅ LLM 回复: {reply[:150]}")
        results['llm'] = '✅ 真实 AI 回复'
    except Exception as e:
        print(f"  ❌ LLM 失败: {e}")
        results['llm'] = f'❌ {e}'

    # ═══ 2. Binance (Technical Agent) ═══
    print("\n" + "="*60)
    print("📊 TEST 2: Binance API (Technical Agent)")
    print("="*60)
    try:
        from backend.data_sources.exchanges.binance_api import BinanceDataSource
        binance = BinanceDataSource()
        klines = await binance.get_klines('BTCUSDT', '1h', 5)
        if klines is not None and len(klines) > 0:
            last = klines.iloc[-1] if hasattr(klines, 'iloc') else klines[-1]
            print(f"  ✅ K线数据: {len(klines)} 根")
            print(f"  最新K线: {last}")
            results['binance'] = f'✅ 真实数据 ({len(klines)} K线)'
        else:
            print(f"  ❌ 无数据返回")
            results['binance'] = '❌ 无数据'
    except Exception as e:
        print(f"  ❌ Binance 失败: {e}")
        results['binance'] = f'❌ {e}'

    # ═══ 3. OnChain (OnChain Agent) ═══
    print("\n" + "="*60)
    print("⛓️ TEST 3: OnChain 数据源 (OnChain Agent)")
    print("="*60)
    try:
        from backend.data_sources.onchain.onchainos import OnchainDataSource
        onchain = OnchainDataSource()
        data = await onchain.get_comprehensive_onchain_data('BTCUSDT')
        # 检查数据是否是硬编码的
        flows = data.get('exchange_flows', {})
        net_flow = flows.get('net_flow')
        print(f"  数据返回: {json.dumps(data, indent=2, default=str)[:500]}")
        if net_flow == -3221.7:  # 硬编码的值
            print(f"  ⚠️ Mock 数据! (net_flow={net_flow} 是硬编码值)")
            results['onchain'] = '⚠️ Mock 硬编码数据'
        else:
            print(f"  ✅ 真实数据: net_flow={net_flow}")
            results['onchain'] = '✅ 真实数据'
    except Exception as e:
        print(f"  ❌ OnChain 失败: {e}")
        results['onchain'] = f'❌ {e}'

    # ═══ 4. FRED (Macro Agent) ═══
    print("\n" + "="*60)
    print("🌍 TEST 4: FRED API (Macro Agent)")
    print("="*60)
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'api_keys.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        fred_key = config.get('fred', {}).get('api_key')
        if fred_key:
            from backend.data_sources.macro.fred import FREDDataSource
            fred = FREDDataSource(fred_key)
            data = await fred.get_comprehensive_macro_data()
            fed_rate = data.get('fed_funds_rate', {})
            print(f"  联邦基金利率: {fed_rate}")
            if fed_rate and fed_rate.get('value') is not None:
                print(f"  ✅ 真实 FRED 数据: 利率={fed_rate.get('value')}%")
                results['fred'] = f"✅ 真实数据 (利率={fed_rate.get('value')}%)"
            else:
                print(f"  ⚠️ 部分数据可能是默认值")
                results['fred'] = '⚠️ 部分数据可能是默认值'
        else:
            print(f"  ❌ 无 FRED API Key")
            results['fred'] = '❌ 无 API Key'
    except Exception as e:
        print(f"  ❌ FRED 失败: {e}")
        results['fred'] = f'❌ {e}'

    # ═══ 5. Sentiment (Sentiment Agent) ═══
    print("\n" + "="*60)
    print("💬 TEST 5: 情绪数据源 (Sentiment Agent)")
    print("="*60)
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'api_keys.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        jwt = config.get('6551', {}).get('jwt_token')
        if jwt:
            from backend.data_sources.macro.sentiment import SentimentDataSource
            sentiment = SentimentDataSource(jwt)
            data = await sentiment.get_comprehensive_sentiment('BTCUSDT')
            score = data.get('overall_sentiment_score')
            print(f"  情绪数据: {json.dumps(data, indent=2, default=str)[:500]}")
            # 检查是否是模拟数据
            if data.get('note') and 'mock' in str(data.get('note', '')).lower():
                results['sentiment'] = '⚠️ Mock 数据'
            else:
                results['sentiment'] = f'✅ 数据 (score={score})'
        else:
            print(f"  ❌ 无 6551 JWT Token")
            results['sentiment'] = '❌ 无 JWT Token'
    except Exception as e:
        print(f"  ❌ Sentiment 失败: {e}")
        results['sentiment'] = f'❌ {e}'

    # ═══ 6. Metaphysical ═══
    print("\n" + "="*60)
    print("🔮 TEST 6: 玄学数据源 (Metaphysical Agent)")
    print("="*60)
    try:
        from backend.data_sources.metaphysical.metaphysical import MetaphysicalDataSource
        meta = MetaphysicalDataSource()
        data = await meta.get_comprehensive_metaphysical_analysis()
        print(f"  玄学数据: {json.dumps(data, indent=2, default=str)[:500]}")
        results['metaphysical'] = '⚠️ Mock/算法生成（玄学无"真实"数据源）'
    except Exception as e:
        print(f"  ❌ Metaphysical 失败: {e}")
        results['metaphysical'] = f'❌ {e}'

    # ═══ 汇总 ═══
    print("\n" + "="*60)
    print("📋 验证汇总")
    print("="*60)
    for name, status in results.items():
        print(f"  {name:15s} : {status}")


if __name__ == '__main__':
    asyncio.run(test_all())
