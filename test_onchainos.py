"""Test fixed onchainos.py integration"""
import asyncio, sys
sys.path.insert(0, ".")
from backend.data_sources.onchain.onchainos import OnchainDataSource

async def test():
    o = OnchainDataSource(
        api_key="26082748-a642-40a9-ac45-40fa0832c8b1",
        api_secret="BBC1397099F43D88FD6A9592E3DF29EF",
        passphrase="zhenZhen001!",
    )
    print(f"has_keys: {o._has_onchainos_keys}")
    
    print("\n=== DEX Trades (ETH on Ethereum) ===")
    trades = await o.get_dex_trades("ETHUSDT", chain="1", limit=20)
    print(f"  total: {trades.get('total_trades')}, buys: {trades.get('buys')}, sells: {trades.get('sells')}")
    print(f"  buy_ratio: {trades.get('buy_ratio')}%, vol: ${trades.get('total_volume_usd'):,.0f}")
    print(f"  source: {trades.get('source')}")
    if trades.get("top_trades"):
        for t in trades["top_trades"][:3]:
            print(f"    {t['type']} ${t['volume_usd']:,.0f} on {t['dex']}")
    
    print("\n=== DEX Price (ETH) ===")
    price = await o.get_dex_price("ETHUSDT")
    print(f"  price: ${price.get('price', 0):,.2f}, source: {price.get('source')}")
    
    print("\n=== Index Price (ETH) ===")
    idx = await o.get_index_price("ETHUSDT")
    print(f"  index: ${idx.get('index_price', 0):,.2f}, source: {idx.get('source')}")
    
    print("\n=== Smart Money Signals (Solana) ===")
    signals = await o.get_smart_money_signals(["501"])
    print(f"  total: {signals.get('total_signals')}, SM: {signals.get('smart_money_count')}, W: {signals.get('whale_count')}, K: {signals.get('kol_count')}")
    
    print("\n=== Comprehensive (BTCUSDT) ===")
    data = await o.get_comprehensive_onchain_data("BTCUSDT")
    print(f"  source: {data.get('source')}")
    print(f"  onchainos_active: {data.get('onchainos_active')}")
    print(f"  trades: total={data['trades'].get('total_trades')}, buy_ratio={data['trades'].get('buy_ratio')}%")
    print(f"  signals: SM={data['signals'].get('smart_money_count')}, W={data['signals'].get('whale_count')}")
    if data.get('price_deviation_pct') is not None:
        print(f"  CEX/Index deviation: {data['price_deviation_pct']:+.3f}%")
    else:
        print(f"  CEX/Index deviation: N/A")
    
    await o.close()
    print("\n✅ ALL DONE")

asyncio.run(test())
