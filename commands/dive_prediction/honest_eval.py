"""模型真实评估 — PR-AUC / F1 / Confusion Matrix / 回测收益

修复: 剔除同 day 特征泄漏，全部用前一天预测后一天。
"""
import sys, json, warnings
from pathlib import Path

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PATHS
from dive_prediction.data_collector import compute_features, ETF_CODE
from dive_prediction.proxy_bypass import call_no_proxy


def prepare_shifted_data(df_raw: pd.DataFrame) -> tuple:
    """准备真正的前瞻数据：用 T 日特征预测 T+1 日跳水"""
    df = compute_features(df_raw)
    # 跳水标签（T日）
    df["label_dive"] = ((df["intraday_drop"] >= 4) | (df["ret1"] <= -4)).astype(int)

    # 合法特征（仅 T-1 能拿到的数据）
    features = [
        "prev_ret5", "prev_amplitude", "consec_up",
        "day_of_week", "is_monday", "is_friday", "month_start", "month_end",
        # 从同天的特征也 shift
        "ret1", "ret5", "ret10", "ret20",
        "vol_ratio", "amount_ma5",
        "amplitude_raw", "amp_ma5",
        "high_low_ratio", "open_close_ratio",
    ]
    available = [c for c in features if c in df.columns]

    # Shift: 用 T 日特征预测 T+1 日
    X = df[available].shift(1).values
    y = df["label_dive"].values

    # 去除首行 NaN
    mask = ~np.isnan(X[:, 0])
    X, y = X[mask], y[mask]

    return X, y, available


def walk_forward_evaluate(X, y, n_window=50, step=20):
    """Walk-forward 验证：窗口从 n_window 开始，每次前移 step 天"""
    from xgboost import XGBClassifier
    from sklearn.metrics import f1_score, precision_recall_curve, auc, confusion_matrix

    all_y_true = []
    all_y_prob = []
    all_y_pred = []

    for start in range(n_window, len(X), step):
        end = min(start + step, len(X))
        if end - start < 5:
            break
        X_train, y_train = X[:start], y[:start]
        X_test, y_test = X[start:end], y[start:end]

        model = XGBClassifier(n_estimators=100, max_depth=4,
                              random_state=42, eval_metric="logloss", use_label_encoder=False)
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_test)[:, 1]
        pred = (prob >= 0.5).astype(int)

        all_y_true.extend(y_test)
        all_y_prob.extend(prob)
        all_y_pred.extend(pred)

    y_true = np.array(all_y_true)
    y_prob = np.array(all_y_prob)
    y_pred = np.array(all_y_pred)

    # PR-AUC
    precision, recall, _ = precision_recall_curve(y_true, y_prob)
    pr_auc = auc(recall, precision)

    # F1
    f1 = f1_score(y_true, y_pred)

    # Confusion Matrix
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, 0)

    return {
        "pr_auc": round(pr_auc, 4),
        "f1": round(f1, 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "total_samples": len(y_true),
        "dive_count": int(y_true.sum()),
        "precision": round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0,
    }


def backtest_simulation(X, y, n_window=50, step=20):
    """回测收益模拟：概率>50% 预警时减仓"""
    from xgboost import XGBClassifier

    balance = 1.0  # 初始净值
    hold_balance = 1.0  # 持有不动
    trades = 0
    correct = 0

    for start in range(n_window, len(X), step):
        end = min(start + step, len(X))
        if end - start < 5:
            break
        X_train, y_train = X[:start], y[:start]
        X_test, y_test = X[start:end], y[start:end]

        model = XGBClassifier(n_estimators=100, max_depth=4,
                              random_state=42, eval_metric="logloss")
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_test)[:, 1]

        for i in range(len(y_test)):
            # 持有不动：假设日收益 = 0（简化，只用做信号比较）
            # 模型策略：如果预警（prob>0.5）且明天真跳水 → 正确
            if prob[i] >= 0.5:
                trades += 1
                if y_test[i] == 1:
                    correct += 1

    return {
        "total_trades": trades,
        "correct_warnings": correct,
        "hit_rate": round(correct / trades * 100, 1) if trades > 0 else 0,
    }


def main():
    csv_path = PATHS["daily_kline"] / f"{ETF_CODE}_hist.csv"
    if not csv_path.exists():
        csv_path = PATHS["daily_kline"] / f"{ETF_CODE}_daily_kline.csv"
    if not csv_path.exists():
        print("❌ 无数据文件")
        return

    df = pd.read_csv(csv_path)
    print(f"数据: {len(df)} 条")

    X, y, features = prepare_shifted_data(df)
    print(f"样本: {len(X)} 天, 跳水: {y.sum()} 天 ({y.mean()*100:.1f}%)")
    print(f"特征: {len(features)} 个")

    print("\n=== Walk-Forward 验证 ===")
    result = walk_forward_evaluate(X, y)
    print(f"  PR-AUC:      {result['pr_auc']:.4f}  (1.0=完美, 0.5=随机)")
    print(f"  F1-score:    {result['f1']:.4f}")
    print(f"  Confusion:")
    cm = result['confusion_matrix']
    print(f"    True Neg:   {cm['tn']:>4d}  (正确预测不跳水)")
    print(f"    False Pos:  {cm['fp']:>4d}  (误报预警)")
    print(f"    False Neg:  {cm['fn']:>4d}  (漏报——跳水没预警)")
    print(f"    True Pos:   {cm['tp']:>4d}  (正确预警跳水)")
    print(f"  Precision:   {result['precision']:.2%}")
    print(f"  Recall:      {result['recall']:.2%}")

    print("\n=== 回测收益模拟 ===")
    sim = backtest_simulation(X, y)
    print(f"  总预警次数: {sim['total_trades']}")
    print(f"  正确预警:   {sim['correct_warnings']}")
    print(f"  命中率:     {sim['hit_rate']}%")

    print(f"\n结论: PR-AUC={result['pr_auc']:.3f}, F1={result['f1']:.3f}, "
          f"命中率={sim['hit_rate']}%")


if __name__ == "__main__":
    main()
