"""跳水预测 XGBoost 模型训练 & 预测

基于 data_collector 产出的特征 + 标签，训练 XGBoost 分类模型。
自动保存/加载模型，增量更新。
"""
import os, json, pickle, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PATHS
from dive_prediction.data_collector import compute_features, ETF_CODE

CST = timezone(timedelta(hours=8))
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "xgboost_dive.pkl"
FEATURES_PATH = MODEL_DIR / "feature_list.json"


def _ensure_dir():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)


def prepare_training_data(df_raw: pd.DataFrame) -> tuple:
    """从原始日K线准备训练数据"""
    df = compute_features(df_raw).dropna()
    if df.empty or len(df) < 10:
        return None, None, None, None

    # 特征列
    feature_cols = [
        "ret1", "ret5", "ret10", "ret20",
        "amplitude_raw", "amp_ma5",
        "vol_ratio", "amount_ma5",
        "prev_ret5", "prev_amplitude",
        "consec_up", "high_low_ratio", "open_close_ratio",
    ]

    # 只保留有数据的特征
    available = [c for c in feature_cols if c in df.columns]
    X = df[available].values
    y = (df["target_dive"] >= 2).astype(int).values  # 二分类: 是否跳水≥2%

    # 时间序列切分: 前80%训练, 后20%验证
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    return X_train, X_val, y_train, y_val, available


def train(force: bool = False) -> dict:
    """训练 XGBoost 模型"""
    _ensure_dir()

    csv_path = PATHS["daily_kline"] / f"{ETF_CODE}_hist.csv"
    if not csv_path.exists():
        return {"status": "error", "msg": f"数据文件不存在: {csv_path}"}

    df = pd.read_csv(csv_path)
    result = prepare_training_data(df)
    if result[0] is None:
        return {"status": "error", "msg": "数据不足（<10行）"}

    X_train, X_val, y_train, y_val, features = result

    try:
        import xgboost as xgb
    except ImportError:
        return {"status": "error", "msg": "xgboost 未安装，执行 pip install xgboost"}

    # 如果不强制重训且已有模型，直接返回
    if MODEL_PATH.exists() and not force:
        model = pickle.loads(MODEL_PATH.read_bytes())
        # 仍然评估验证集
        val_pred = (model.predict_proba(X_val)[:, 1] >= 0.5).astype(int)
        acc = (val_pred == y_val).mean()
        return {
            "status": "skipped",
            "msg": f"模型已存在，验证集准确率: {acc:.1%}",
            "n_train": len(X_train), "n_val": len(X_val),
            "val_acc": round(float(acc), 4),
        }

    # 训练
    model = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, eval_metric="logloss",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    # 评估
    train_pred = (model.predict_proba(X_train)[:, 1] >= 0.5).astype(int)
    val_pred = (model.predict_proba(X_val)[:, 1] >= 0.5).astype(int)
    train_acc = (train_pred == y_train).mean()
    val_acc = (val_pred == y_val).mean()

    # 保存
    MODEL_PATH.write_bytes(pickle.dumps(model))
    FEATURES_PATH.write_text(json.dumps(features, indent=2))

    # 特征重要性
    importance = dict(zip(features, model.feature_importances_))
    top_features = sorted(importance.items(), key=lambda x: -x[1])[:5]

    return {
        "status": "trained",
        "n_train": len(X_train), "n_val": len(X_val),
        "train_acc": round(float(train_acc), 4),
        "val_acc": round(float(val_acc), 4),
        "top_features": [{"name": k, "importance": round(v, 3)} for k, v in top_features],
        "features": features,
    }


def predict_proba(features_df: pd.DataFrame) -> float:
    """用训练好的模型预测跳水概率"""
    if not MODEL_PATH.exists():
        return 0.0

    model = pickle.loads(MODEL_PATH.read_bytes())
    if not FEATURES_PATH.exists():
        return 0.0

    feature_list = json.loads(FEATURES_PATH.read_text())
    available = [c for c in feature_list if c in features_df.columns]
    if not available:
        return 0.0

    X = features_df[available].values
    prob = model.predict_proba(X)[0, 1]
    return round(float(prob) * 100, 1)


def main():
    import argparse
    p = argparse.ArgumentParser(description="XGBoost跳水预测模型训练")
    p.add_argument("--force", action="store_true", help="强制重训")
    p.add_argument("--predict", type=str, default="", help="预测最新一条的概率（last N days）")
    args = p.parse_args()

    if args.predict:
        csv_path = PATHS["daily_kline"] / f"{ETF_CODE}_hist.csv"
        if not csv_path.exists():
            print("⚠️ 无历史数据")
            return
        df = pd.read_csv(csv_path)
        feat = compute_features(df).ffill().bfill()
        prob = predict_proba(feat.iloc[-int(args.predict):])
        print(f"  跳水概率: {prob:.1f}%")
        return

    result = train(force=args.force)
    print(f"  状态: {result.get('status')}")
    print(f"  训练样本: {result.get('n_train', '?')}  验证样本: {result.get('n_val', '?')}")
    if "val_acc" in result:
        print(f"  验证准确率: {result['val_acc']:.1%}")
    if "top_features" in result:
        print(f"  最重要的特征:")
        for f in result["top_features"]:
            print(f"    {f['name']}: {f['importance']:.3f}")
    if "msg" in result:
        print(f"  信息: {result['msg']}")


if __name__ == "__main__":
    main()
