"""通用策略挖掘与回测框架 — Strategy Lab

模块组成:
  strategy_lab/
    __init__.py       — 入口调度
    universe.py       — 股票池构建
    factor_registry.py — 因子管理
    backtest.py       — 通用回测引擎
    executor.py       — 交易约束模拟
    param_search.py   — 参数搜索
    walk_forward.py   — 滚动验证
    regime.py         — 市场环境拆分
    ranker.py         — 策略排行
    paper.py          — 模拟交易信号
    publisher.py      — package 发布
"""
