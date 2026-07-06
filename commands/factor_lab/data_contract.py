"""No-Fallback Data Contract V5.5 — 数据契约: NaN 必须抛异常而非返回 0"""
import pandas as pd


class DataContractViolation(Exception):
    """数据契约被违反: 字段不应为 NaN 或空"""
    pass


def validate_series(series: pd.Series, field_name: str, nullable: bool = False):
    """验证字段无 NaN。nullable=True 时允许 NaN。"""
    if not nullable and series.isna().any():
        nan_count = series.isna().sum()
        raise DataContractViolation(
            f"字段 '{field_name}' 包含 {nan_count}/{len(series)} 个 NaN 值。"
            f" 不允许静默填充。请检查上游数据源。"
        )


def validate_dataframe(df: pd.DataFrame, required_fields: list[str]):
    """验证 DataFrame 包含必需字段且无 NaN"""
    missing = [f for f in required_fields if f not in df.columns]
    if missing:
        raise DataContractViolation(f"缺少必需字段: {missing}")
    for field in required_fields:
        validate_series(df[field], field)


def safe_factor_calc(df: pd.DataFrame, factor_name: str, required_cols: list[str],
                     calc_fn, fallback_value=None):
    """带契约的因子计算: 先验证数据完整性, 再计算, 而非先 fillna 再算。"""
    validate_dataframe(df, required_cols)
    result = calc_fn(df)
    validate_series(result, factor_name)
    return result
