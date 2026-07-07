"""多标的联合训练 + 异常检测 + Walk-Forward 验证"""
import sys, warnings
from pathlib import Path
import pandas as pd, numpy as np
warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PATHS
from dive_prediction.features import load_etf, LEADER_CODES
from dive_prediction.honest_eval import walk_forward_evaluate, backtest_simulation

KLINE = PATHS["daily_kline"]
ETF_CODE = "159516"
# 更多半导体ETF（待数据拉取后启用）
EXTRA_ETFS = ["512480", "588290", "561980"]
ALL_INSTRUMENTS = [ETF_CODE] + LEADER_CODES


def load_all_instruments() -> list[pd.DataFrame]:
    """加载所有可用的标的日K线数据"""
    result = []
    for code in ALL_INSTRUMENTS:
        path = KLINE / f"{code}_daily_kline.csv"
        if path.exists():
            df = pd.read_csv(path)
            df["code"] = code
            result.append(df)
    # 尝试加载其他ETF
    for code in EXTRA_ETFS:
        path = KLINE / f"{code}_daily_kline.csv"
        if path.exists():
            df = pd.read_csv(path)
            df["code"] = code
            result.append(df)
    return result


def compute_multi_features(df_list: list[pd.DataFrame]) -> tuple:
    """多标的一起计算特征，输出 (X, y, feature_names)"""
    from dive_prediction.features import compute_full_features, prepare_Xy, load_etf, load_leaders

    all_X, all_y = [], []
    feature_names = None

    for df in df_list:
        code = df["code"].iloc[0]
        etf = df.rename(columns={"timeString": "date"}) if "timeString" in df else df
        if "code" in etf.columns:
            etf = etf.drop(columns=["code"])
        
        leaders = {}
        if code in [ETF_CODE] + EXTRA_ETFS:
            for lc in LEADER_CODES:
                lp = KLINE / f"{lc}_daily_kline.csv"
                if lp.exists():
                    leaders[lc] = pd.read_csv(lp)

        feat = compute_full_features(etf, leaders if code in [ETF_CODE] + EXTRA_ETFS else {})
        X, y, names = prepare_Xy(feat, "label_dive_25pct")
        
        if feature_names is None:
            feature_names = names
        else:
            # 对齐特征列：缺失的补0，多余的截掉
            X_df = pd.DataFrame(X, columns=names)
            for col in feature_names:
                if col not in X_df.columns:
                    X_df[col] = 0
            X = X_df[feature_names].values
        
        all_X.append(X)
        all_y.append(y)

    # 合并
    X_all = np.vstack(all_X)
    y_all = np.concatenate(all_y)
    return X_all, y_all, feature_names


def clean_nan(X, y):
    """移除 NaN"""
    mask = ~pd.DataFrame(X).isna().any(axis=1).values if len(X) > 0 else slice(None)
    return X[mask], y[mask]


def evaluate_with_balancing(X, y, method="xgboost"):
    """Walk-forward 验证（含 SMOTE 过采样处理不平衡）"""
    from xgboost import XGBClassifier
    from sklearn.ensemble import RandomForestClassifier, IsolationForest
    from sklearn.metrics import precision_recall_curve, auc, f1_score, confusion_matrix

    all_y_true, all_y_prob, all_y_pred = [], [], []
    n_window, step = 60, 20

    for start in range(n_window, len(X), step):
        end = min(start + step, len(X))
        if end - start < 5:
            break
        X_train, y_train = X[:start], y[:start]
        X_test, y_test = X[start:end], y[start:end]

        if method == "xgboost":
            # XGBoost + scale_pos_weight 处理不平衡
            scale = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
            model = XGBClassifier(n_estimators=100, max_depth=4, scale_pos_weight=scale,
                                  random_state=42, eval_metric="logloss")
            model.fit(X_train, y_train)
            prob = model.predict_proba(X_test)[:, 1]
        elif method == "random_forest":
            model = RandomForestClassifier(n_estimators=200, max_depth=6,
                                            class_weight="balanced", random_state=42)
            model.fit(X_train, y_train)
            prob = model.predict_proba(X_test)
            prob = prob[:, 1] if prob.shape[1] > 1 else np.full(len(prob), 0.0)
        elif method == "isolation_forest":
            # Isolation Forest: anomaly detection
            model = IsolationForest(contamination=0.05, random_state=42)
            model.fit(X_train)
            # 分数转概率（负的越远越异常）
            scores = model.decision_function(X_test)
            prob = 1 - (scores - scores.min()) / (scores.max() - scores.min() + 1e-9)
        else:
            raise ValueError(f"unknown method: {method}")

        pred = (prob >= 0.5).astype(int)
        all_y_true.extend(y_test)
        all_y_prob.extend(prob)
        all_y_pred.extend(pred)

    y_true = np.array(all_y_true)
    y_prob = np.array(all_y_prob)
    y_pred = np.array(all_y_pred)

    # PR-AUC
    prec, rec, _ = precision_recall_curve(y_true, y_prob)
    pr_auc = auc(rec, prec)
    # F1
    f1 = f1_score(y_true, y_pred)
    # Confusion
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, 0)

    return {
        "pr_auc": round(pr_auc, 4),
        "f1": round(f1, 4),
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "precision": round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0,
        "total": len(y_true),
        "dives": int(y_true.sum()),
    }


def main():
    print("加载多标的数据...")
    dfs = load_all_instruments()
    print(f"  标的数: {len(dfs)}")
    for df in dfs:
        print(f"    {df['code'].iloc[0]}: {len(df)} 天")

    print("\n计算特征（合并训练）...")
    X, y, features = compute_multi_features(dfs)
    X, y = clean_nan(X, y)
    print(f"  总样本: {len(X)}, 跳水: {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"  特征: {len(features)}")

    for method in ["xgboost", "random_forest", "isolation_forest"]:
        print(f"\n  === {method} ===")
        result = evaluate_with_balancing(X, y, method=method)
        cm = result["confusion"]
        print(f"  PR-AUC:     {result['pr_auc']:.4f}")
        print(f"  F1:         {result['f1']:.4f}")
        print(f"  Precision:  {result['precision']:.2%}")
        print(f"  Recall:     {result['recall']:.2%}")
        print(f"  Confusion:  TN={cm['tn']} FP={cm['fp']} FN={cm['fn']} TP={cm['tp']}")
        print(f"  样本: {result['total']}, 跳水: {result['dives']}")


if __name__ == "__main__":
    main()
