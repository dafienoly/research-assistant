"""表达式解析器 — 将因子表达式编译为可执行计算图

支持算子:
  截面: rank, zscore, scale, winsorize
  时序: ts_mean, ts_std, ts_min, ts_max, ts_rank, ts_sum,
        ts_corr, ts_cov, ts_decay_linear, ts_delta, ts_av_diff
  技术: rsi, macd, atr, bb_width, ema, sma
  非线性: sigmoid, tanh, sign, abs, clip, sign_power
  组合: +, -, *, /, 条件(where)

用法:
  parser = ExpressionParser()
  tree = parser.parse("rank(close / ts_mean(close, 20))")
  result = tree.eval(df)  # 返回 pd.Series
"""

import re
import numpy as np
import pandas as pd
from typing import Any, Optional

# ─── AST 节点类型 ─────────────────────────────────────────

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

class FuncCall(Node):
    def __init__(self, name: str, args: list):
        self.name = name.lower()
        self.args = args
    def eval(self, df):
        return FUNC_REGISTRY[self.name](df, self.args)

# ─── 算子注册表 ─────────────────────────────────────────

FUNC_REGISTRY = {}

def register_op(name: str):
    def wrapper(fn):
        FUNC_REGISTRY[name] = fn
        return fn
    return wrapper

# ═══════════════════════════════════════════════════════
# 截面算子 (cross-sectional) — 按 date 分组
# ═══════════════════════════════════════════════════════

def _cs_apply(df, args, fn):
    """截面算子：按 date 分组应用函数"""
    val = args[0].eval(df)
    return val.groupby(df["date"]).transform(fn)

@register_op("rank")
def op_rank(df, args):
    return _cs_apply(df, args, lambda x: x.rank(pct=True))

@register_op("zscore")
def op_zscore(df, args):
    def _z(x):
        return (x - x.mean()) / x.std().replace(0, np.nan)
    return _cs_apply(df, args, _z)

@register_op("scale")
def op_scale(df, args):
    def _s(x):
        return (x - x.min()) / (x.max() - x.min() + 1e-10)
    return _cs_apply(df, args, _s)

# ═══════════════════════════════════════════════════════
# 时序算子 (time-series) — 按 symbol 分组
# ═══════════════════════════════════════════════════════

def _ts_apply(df, args, fn):
    """时序算子：按 symbol 分组，滚动窗口"""
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
    """x - ts_mean(x, w)"""
    w = _get_window(args)
    return _ts_apply(df, args, lambda x: x - x.rolling(w, min_periods=1).mean())

@register_op("ts_decay_linear")
def op_ts_decay_linear(df, args):
    """线性衰减加权平均"""
    w = _get_window(args)
    def _decay(s):
        if len(s) < w:
            return s.iloc[-1] if len(s) > 0 else 0
        weights = np.arange(1, w + 1)
        return np.dot(s.values[-w:], weights) / weights.sum()
    return _ts_apply(df, args, lambda x: x.rolling(w).apply(_decay, raw=False))

@register_op("ts_corr")
def op_ts_corr(df, args):
    w = _get_window(args) if len(args) > 2 else 20
    a = args[0].eval(df); b = args[1].eval(df)
    return a.groupby(df["symbol"]).transform(lambda x: x.rolling(w).corr(b))

# ═══════════════════════════════════════════════════════
# 技术指标
# ═══════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════
# 非线性/辅助算子
# ═══════════════════════════════════════════════════════

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
    """where(condition, true_val, false_val)"""
    cond = args[0].eval(df).astype(bool)
    t = args[1].eval(df); f = args[2].eval(df)
    return pd.Series(np.where(cond, t, f), index=df.index)

@register_op("sign_power")
def op_sign_power(df, args):
    """sign_power(x, exp=0.5) — 保留符号的幂变换"""
    val = args[0].eval(df)
    exp = float(args[1].eval(df).iloc[0]) if len(args) > 1 else 0.5
    return np.sign(val) * (np.abs(val) ** exp)

@register_op("log")
def op_log(df, args):
    return np.log(args[0].eval(df).replace(0, np.nan).abs().clip(1e-10))

# ═══════════════════════════════════════════════════════
# 分词器 / 解析器
# ═══════════════════════════════════════════════════════

TOKEN_SPEC = [
    ("NUMBER",   r"\d+\.?\d*"),
    ("FIELD",    r"[a-zA-Z_][a-zA-Z0-9_]*"),
    ("LPAREN",   r"\("),
    ("RPAREN",   r"\)"),
    ("COMMA",    r","),
    ("OP",       r"[+\-*/]"),
    ("SKIP",     r"\s+"),
]
TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in TOKEN_SPEC))

class Token:
    def __init__(self, type, value, pos):
        self.type = type; self.value = value; self.pos = pos

def tokenize(s: str) -> list:
    tokens = []
    for m in TOKEN_RE.finditer(s):
        if m.lastgroup == "SKIP":
            continue
        tokens.append(Token(m.lastgroup, m.group(), m.start()))
    return tokens

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
        node = self._expr()
        if self.peek():
            raise SyntaxError(f"表达式结束后多余 token: {self.peek().value}")
        return node

    def _expr(self) -> Node:
        node = self._term()
        while self.peek() and self.peek().type == "OP" and self.peek().value in ("+", "-"):
            op = self.consume().value
            right = self._term()
            node = BinaryOp(op, node, right)
        return node

    def _term(self) -> Node:
        node = self._factor()
        while self.peek() and self.peek().type == "OP" and self.peek().value in ("*", "/"):
            op = self.consume().value
            right = self._factor()
            node = BinaryOp(op, node, right)
        return node

    def _factor(self) -> Node:
        t = self.peek()
        if t is None:
            raise SyntaxError("表达式意外结束")
        # 一元负号
        if t.type == "OP" and t.value == "-":
            self.consume()
            return BinaryOp("*", Number(-1.0), self._factor())
        if t.type == "NUMBER":
            self.consume()
            return Number(float(t.value))
        if t.type == "FIELD":
            self.consume()
            # 检查是否函数调用
            if self.peek() and self.peek().type == "LPAREN":
                name = t.value
                self.consume()
                args = []
                if self.peek() and self.peek().type != "RPAREN":
                    args.append(self._expr())
                    while self.peek() and self.peek().type == "COMMA":
                        self.consume()
                        args.append(self._expr())
                self.consume("RPAREN")
                return FuncCall(name, args)
            return Field(t.value)
        if t.type == "LPAREN":
            self.consume()
            node = self._expr()
            self.consume("RPAREN")
            return node
        raise SyntaxError(f"意外的 token: {t.value} (位置 {t.pos})")

class ExpressionParser:
    """表达式解析器入口"""
    
    OPERATORS = sorted(FUNC_REGISTRY.keys())
    
    def parse(self, expression: str) -> Node:
        tokens = tokenize(expression)
        parser = Parser(tokens)
        return parser.parse()
    
    def eval(self, expression: str, df: pd.DataFrame) -> pd.Series:
        node = self.parse(expression)
        return node.eval(df)
    
    def validate(self, expression: str) -> str:
        """验证表达式是否合法，返回错误信息或空字符串"""
        try:
            self.parse(expression)
            return ""
        except (SyntaxError, ValueError) as e:
            return str(e)

# ═══════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = ExpressionParser()
    tests = [
        "rank(close / ts_mean(close, 20))",
        "rank(ret5) * rank(vol_ratio60)",
        "(close - ts_min(low, 10)) / (ts_max(high, 10) - ts_min(low, 10))",
        "rank(reversal5) * rank(vol_ratio60)",
        "ts_decay_linear(close / vwap, 10)",
        "rank(ts_corr(close, volume, 20))",
        "sigmoid(zscore(close / ts_mean(close, 20)))",
    ]
    for t in tests:
        err = parser.validate(t)
        print(f"{'✅' if not err else '❌'} {t}")
        if err:
            print(f"   {err}")