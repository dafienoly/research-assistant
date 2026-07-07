"""全特征模型评估 — 四个优先级全部集成"""
import sys, warnings
from pathlib import Path
import pandas as pd, numpy as np
warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dive_prediction.features import load_etf, load_leaders, compute_full_features, prepare_Xy
from dive_prediction.honest_eval import walk_forward_evaluate, backtest_simulation


def main():
    print("加载数据...")
    df_etf = load_etf()
    leaders = load_leaders()
    print(f"ETF: {len(df_etf)} 天, 龙头: {len(leaders)} 只")

    print("\n计算全部特征...")
    df = compute_full_features(df_etf, leaders)
    print(f"特征总计: {sum(1 for c in df.columns if c != 'date')} 列")

    for label_name, label_col, desc in [
        ("跳水≥4%", "label_dive_4pct", "原始定义"),
        ("跳水≥3%", "label_dive_3pct", "宽松"),
        ("跳水≥2.5%", "label_dive_25pct", "最宽松(Priority 4)"),
    ]:
        X, y, features = prepare_Xy(df, label_col)
        dive_rate = y.mean() * 100
        print(f"\n{'='*50}")
        print(f"  {label_name} ({desc}) — 跳水率 {dive_rate:.1f}% ({y.sum()}/{len(y)})")
        print(f"  特征数: {len(features)}")
        print(f"{'='*50}")

        if y.sum() < 3:
            print("  跳水样本太少(<3)，跳过")
            continue

        # Walk-Forward 验证
        result = walk_forward_evaluate(X, y)
        cm = result["confusion_matrix"]

        print(f"  Walk-Forward 验证:")
        print(f"    PR-AUC:     {result['pr_auc']:.4f}  (1.0=完美, 0.5=随机)")
        print(f"    F1:         {result['f1']:.4f}")
        print(f"    Precision:  {result['precision']:.2%}")
        print(f"    Recall:     {result['recall']:.2%}")
        print(f"    Confusion:  TN={cm['tn']} FP={cm['fp']} FN={cm['fn']} TP={cm['tp']}")

        # 回测
        sim = backtest_simulation(X, y)
        print(f"  回测: 预警{sim['total_trades']}次, 正确{sim['correct_warnings']}次, "
              f"命中率{sim['hit_rate']}%")

    # 新闻情感 (Priority 3)
    print(f"\n{'='*50}")
    print(f"  新闻情感特征 (Priority 3)")
    print(f"{'='*50}")
    print(f"  需要: 用浏览器去财联社/英为财情搜半导体新闻")
    print(f"  已确认: 浏览器可访问 cls.cn/telegraph")
    print(f"  下一步: 搜 '半导体 芯片 ETF' 关键词，LLM 打情绪分")


if __name__ == "__main__":
    main()
