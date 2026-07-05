"""Alpha Evaluation Hook V3.0 — 生成评估计划"""
from datetime import datetime, timezone, timedelta
from factor_lab.alpha.registry import get_alpha

CST = timezone(timedelta(hours=8))


def generate_evaluation_plan(alpha_id: str) -> dict:
    """生成 Alpha 评估计划 (不下单, 不回测)"""
    spec = get_alpha(alpha_id)
    if "error" in spec:
        return spec

    return {
        "alpha_id": alpha_id,
        "alpha_name": spec.get("name", ""),
        "generated_at": datetime.now(CST).isoformat(),
        "plan": {
            "stage_1": "数据准备: 检查 universe/data_requirements",
            "stage_2": "因子计算: 执行 factor_expression",
            "stage_3": "信号生成: 计算 signal_direction",
            "stage_4": "Backtest: 回测评估 (V3.1)",
            "stage_5": "Walk Forward: 滚动验证 (V3.1)",
            "stage_6": "Paper Apply: 进入 paper trading (V3.2)",
        },
        "status": "evaluation_plan_generated",
        "note": "本阶段只生成评估计划, 不执行交易",
    }
