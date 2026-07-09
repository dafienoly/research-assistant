"""表达式解析器 V2 — 支持比较/逻辑运算 + 缺失算子 + 别名表

升级来源于 QuantGPT 的 42+ AST 算子设计，结合纯 Python 执行。

新增:
  - 比较运算: > < >= <= == !=
  - 逻辑运算: and or && ||
  - 幂运算: ^ (Power)
  - 缺失算子: ts_shift, ts_argmax, ts_argmin, ts_product, ts_zscore,
              power, sqrt, exp, max, min
  - Bollinger: boll_upper, boll_lower, boll_mid, bb_width
  - 别名表: delta→ts_delta, delay→ts_shift, sma→ts_mean, stddev→ts_std 等
  - 验证优化: 返回详细错误信息

用法:
  parser = ExpressionParser()
  tree = parser.parse("rank(close / ts_mean(close, 20))")
  result = tree.eval(df)  # 返回 pd.Series
"""

import re
import numpy as np
import pandas as pd
from typing import Any, Optional

# ═══════════════════════════════════════════════════════
# AST 节点类型
# ═══════════════════════════════════════════════════════

class Node:
    def eval(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

class Number(Node):
    def __init__(self, value: float):
        self.value = value
    def eval(self, df):
        return pd.Series(float(self.value), index=df.index)

class Field(Node):
    def __init__(self, name: str):
        self.name = name
    def eval(self, df):
        if self.name in df.columns:
            return df[self.name].astype(float)
        raise ValueError(f"未知字段: {self.name}")

class BinaryOp(Node):
    def __init__(self, op: str, left: Node, right: Node):
        self.op = op; self.left = left; self.right = right
    def eval(self, df):
        l = self.left.eval(df); r = self.right.eval(df)
        if self.op == "+": return l + r
        if self.op == "-": return l - r
        if self.op == "*": return l * r
        if self.op == "/": return l / r.replace(0, np.nan)
        raise ValueError(f"未知运算符: {self.op}")

class ComparisonOp(Node):
    """比较运算: > < >= <= == != 返回 0.0 / 1.0"""
    def __init__(self, op: str, left: Node, right: Node):
        self.op = op; self.left = left; self.right = right
    def eval(self, df):
        l = self.left.eval(df); r = self.right.eval(df)
        if self.op == "GT":  return (l > r).astype(float)
        if self.op == "LT":  return (l < r).astype(float)
        if self.op == "GE":  return (l >= r).astype(float)
        if self.op == "LE":  return (l <= r).astype(float)
        if self.op == "EQ":  return (l == r).astype(float)
        if self.op == "NE":  return (l != r).astype(float)
        raise ValueError(f"未知比较运算符: {self.op}")

class LogicalOp(Node):
    """逻辑运算: and or 返回 0.0 / 1.0"""
    def __init__(self, op: str, left: Node, right: Node):
        self.op = op; self.left = left; self.right = right
    def eval(self, df):
        l = self.left.eval(df).astype(bool)
        r = self.right.eval(df).astype(bool)
        if self.op == "AND": return (l & r).astype(float)
        if self.op == "OR":  return (l | r).astype(float)
        raise ValueError(f"未知逻辑运算符: {self.op}")

class FuncCall(Node):
    def __init__(self, name: str, args: list):
        self.name = name.lower()
        self.args = args
    def eval(self, df):
        if self.name not in FUNC_REGISTRY:
            raise ValueError(f"未知函数: {self.name}")
        return FUNC_REGISTRY[self.name](df, self.args)

# ═══════════════════════════════════════════════════════
# 算子注册表
# ═══════════════════════════════════════════════════════

FUNC_REGISTRY = {}

def register_op(name: str):
    def wrapper(fn):
        FUNC_REGISTRY[name] = fn
        return fn
    return wrapper

# ── 截面算子 (cross-sectional) ────────────────────────

def _cs_apply(df, args, fn):
    val = args[0].eval(df)
    return val.groupby(df["date"]).transform(fn)

@register_op("rank")
def op_rank(df, args):
    return _cs_apply(df, args, lambda x: x.rank(pct=True))

@register_op("zscore")
def op_zscore(df, args):
    def _z(x):
        s = x.std()
        if isinstance(s, pd.Series):
            s = s.replace(0, np.nan)
        elif hasattr(s, 'shape') and s.ndim > 0:
            s[s == 0] = np.nan
        elif s == 0:
            s = np.nan
        return (x - x.mean()) / s
    return _cs_apply(df, args, _z)

@register_op("scale")
def op_scale(df, args):
    def _s(x):
        return (x - x.min()) / (x.max() - x.min() + 1e-10)
    return _cs_apply(df, args, _s)

# ── 时序算子 (time-series) ────────────────────────────

def _ts_apply(df, args, fn):
    val = args[0].eval(df)
    return val.groupby(df["symbol"]).transform(fn)

def _get_window(args, idx=1, default=20):
    if len(args) > idx:
        w = args[idx].eval(pd.DataFrame({"x": [1]}))
        return int(w.iloc[0]) if hasattr(w, 'iloc') else int(w)
    return default

@register_op("ts_mean")
def op_ts_mean(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).mean())

@register_op("ts_std")
def op_ts_std(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).std().fillna(0))

@register_op("ts_min")
def op_ts_min(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).min())

@register_op("ts_max")
def op_ts_max(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).max())

@register_op("ts_sum")
def op_ts_sum(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).sum())

@register_op("ts_rank")
def op_ts_rank(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).apply(
        lambda y: pd.Series(y).rank(pct=True).iloc[-1] if len(y) > 1 else 0.5, raw=False))

@register_op("ts_delta")
def op_ts_delta(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.diff(w))

@register_op("ts_av_diff")
def op_ts_av_diff(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x - x.rolling(w, min_periods=1).mean())

@register_op("ts_decay_linear")
def op_ts_decay_linear(df, args):
    w = _get_window(args)
    def _decay(s):
        if len(s) < w:
            return s.iloc[-1] if len(s) > 0 else 0
        weights = np.arange(1, w + 1)
        return np.dot(s.values[-w:], weights) / weights.sum()
    return _ts_apply(df, args, lambda x: x.rolling(w).apply(_decay, raw=False))

@register_op("ts_corr")
def op_ts_corr(df, args):
    w = _get_window(args, idx=2) if len(args) > 2 else 20
    a = args[0].eval(df); b = args[1].eval(df)
    return a.groupby(df["symbol"]).transform(lambda x: x.rolling(w).corr(b))

@register_op("ts_cov")
def op_ts_cov(df, args):
    w = _get_window(args, idx=2) if len(args) > 2 else 20
    a = args[0].eval(df); b = args[1].eval(df)
    return a.groupby(df["symbol"]).transform(lambda x: x.rolling(w).cov(b))

# ── 新增时序算子 ──────────────────────────────────────

@register_op("ts_shift")
def op_ts_shift(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.shift(w))

@register_op("ts_argmax")
def op_ts_argmax(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).apply(
        lambda y: np.argmax(y) if len(y) > 0 else np.nan, raw=True))

@register_op("ts_argmin")
def op_ts_argmin(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).apply(
        lambda y: np.argmin(y) if len(y) > 0 else np.nan, raw=True))

@register_op("ts_product")
def op_ts_product(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).apply(
        lambda y: np.prod(y) if len(y) > 0 else np.nan, raw=True))

@register_op("ts_zscore")
def op_ts_zscore(df, args):
    w = _get_window(args)
    def _z(s):
        if len(s) < 2: return 0.0
        return (s.iloc[-1] - s.mean()) / (s.std(ddof=0) + 1e-10)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=2).apply(
        lambda y: (y[-1] - np.mean(y)) / (np.std(y) + 1e-10), raw=True))

# ── 技术指标 ──────────────────────────────────────────

@register_op("ema")
def op_ema(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.ewm(span=w, adjust=False).mean())

@register_op("sma")
def op_sma(df, args):
    return op_ts_mean(df, args)

@register_op("rsi")
def op_rsi(df, args):
    w = _get_window(args)
    def _rsi(s):
        if len(s) < w:
            return 50.0
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(w).mean()
        loss = (-delta).clip(lower=0).rolling(w).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)
    return _ts_apply(df, args, _rsi)

# ── Bollinger Bands ───────────────────────────────────

@register_op("bb_width")
def op_bb_width(df, args):
    w = _get_window(args)
    def _bb(s):
        if len(s) < w: return 0.0
        mid = s.rolling(w, min_periods=1).mean().iloc[-1]
        std = s.rolling(w, min_periods=1).std().iloc[-1]
        upper = mid + 2 * std
        lower = mid - 2 * std
        return (upper - lower) / (mid + 1e-10)
    return _ts_apply(df, args, _bb)

@register_op("boll_upper")
def op_boll_upper(df, args):
    w = _get_window(args)
    def _up(s):
        if len(s) < w: return 0.0
        mid = s.rolling(w, min_periods=1).mean().iloc[-1]
        std = s.rolling(w, min_periods=1).std().iloc[-1]
        return mid + 2 * std
    return _ts_apply(df, args, _up)

@register_op("boll_lower")
def op_boll_lower(df, args):
    w = _get_window(args)
    def _lo(s):
        if len(s) < w: return 0.0
        mid = s.rolling(w, min_periods=1).mean().iloc[-1]
        std = s.rolling(w, min_periods=1).std().iloc[-1]
        return mid - 2 * std
    return _ts_apply(df, args, _lo)

@register_op("boll_mid")
def op_boll_mid(df, args):
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x.rolling(w, min_periods=1).mean())

# ── 非线性/辅助算子 ──────────────────────────────────

@register_op("abs")
def op_abs(df, args):
    return args[0].eval(df).abs()

@register_op("sign")
def op_sign(df, args):
    return np.sign(args[0].eval(df))

@register_op("sigmoid")
def op_sigmoid(df, args):
    return 1 / (1 + np.exp(-args[0].eval(df)))

@register_op("tanh")
def op_tanh(df, args):
    return np.tanh(args[0].eval(df))

@register_op("clip")
def op_clip(df, args):
    val = args[0].eval(df)
    lo = float(args[1].eval(df).iloc[0]) if len(args) > 1 else -3
    hi = float(args[2].eval(df).iloc[0]) if len(args) > 2 else 3
    return val.clip(lo, hi)

@register_op("where")
def op_where(df, args):
    cond = args[0].eval(df).astype(bool)
    t = args[1].eval(df); f = args[2].eval(df)
    return pd.Series(np.where(cond, t, f), index=df.index)

@register_op("sign_power")
def op_sign_power(df, args):
    val = args[0].eval(df)
    exp = float(args[1].eval(df).iloc[0]) if len(args) > 1 else 0.5
    return np.sign(val) * (np.abs(val) ** exp)

@register_op("log")
def op_log(df, args):
    return np.log(args[0].eval(df).replace(0, np.nan).abs().clip(1e-10))

# ── 新增二元/一元算子 ────────────────────────────────

@register_op("power")
def op_power(df, args):
    val = args[0].eval(df)
    if len(args) > 1:
        exp = args[1].eval(df)
        return val ** exp
    return val ** 2

@register_op("sqrt")
def op_sqrt(df, args):
    return np.sqrt(args[0].eval(df).clip(0))

@register_op("exp")
def op_exp(df, args):
    return np.exp(args[0].eval(df).clip(-500, 500))

@register_op("max")
def op_max(df, args):
    a = args[0].eval(df); b = args[1].eval(df)
    return pd.concat([a, b], axis=1).max(axis=1)

@register_op("min")
def op_min(df, args):
    a = args[0].eval(df); b = args[1].eval(df)
    return pd.concat([a, b], axis=1).min(axis=1)

# ── 别名表 ────────────────────────────────────────────

def _setup_aliases():
    ALIAS_MAP = {
        "delta": "ts_delta",
        "delay": "ts_shift",
        "ts_delay": "ts_shift",
        "covariance": "ts_cov",
        "correlation": "ts_corr",
        "ts_covariance": "ts_cov",
        "stddev": "ts_std",
        "ts_std_dev": "ts_std",
        "ts_arg_max": "ts_argmax",
        "ts_arg_min": "ts_argmin",
        "wma": "ts_decay_linear",
        "pow": "power",
    }
    for alias, target in ALIAS_MAP.items():
        if target in FUNC_REGISTRY and alias not in FUNC_REGISTRY:
            FUNC_REGISTRY[alias] = FUNC_REGISTRY[target]

_setup_aliases()

# ═══════════════════════════════════════════════════════
# 分词器
# ═══════════════════════════════════════════════════════

TOKEN_SPEC = [
    ("GE",      r">="),
    ("LE",      r"<="),
    ("EQ",      r"=="),
    ("NE",      r"!="),
    ("GT",      r">"),
    ("LT",      r"<"),
    ("AND",     r"and\b|\&\&"),
    ("OR",      r"or\b|\|\|"),
    ("CARET",   r"\^"),
    ("NUMBER",  r"\d+\.?\d*"),
    ("FIELD",   r"[a-zA-Z_][a-zA-Z0-9_]*"),
    ("LPAREN",  r"\("),
    ("RPAREN",  r"\)"),
    ("COMMA",   r","),
    ("OP",      r"[+\-*/]"),
    ("SKIP",    r"\s+"),
]

TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in TOKEN_SPEC))


class Token:
    def __init__(self, type, value, pos):
        self.type = type; self.value = value; self.pos = pos
    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, {self.pos})"


def tokenize(s: str) -> list:
    tokens = []
    for m in TOKEN_RE.finditer(s):
        if m.lastgroup == "SKIP":
            continue
        tokens.append(Token(m.lastgroup, m.group(), m.start()))
    return tokens


# ═══════════════════════════════════════════════════════
# 递归下降解析器
# ═══════════════════════════════════════════════════════
#
# 优先级 (从低到高):
#   or_expr      ← or ||
#   and_expr     ← and &&
#   comparison   ← < <= > >= == !=
#   additive     ← + -
#   multiplicative ← * /
#   power        ← ^            (右结合)
#   unary        ← - (负号)
#   primary      ← 数字 / 字段 / (expr) / 函数调用
# ═══════════════════════════════════════════════════════

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens; self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected=None):
        t = self.peek()
        if t is None:
            raise SyntaxError("表达式意外结束")
        if expected and t.type != expected and t.value != expected:
            raise SyntaxError(f"期望 {expected}，得到 {t.value} (位置 {t.pos})")
        self.pos += 1
        return t

    def parse(self) -> Node:
        node = self._or_expr()
        if self.peek():
            raise SyntaxError(f"表达式结束后多余 token: {self.peek().value} (位置 {self.peek().pos})")
        return node

    def _or_expr(self) -> Node:
        node = self._and_expr()
        while self.peek() and self.peek().type == "OR":
            self.consume()
            right = self._and_expr()
            node = LogicalOp("OR", node, right)
        return node

    def _and_expr(self) -> Node:
        node = self._comparison()
        while self.peek() and self.peek().type == "AND":
            self.consume()
            right = self._comparison()
            node = LogicalOp("AND", node, right)
        return node

    def _comparison(self) -> Node:
        node = self._additive()
        while self.peek() and self.peek().type in ("GT", "LT", "GE", "LE", "EQ", "NE"):
            op = self.consume().type
            right = self._additive()
            node = ComparisonOp(op, node, right)
        return node

    def _additive(self) -> Node:
        node = self._multiplicative()
        while self.peek() and self.peek().type == "OP" and self.peek().value in ("+", "-"):
            op = self.consume().value
            right = self._multiplicative()
            node = BinaryOp(op, node, right)
        return node

    def _multiplicative(self) -> Node:
        node = self._power()
        while self.peek() and self.peek().type == "OP" and self.peek().value in ("*", "/"):
            op = self.consume().value
            right = self._power()
            node = BinaryOp(op, node, right)
        return node

    def _power(self) -> Node:
        node = self._unary()
        if self.peek() and self.peek().type == "CARET":
            self.consume()
            right = self._power()
            node = FuncCall("power", [node, right])
        return node

    def _unary(self) -> Node:
        t = self.peek()
        if t is None:
            raise SyntaxError("表达式意外结束")
        if t.type == "OP" and t.value == "-":
            self.consume()
            return BinaryOp("*", Number(-1.0), self._unary())
        return self._primary()

    def _primary(self) -> Node:
        t = self.peek()
        if t is None:
            raise SyntaxError("表达式意外结束")
        if t.type == "NUMBER":
            self.consume()
            return Number(float(t.value))
        if t.type == "FIELD":
            self.consume()
            name = t.value
            if self.peek() and self.peek().type == "LPAREN":
                self.consume()
                args = []
                if self.peek() and self.peek().type != "RPAREN":
                    args.append(self._or_expr())
                    while self.peek() and self.peek().type == "COMMA":
                        self.consume()
                        args.append(self._or_expr())
                self.consume("RPAREN")
                return FuncCall(name, args)
            return Field(name)
        if t.type == "LPAREN":
            self.consume()
            node = self._or_expr()
            self.consume("RPAREN")
            return node
        raise SyntaxError(f"意外的 token: {t.value} (位置 {t.pos})")


# ═══════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════

class ExpressionParser:
    """表达式解析器入口"""

    def parse(self, expression: str) -> Node:
        tokens = tokenize(expression)
        parser = Parser(tokens)
        return parser.parse()

    def eval(self, expression: str, df: pd.DataFrame) -> pd.Series:
        node = self.parse(expression)
        return node.eval(df)

    def validate(self, expression: str) -> str:
        try:
            self.parse(expression)
            return ""
        except (SyntaxError, ValueError) as e:
            return str(e)

    @property
    def operators(self) -> list:
        return sorted(FUNC_REGISTRY.keys())


# ═══════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = ExpressionParser()
    tests = [
        # V1 向后兼容
        "rank(close / ts_mean(close, 20))",
        "rank(ret5) * rank(vol_ratio60)",
        "(close - ts_min(low, 10)) / (ts_max(high, 10) - ts_min(low, 10))",
        "rank(reversal5) * rank(vol_ratio60)",
        "ts_decay_linear(close / vwap, 10)",
        "rank(ts_corr(close, volume, 20))",
        "sigmoid(zscore(close / ts_mean(close, 20)))",
        # V2: 比较运算
        "where(returns > 0, 1, 0)",
        "where(close < ts_mean(close, 20), 1, 0)",
        "where(close >= open and volume > ts_mean(volume, 20), 1, 0)",
        "where(returns > 0 and close < ts_mean(close, 20), 1, 0)",
        "where(close == open or volume > ts_mean(volume, 5), 1, 0)",
        # V2: 缺失算子
        "ts_shift(close, 5)",
        "ts_argmax(high, 20) > ts_argmin(low, 20)",
        "ts_product(close / open, 5)",
        "ts_zscore(returns, 20)",
        "power(rank(close), 2)",
        "sqrt(abs(returns))",
        "exp(zscore(returns))",
        "max(ts_mean(close, 5), ts_mean(close, 20))",
        "min(close, open)",
        # V2: 别名
        "delta(close, 5)",
        "delay(volume, 1)",
        "correlation(close, volume, 20)",
        "stddev(returns, 20)",
        "sma(close, 10)",
        # V2: 幂运算
        "returns ^ 2",
        # V2: Bollinger
        "boll_upper(close, 20)",
        "boll_lower(close, 20)",
        "boll_mid(close, 20)",
        "bb_width(close, 20)",
        "where(close > boll_upper(close, 20), 1, 0)",
        "where(close < boll_lower(close, 20) and volume > ts_mean(volume, 20), 1, 0)",
        # LLM 之前被拒的表达式
        "sign(returns) * rank(volume / ts_mean(volume, 20)) * where(returns > 0 and close < ts_mean(close, 20), 1, 0) * (1 + rank(-ts_delta(close, 5) / ts_std(close, 20)))",
        # 组合测试
        "rank(ts_corr(close, volume, 20)) > 0.3 and rank(ts_mean(volume, 5)) > 0.5",
        "ts_zscore(returns, 20) < -2 or ts_zscore(returns, 20) > 2",
        "max(ts_mean(close, 5), boll_mid(close, 20)) / min(ts_mean(close, 20), open)",
    ]
    passed = 0
    total = len(tests)
    for expr in tests:
        err = parser.validate(expr)
        ok = not err
        icon = "✅" if ok else "❌"
        print(f"{icon} {expr[:80]}")
        if err:
            print(f"   ↳ {err}")
        if ok:
            passed += 1
    print(f"\n{passed}/{total} 通过")
