"""
Tushare Provider 包 — V4.0 统一入口

用法:
    from commands.data_providers.tushare import (
        TushareMarketProvider,
        TushareFinaProvider,
        TushareFundFlowProvider,
        TushareEventProvider,
        TushareStockProvider,
        get_all_providers,
        capabilities_summary,
    )

    market = TushareMarketProvider()
    df = market.daily(ts_code='688012.SH', start_date='20240101', end_date='20240331')
"""

try:
    from commands.data_providers.tushare.tushare_market import TushareMarketProvider
except ModuleNotFoundError:
    from data_providers.tushare.tushare_market import TushareMarketProvider

try:
    from commands.data_providers.tushare.tushare_fina import TushareFinaProvider
except ModuleNotFoundError:
    from data_providers.tushare.tushare_fina import TushareFinaProvider

try:
    from commands.data_providers.tushare.tushare_fund_flow import TushareFundFlowProvider
except ModuleNotFoundError:
    from data_providers.tushare.tushare_fund_flow import TushareFundFlowProvider

try:
    from commands.data_providers.tushare.tushare_event import TushareEventProvider
except ModuleNotFoundError:
    from data_providers.tushare.tushare_event import TushareEventProvider

try:
    from commands.data_providers.tushare.tushare_stock import TushareStockProvider
except ModuleNotFoundError:
    from data_providers.tushare.tushare_stock import TushareStockProvider

try:
    from commands.data_providers import BaseProvider, ProviderCapability, ProviderHealth
except ModuleNotFoundError:
    from data_providers import BaseProvider, ProviderCapability, ProviderHealth

__all__ = [
    "TushareMarketProvider",
    "TushareFinaProvider",
    "TushareFundFlowProvider",
    "TushareEventProvider",
    "TushareStockProvider",
    "BaseProvider",
    "ProviderCapability",
    "ProviderHealth",
    "get_all_providers",
    "capabilities_summary",
]


def get_all_providers() -> list:
    """返回所有已实现的 Tushare Provider 实例"""
    return [
        TushareMarketProvider(),
        TushareFinaProvider(),
        TushareStockProvider(),
        TushareFundFlowProvider(),
        TushareEventProvider(),
    ]


def capabilities_summary() -> dict:
    """返回所有 Provider 的能力汇总"""
    summary = {}
    for p in get_all_providers():
        cap = p.capability
        enabled = {k: v for k, v in cap.__dict__.items()
                   if k.startswith("can_") and v}
        summary[cap.name] = enabled
    return summary
