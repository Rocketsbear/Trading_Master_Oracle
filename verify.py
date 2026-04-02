import asyncio, json, os, sys
sys.path.insert(0, 'D:\\All_in_AI\\Trading_system')

async def test():
    with open('D:\\All_in_AI\\Trading_system\\config\\api_keys.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    print("=" * 50)
    print("1. Binance (Technical Agent)")
    print("=" * 50)
    try:
        from backend.data_sources.exchanges.binance_api import BinanceDataSource
        b = BinanceDataSource()
        klines = await b.get_klines('BTCUSDT', '1h', 3)
        print(f"  K lines: {len(klines)}")
        print(f"  Latest close: {klines.iloc[-1]['close']}")
        print("  >>> REAL DATA")
    except Exception as e:
        print(f"  >>> ERROR: {e}")

    print()
    print("=" * 50)
    print("2. OnChain (OnChain Agent)")
    print("=" * 50)
    try:
        from backend.data_sources.onchain.onchainos import OnchainDataSource
        o = OnchainDataSource()
        d = await o.get_comprehensive_onchain_data('BTCUSDT')
        nf = d.get('exchange_flows', {}).get('net_flow')
        print(f"  net_flow: {nf}")
        if nf == -3221.7:
            print("  >>> MOCK DATA (hardcoded -3221.7)")
        else:
            print("  >>> REAL DATA")
    except Exception as e:
        print(f"  >>> ERROR: {e}")

    print()
    print("=" * 50)
    print("3. FRED (Macro Agent)")
    print("=" * 50)
    try:
        fk = cfg.get('fred', {}).get('api_key')
        from backend.data_sources.macro.fred import FREDDataSource
        fr = FREDDataSource(fk)
        d = await fr.get_comprehensive_macro_data()
        rate = d.get('fed_funds_rate', {}).get('value')
        print(f"  fed_rate: {rate}")
        print(f"  >>> {'REAL DATA' if rate else 'ERROR'}")
    except Exception as e:
        print(f"  >>> ERROR: {e}")

    print()
    print("=" * 50)
    print("4. Sentiment (Sentiment Agent)")
    print("=" * 50)
    try:
        jwt = cfg.get('6551', {}).get('jwt_token')
        from backend.data_sources.macro.sentiment import SentimentDataSource
        s = SentimentDataSource(jwt)
        d = await s.get_comprehensive_sentiment('BTCUSDT')
        score = d.get('overall_sentiment_score')
        print(f"  score: {score}")
        print(f"  keys: {list(d.keys())[:5]}")
    except Exception as e:
        print(f"  >>> ERROR: {e}")

    print()
    print("=" * 50)
    print("5. Metaphysical")
    print("=" * 50)
    try:
        from backend.data_sources.metaphysical.metaphysical import MetaphysicalDataSource
        m = MetaphysicalDataSource()
        d = await m.get_comprehensive_metaphysical_analysis()
        print(f"  score: {d.get('overall_score')}")
        print("  >>> ALGORITHM (no external API)")
    except Exception as e:
        print(f"  >>> ERROR: {e}")

    print()
    print("=" * 50)
    print("6. MiniMax LLM")
    print("=" * 50)
    try:
        mm = cfg.get('minimax', {})
        from backend.ai.llm_client import LLMClient
        c = LLMClient(
            api_key=mm['api_key'],
            base_url=mm.get('base_url', 'https://api.minimaxi.com/v1'),
            model=mm.get('model', 'MiniMax-M1'),
            max_retries=1,
        )
        r = await c.chat([{'role': 'user', 'content': 'say ok'}], max_tokens=10)
        print(f"  reply: {r}")
        print("  >>> WORKING")
    except Exception as e:
        err = str(e)
        if 'insufficient_balance' in err:
            print("  >>> INSUFFICIENT BALANCE (no credit)")
        elif '429' in err:
            print("  >>> RATE LIMITED")
        else:
            print(f"  >>> ERROR: {e}")

asyncio.run(test())
