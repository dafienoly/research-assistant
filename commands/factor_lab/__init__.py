"""factor_lab — 因子研究实验室 (V3.2)

模块结构:
  factor_evaluation      统一评估 API (IC/ICIR/反过拟合/Walk-Forward/正交性/评分)
  ic_analyzer            IC/ICIR 计算 & 分层回测
  validation             反过拟合 & Walk-Forward 验证
  orthogonality          正交性分析 & 增量价值
  scoring                因子评分 (家族感知)
  factor_base            因子注册表 & 基类
  factor_engine          因子计算引擎

快速开始:
    from factor_lab.factor_evaluation import run_full_evaluation, FactorEvaluation

    # 一站式评估
    report = run_full_evaluation(df, close_pivot, factor_name="ret5")

    # 分步控制
    ev = FactorEvaluation()
    ic = ev.evaluate_ic(df, "ret5")
    ao = ev.evaluate_anti_overfit(df, "ret5", close_pivot)
    score = ev.evaluate_scoring(ao)
"""
