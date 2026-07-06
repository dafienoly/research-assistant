"""LLM Alpha Discovery V3.7 — LLM 生成 AlphaSpec 候选

LLM 生成 AlphaSpec 候选，不直接写策略配置。
所有候选进入 review queue (默认 disabled)，审批通过后才 register_alpha。

安全边界:
  - auto_apply: False
  - requires_human_approval: True
  - no_live_trade: True
  - paper_config_modified: False
  - live_config_modified: False

用法:
    from factor_lab.alpha.llm_alpha_discovery import (
        LLM_ALPHA_PROMPT_TEMPLATE,
        AlphaSpecValidator,
        CandidateReviewQueue,
        generate_candidate_spec,
        submit_candidate,
        approve_candidate,
        reject_candidate,
    )
"""

import sys, os, json, csv, re, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
CANDIDATES_ROOT = Path("/mnt/d/HermesData/alpha_candidates")
CANDIDATES_INDEX = CANDIDATES_ROOT / "candidates_index.json"

# ─── WSL2/9P 文件系统缓存同步 ────────────────────────────


def _fsync_dir(path: Path):
    """同步目录元数据 (解决 WSL2 9P 协议缓存延迟问题)"""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except OSError:
        pass


def _fsync_file(path: Path):
    """同步文件内容并刷新父目录元数据"""
    try:
        fd = os.open(str(path), os.O_WRONLY)
        os.fsync(fd)
        os.close(fd)
        _fsync_dir(path.parent)
    except OSError:
        pass

# ─── LLM Prompt 模板 ─────────────────────────────────────

LLM_ALPHA_PROMPT_TEMPLATE = """You are a quantitative alpha researcher for A-share market.
Generate {num_candidates} alpha factor candidate(s) based on the following context.

## Context
{context}

## Output Format

Each candidate must be a valid JSON object with these **required** fields:

| Field | Type | Description |
|-------|------|-------------|
| name | string | Short unique factor name (snake_case, e.g. "mom_vol_trend") |
| description | string | One-line description of the factor |
| hypothesis | string | Detailed investment rationale — why this factor should predict returns |
| factor_expression | string | Mathematical expression using available operators and data fields |
| universe | string | Stock universe; default "all_watchlist" |
| data_requirements | array | List of required data field names (e.g. ["close", "volume", "amount"]) |
| signal_direction | string | One of: "long", "short", "long_short" |
| rebalance_frequency | string | One of: "daily", "weekly", "monthly" |
| risk_constraints | object | Dict with max_position_weight (default 0.25) and max_drawdown (default 0.15) |
| risk_notes | string | Potential risks: overfitting, regime dependency, capacity, etc. |
| evidence | string | Supporting evidence: academic paper, empirical observation, financial theory |

## Available Operators
- **Cross-sectional**: rank(x), zscore(x), scale(x), winsorize(x)
- **Time-series**: ts_mean(x, w), ts_std(x, w), ts_min(x, w), ts_max(x, w), ts_rank(x, w),
  ts_sum(x, w), ts_corr(x, y, w), ts_cov(x, y, w), ts_decay_linear(x, w),
  ts_delta(x, w), ts_av_diff(x, w)
- **Technical**: ema(x, w), sma(x, w), rsi(x, w), macd(x), atr(x), bb_width(x)
- **Non-linear**: sigmoid(x), tanh(x), sign(x), abs(x), clip(x, lo, hi), sign_power(x, p)
- **Logical**: where(cond, true_val, false_val)
- **Arithmetic**: +, -, *, /

Window parameter w is always a positive integer (number of trading days).

## Available Data Fields
close, open, high, low, volume, amount, returns, vwap

## CRITICAL RULES (violations will be rejected)
1. Output ONLY valid JSON wrapped in ```json ... ``` blocks — no extra commentary outside.
2. NEVER use negative window parameters (e.g., ts_delta(close, -1)).
3. NEVER use zero or one-day windows that cause look-ahead (e.g., ts_mean(close, 1)).
4. The factor_expression MUST be evaluatable by a parser that supports operators listed above.
5. Each name must be unique within this response.
6. Do NOT include any strategy config, paper config, or live trading parameters.
7. Output nothing outside the JSON code block.
"""


# ─── AlphaSpec Validator ─────────────────────────────────

REQUIRED_FIELDS = [
    "name", "description", "hypothesis", "factor_expression",
    "signal_direction", "universe", "data_requirements",
    "risk_notes", "evidence",
]

VALID_SIGNAL_DIRECTIONS = {"long", "short", "long_short"}
VALID_REBALANCE_FREQUENCIES = {"daily", "weekly", "monthly"}

# 禁止的 Window 参数 — 小于该值视为未来函数/过拟合
MIN_WINDOW = 2


class AlphaSpecValidator:
    """AlphaSpec 候选验证器

    验证维度:
      1. 字段完整性 — 必须包含所有 required 字段
      2. 字段类型/值合法性 — signal_direction, rebalance_frequency 等
      3. 不可计算 — factor_expression 能否被 ExpressionParser 解析
      4. 未来函数 — window 参数是否为负/零/1
      5. 字段长度/格式范围校验
    """

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self, candidate: dict) -> bool:
        """执行全部验证，返回 True=通过 False=不通过"""
        self.errors = []
        self.warnings = []
        self._check_required_fields(candidate)
        if self.errors:
            return False
        self._check_signal_direction(candidate)
        self._check_rebalance_frequency(candidate)
        self._check_field_lengths(candidate)
        self._check_data_requirements(candidate)
        self._check_expression_computable(candidate.get("factor_expression", ""))
        self._check_future_function(candidate.get("factor_expression", ""))
        return len(self.errors) == 0

    def _check_required_fields(self, candidate: dict):
        for field in REQUIRED_FIELDS:
            val = candidate.get(field)
            if val is None or (isinstance(val, str) and not val.strip()):
                self.errors.append(f"缺少必需字段: {field}")

    def _check_signal_direction(self, candidate: dict):
        val = candidate.get("signal_direction", "")
        if val and val not in VALID_SIGNAL_DIRECTIONS:
            self.errors.append(
                f"signal_direction 非法值 '{val}'; 允许: {', '.join(sorted(VALID_SIGNAL_DIRECTIONS))}"
            )

    def _check_rebalance_frequency(self, candidate: dict):
        val = candidate.get("rebalance_frequency", "")
        if val and val not in VALID_REBALANCE_FREQUENCIES:
            self.errors.append(
                f"rebalance_frequency 非法值 '{val}'; 允许: {', '.join(sorted(VALID_REBALANCE_FREQUENCIES))}"
            )

    def _check_field_lengths(self, candidate: dict):
        """字段长度合理性检查"""
        name = candidate.get("name", "")
        if len(name) > 60:
            self.errors.append(f"name 过长 ({len(name)} 字符), 最大 60")
        desc = candidate.get("description", "")
        if len(desc) > 500:
            self.warnings.append(f"description 偏长 ({len(desc)} 字符)")
        hypothesis = candidate.get("hypothesis", "")
        if len(hypothesis) > 2000:
            self.warnings.append(f"hypothesis 偏长 ({len(hypothesis)} 字符)")
        expr = candidate.get("factor_expression", "")
        if len(expr) > 500:
            self.errors.append(f"factor_expression 过长 ({len(expr)} 字符), 最大 500")

    def _check_data_requirements(self, candidate: dict):
        """data_requirements 必须是字符串列表"""
        dr = candidate.get("data_requirements", [])
        if not isinstance(dr, list):
            self.errors.append("data_requirements 必须是列表")
            return
        if not dr:
            self.warnings.append("data_requirements 为空列表")
            return
        for item in dr:
            if not isinstance(item, str) or not item.strip():
                self.errors.append(f"data_requirements 包含非法元素: {item}")

    def _check_expression_computable(self, expression: str):
        """验证表达式能否被 ExpressionParser 解析"""
        if not expression:
            self.errors.append("factor_expression 为空")
            return
        try:
            from factor_lab.expression_parser import ExpressionParser
            parser = ExpressionParser()
            err = parser.validate(expression)
            if err:
                self.errors.append(f"factor_expression 不可计算: {err}")
        except ImportError:
            self.warnings.append("ExpressionParser 不可用, 跳过可计算性检查")
        except Exception as e:
            self.errors.append(f"factor_expression 解析异常: {e}")

    def _check_future_function(self, expression: str):
        """检测未来函数: 负 window、零 window、window=1"""
        if not expression:
            return
        # 检查负 window 参数: ts_mean(x, -5) 等
        neg_windows = re.findall(r'(ts_mean|ts_std|ts_min|ts_max|ts_rank|ts_sum|'
                                 r'ts_corr|ts_cov|ts_decay_linear|ts_delta|ts_av_diff|'
                                 r'ema|sma|rsi)\(\s*\w+\s*,\s*(-?\d+)', expression)
        for op_name, win_val in neg_windows:
            win = int(win_val)
            if win < MIN_WINDOW:
                self.errors.append(
                    f"未来函数: {op_name} 使用 window={win} (最小允许: {MIN_WINDOW})"
                )
        # 检查 ts_delta(x, 0) — 无意义
        zero_deltas = re.findall(r'ts_delta\(\s*\w+\s*,\s*0\s*\)', expression)
        if zero_deltas:
            for match in zero_deltas:
                self.errors.append(f"未来函数/无意义: {match}")

    def get_report(self) -> dict:
        """返回验证报告"""
        return {
            "passed": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ─── 重复检测 ─────────────────────────────────────────────

def check_duplicate_in_registry(candidate: dict) -> dict:
    """检查候选是否与已注册 Alpha 重复

    检查维度:
      - name 精确匹配
      - factor_expression 精确匹配

    返回: {"is_duplicate": bool, "matched_alpha_ids": list}
    """
    from factor_lab.alpha.registry import list_alpha
    alphas = list_alpha()
    name = candidate.get("name", "").strip()
    expr = candidate.get("factor_expression", "").strip()
    matched = []
    for a in alphas:
        aid = a.get("alpha_id", "")
        if a.get("name", "").strip() == name:
            matched.append({"alpha_id": aid, "field": "name", "value": name})
            continue
        # 尝试读取完整 spec 比较表达式
        try:
            from factor_lab.alpha.registry import get_alpha
            spec = get_alpha(aid)
            if spec and spec.get("factor_expression", "").strip() == expr:
                matched.append({"alpha_id": aid, "field": "factor_expression", "value": expr[:60]})
        except Exception:
            pass
    return {"is_duplicate": len(matched) > 0, "matched_alpha_ids": matched}


def check_duplicate_in_queue(candidate: dict) -> dict:
    """检查候选是否与 review queue 中已有候选重复"""
    index = _load_candidates_index()
    name = candidate.get("name", "").strip()
    expr = candidate.get("factor_expression", "").strip()
    matched = []
    for entry in index:
        if entry.get("name", "").strip() == name:
            matched.append({
                "candidate_id": entry.get("candidate_id", ""),
                "status": entry.get("status", ""),
                "field": "name",
                "value": name,
            })
            continue
        # 读取完整候比较表达式
        cid = entry.get("candidate_id", "")
        candidate_dir = CANDIDATES_ROOT / cid
        spec_path = candidate_dir / "candidate.json"
        if spec_path.exists():
            try:
                data = json.loads(spec_path.read_text())
                spec_data = data.get("spec", {})
                if spec_data.get("factor_expression", "").strip() == expr:
                    matched.append({
                        "candidate_id": cid,
                        "status": entry.get("status", ""),
                        "field": "factor_expression",
                        "value": expr[:60],
                    })
            except Exception:
                pass
    return {"is_duplicate": len(matched) > 0, "matched_candidates": matched}


# ─── Candidate Review Queue ──────────────────────────────

CANDIDATE_STATUSES = ["pending_review", "approved", "rejected", "promoted"]


def _ensure_candidates_root():
    CANDIDATES_ROOT.mkdir(parents=True, exist_ok=True)
    _fsync_dir(CANDIDATES_ROOT)


def _load_candidates_index():
    _ensure_candidates_root()
    if CANDIDATES_INDEX.exists():
        return json.loads(CANDIDATES_INDEX.read_text())
    return []


def _save_candidates_index(index):
    CANDIDATES_INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    _fsync_file(CANDIDATES_INDEX)


def submit_candidate(candidate: dict, source: str = "llm") -> dict:
    """提交 AlphaSpec 候选到 review queue

    1. 验证 (字段完整性/可计算性/未来函数)
    2. 查重 (仅警告，不阻止入库)
    3. 写入候选目录
    4. 更新 index

    参数:
        candidate: AlphaSpec 候选 dict
        source: 来源 ("llm", "manual")

    返回: dict 包含 candidate_id, status, validation, duplicate_check
    """
    # 验证
    validator = AlphaSpecValidator()
    validation_passed = validator.validate(candidate)

    # 查重 (仅验证通过后执行；重复只记录警告不拒绝)
    duplicate_info = {"registry": {"is_duplicate": False}, "queue": {"is_duplicate": False}}
    if validation_passed:
        duplicate_info["registry"] = check_duplicate_in_registry(candidate)
        duplicate_info["queue"] = check_duplicate_in_queue(candidate)

    is_duplicate = (
        duplicate_info["registry"]["is_duplicate"]
        or duplicate_info["queue"]["is_duplicate"]
    )

    # 拒绝原因: 仅验证失败导致拒绝，重复仅警告
    rejected_reasons = []
    if not validation_passed:
        rejected_reasons.extend(validator.errors)
    if is_duplicate:
        validator.warnings.append("与现有 Alpha/候选重复 — 请确认是否需要重复注册")

    # 状态决定: 验证通过则进入审核队列 (哪怕有重复警告)
    candidate_status = "pending_review" if validation_passed else "rejected"

    # 写入候选目录
    _ensure_candidates_root()
    cid = f"cand_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
    candidate_dir = CANDIDATES_ROOT / cid
    candidate_dir.mkdir(parents=True, exist_ok=True)
    _fsync_dir(CANDIDATES_ROOT)

    # 组装候选记录
    now_iso = datetime.now(CST).isoformat()
    record = {
        "candidate_id": cid,
        "source": source,
        "status": candidate_status,
        "submitted_at": now_iso,
        "updated_at": now_iso,
        "validation_passed": validation_passed,
        "validation_errors": validator.errors,
        "validation_warnings": validator.warnings,
        "duplicate_info": duplicate_info,
        "rejected_reasons": rejected_reasons,
        "spec": {
            "name": candidate.get("name", ""),
            "description": candidate.get("description", ""),
            "hypothesis": candidate.get("hypothesis", ""),
            "factor_expression": candidate.get("factor_expression", ""),
            "universe": candidate.get("universe", "all_watchlist"),
            "data_requirements": candidate.get("data_requirements", []),
            "signal_direction": candidate.get("signal_direction", "long"),
            "rebalance_frequency": candidate.get("rebalance_frequency", "monthly"),
            "risk_constraints": candidate.get("risk_constraints", {
                "max_position_weight": 0.25, "max_drawdown": 0.15,
            }),
            "risk_notes": candidate.get("risk_notes", ""),
            "evidence": candidate.get("evidence", ""),
            "created_at": now_iso,
            "source": source,
            "enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
        },
    }

    (candidate_dir / "candidate.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )
    _fsync_dir(candidate_dir)

    # 更新 index
    index = _load_candidates_index()
    index.append({
        "candidate_id": cid,
        "name": candidate.get("name", ""),
        "status": record["status"],
        "source": source,
        "submitted_at": now_iso,
        "validation_passed": validation_passed,
    })
    _save_candidates_index(index)

    result = {
        "candidate_id": cid,
        "status": record["status"],
        "validation": {"passed": validation_passed, "errors": validator.errors, "warnings": validator.warnings},
        "duplicate_check": duplicate_info,
        "rejected": not validation_passed,  # 仅验证失败算拒绝，重复不拒绝
        "rejected_reasons": rejected_reasons,
    }

    # 同时写入 LLM Alpha Discovery 报告目录
    _write_submission_report(candidate, result)

    return result


def _write_submission_report(candidate: dict, result: dict):
    """每次提交写入一份审计报告到 HermesReports"""
    sid = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = BASE / "llm_alpha_discovery" / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "run_id": sid,
        "version": "V3.7",
        "source": "llm_alpha_discovery",
        "submitted_at": datetime.now(CST).isoformat(),
        "candidate": {
            "name": candidate.get("name", ""),
            "description": candidate.get("description", ""),
            "hypothesis": candidate.get("hypothesis", "")[:200],
            "factor_expression": candidate.get("factor_expression", ""),
        },
        "result": result,
        "safety": {
            "auto_apply": False,
            "no_live_trade": True,
            "all_disabled": True,
            "no_broker": True,
            "no_paper_config_modified": True,
            "no_live_config_modified": True,
        },
    }
    (out_dir / "submission_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )

    # 简短摘要
    status_icon = "✅" if result["validation"]["passed"] else "❌"
    status_text = "Accepted (pending review)" if result["validation"]["passed"] else "Rejected"
    dup_warn = " (with duplicate warning)" if (result.get("duplicate_check", {}).get("registry", {}).get("is_duplicate") or result.get("duplicate_check", {}).get("queue", {}).get("is_duplicate")) else ""
    summary = f"""# LLM Alpha Discovery — Submission Report

Run: {sid}
Status: {status_icon} {status_text}{dup_warn}
Candidate: {candidate.get('name', '?')}

## Validation
- Passed: {result['validation']['passed']}
- Errors: {json.dumps(result['validation']['errors'], ensure_ascii=False)}
- Warnings: {json.dumps(result['validation']['warnings'], ensure_ascii=False)}

## Duplicate Check
- Registry duplicate: {result['duplicate_check']['registry']['is_duplicate']}
- Queue duplicate: {result['duplicate_check']['queue']['is_duplicate']}

## Safety
- auto_apply=False ✅
- no_live_trade=True ✅
- all_disabled=True ✅
- No broker/miniqmt ✅
- No paper/live config modified ✅
"""
    (out_dir / "submission_summary.md").write_text(summary)

    # 追加到总体报告
    _append_to_master_log(result)

    print(f"\n{'='*60}")
    print(f"  🤖 LLM Alpha Discovery V3.7")
    print(f"  Candidate: {candidate.get('name', '?')}")
    if not result.get('validation', {}).get('passed', False):
        print(f"  Status: ❌ Rejected (validation failed)")
        for reason in result.get('rejected_reasons', []):
            print(f"    - {reason}")
    else:
        is_dup = (result.get('duplicate_check', {}).get('registry', {}).get('is_duplicate', False)
                  or result.get('duplicate_check', {}).get('queue', {}).get('is_duplicate', False))
        dup_label = " ⚠️  (duplicate warning)" if is_dup else ""
        print(f"  Status: ✅ Accepted (pending review){dup_label}")
    if result.get('validation', {}).get('warnings', []):
        for w in result['validation']['warnings']:
            print(f"    ⚠️  {w}")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")


def _append_to_master_log(result: dict):
    """追加到 master log"""
    log_dir = BASE / "llm_alpha_discovery"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "llm_alpha_discovery_log.jsonl"
    entry = {
        "timestamp": datetime.now(CST).isoformat(),
        "candidate_id": result.get("candidate_id", ""),
        "name": result.get("candidate_id", ""),
        "status": result.get("status", ""),
        "validation_passed": result.get("validation", {}).get("passed", False),
        "warnings": result.get("validation", {}).get("warnings", []),
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def approve_candidate(candidate_id: str) -> dict:
    """审批通过候选，注册到 Alpha Registry

    流程:
      1. 标记候选为 approved
      2. 调用 registry.register_alpha() 注册
      3. 生成的 Alpha 默认 disabled

    返回:
        dict: 注册结果
    """
    candidate_dir = CANDIDATES_ROOT / candidate_id
    cand_path = candidate_dir / "candidate.json"
    if not cand_path.exists():
        return {"error": f"Candidate {candidate_id} not found"}

    record = json.loads(cand_path.read_text())
    if record["status"] != "pending_review":
        return {"error": f"Candidate status is '{record['status']}', expected 'pending_review'"}

    spec_dict = record["spec"]

    # 注册到 Alpha Registry
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.alpha.registry import register_alpha

    spec = AlphaSpec(
        name=spec_dict["name"],
        description=spec_dict.get("description", ""),
        hypothesis=spec_dict.get("hypothesis", ""),
        universe=spec_dict.get("universe", "all_watchlist"),
        data_requirements=spec_dict.get("data_requirements", ["close", "volume", "amount"]),
        factor_expression=spec_dict.get("factor_expression", ""),
        signal_direction=spec_dict.get("signal_direction", "long"),
        rebalance_frequency=spec_dict.get("rebalance_frequency", "monthly"),
        risk_constraints=spec_dict.get("risk_constraints", {"max_position_weight": 0.25, "max_drawdown": 0.15}),
        author="llm_alpha_researcher",
        source=f"llm_alpha_discovery:{candidate_id}",
        version="0.0.1",
        status="registered",
        enabled=False,
        paper_enabled=False,
        live_enabled=False,
        tags=["llm_discovered", "v3.7", "no_live_trade"],
    )
    result = register_alpha(spec)

    # 更新候选记录
    record["status"] = "approved"
    record["updated_at"] = datetime.now(CST).isoformat()
    record["alpha_id"] = result.get("alpha_id", "")
    record["alpha_dir"] = result.get("alpha_dir", "")
    cand_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    # 更新 index
    index = _load_candidates_index()
    for i, entry in enumerate(index):
        if entry["candidate_id"] == candidate_id:
            index[i]["status"] = "approved"
            index[i]["alpha_id"] = result.get("alpha_id", "")
    _save_candidates_index(index)

    return {
        "candidate_id": candidate_id,
        "status": "approved",
        "alpha_id": result.get("alpha_id", ""),
        "alpha_dir": result.get("alpha_dir", ""),
        "safety": {"enabled": False, "paper_enabled": False, "live_enabled": False},
    }


def reject_candidate(candidate_id: str, reason: str = "") -> dict:
    """拒绝候选，记录原因"""
    candidate_dir = CANDIDATES_ROOT / candidate_id
    cand_path = candidate_dir / "candidate.json"
    if not cand_path.exists():
        return {"error": f"Candidate {candidate_id} not found"}

    record = json.loads(cand_path.read_text())
    if record["status"] != "pending_review":
        return {"error": f"Candidate status is '{record['status']}', expected 'pending_review'"}

    record["status"] = "rejected"
    record["updated_at"] = datetime.now(CST).isoformat()
    record["rejected_reasons"] = record.get("rejected_reasons", [])
    if reason:
        record["rejected_reasons"].append(reason)

    cand_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    # 更新 index
    index = _load_candidates_index()
    for i, entry in enumerate(index):
        if entry["candidate_id"] == candidate_id:
            index[i]["status"] = "rejected"
    _save_candidates_index(index)

    return {
        "candidate_id": candidate_id,
        "status": "rejected",
        "reasons": record["rejected_reasons"],
    }


def update_candidate_status(candidate_id: str, new_status: str) -> dict:
    """更新候选状态

    参数:
        candidate_id: 候选 ID
        new_status: 新状态 (promoted, approved, rejected, pending_review)

    返回:
        更新结果 dict
    """
    candidate_dir = CANDIDATES_ROOT / candidate_id
    cand_path = candidate_dir / "candidate.json"
    if not cand_path.exists():
        return {"error": f"Candidate {candidate_id} not found"}

    record = json.loads(cand_path.read_text())
    old_status = record["status"]
    record["status"] = new_status
    record["updated_at"] = datetime.now(CST).isoformat()

    cand_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    # 更新 index
    index = _load_candidates_index()
    for i, entry in enumerate(index):
        if entry["candidate_id"] == candidate_id:
            index[i]["status"] = new_status
    _save_candidates_index(index)

    return {
        "candidate_id": candidate_id,
        "old_status": old_status,
        "new_status": new_status,
        "success": True,
    }


def list_candidates(status: str = "") -> list:
    """列出 review queue 中的候选

    参数:
        status: 过滤状态，空=全部
    """
    index = _load_candidates_index()
    if status:
        return [c for c in index if c.get("status") == status]
    return index


def get_candidate(candidate_id: str) -> dict:
    """获取候选详情"""
    candidate_dir = CANDIDATES_ROOT / candidate_id
    cand_path = candidate_dir / "candidate.json"
    if not cand_path.exists():
        return {"error": f"Candidate {candidate_id} not found"}
    return json.loads(cand_path.read_text())


def generate_rejected_reason_report() -> dict:
    """生成被拒绝候选的原因报告"""
    index = _load_candidates_index()
    rejected = [c for c in index if c.get("status") == "rejected"]
    details = []
    for entry in rejected:
        cid = entry.get("candidate_id", "")
        record = get_candidate(cid)
        if "error" not in record:
            details.append({
                "candidate_id": cid,
                "name": record.get("spec", {}).get("name", ""),
                "rejected_reasons": record.get("rejected_reasons", []),
                "validation_errors": record.get("validation_errors", []),
                "submitted_at": record.get("submitted_at", ""),
            })

    # 统计
    reason_counts = {}
    for d in details:
        for r in d.get("rejected_reasons", []):
            reason_counts[r] = reason_counts.get(r, 0) + 1

    # 写入报告
    sid = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    out_dir = BASE / "llm_alpha_discovery" / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "run_id": sid,
        "report_type": "rejected_reason_report",
        "total_candidates": len(index),
        "total_rejected": len(rejected),
        "reason_counts": reason_counts,
        "rejected_details": details,
    }
    (out_dir / "rejected_reason_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )

    return report


# ─── LLM 生成 + 提交管线 ──────────────────────────────────

def generate_candidate_spec(prompt_context: str, num_candidates: int = 3) -> list:
    """通过 LLM 生成 AlphaSpec 候选，并提交到 review queue

    步骤:
      1. 构造 prompt
      2. 调用 LLM
      3. 解析 JSON 响应
      4. 逐个提交到 review queue

    参数:
        prompt_context: 上下文描述 (当前因子、市场环境等)
        num_candidates: 希望生成的候选数

    返回:
        list[dict]: 每个候选的提交结果
    """
    prompt = LLM_ALPHA_PROMPT_TEMPLATE.format(
        context=prompt_context,
        num_candidates=num_candidates,
    )

    # 调用 LLM
    response = _call_llm(prompt)

    # 解析 JSON
    candidates = _parse_llm_response(response)

    # 逐个提交
    results = []
    for cand in candidates:
        result = submit_candidate(cand, source="llm")
        results.append(result)

    return results


def _call_llm(prompt: str, temperature: float = 0.3) -> str:
    """调用 LLM 后端 (通过 Hermes CLI)"""
    import subprocess
    try:
        result = subprocess.run(
            ["hermes", "-z", prompt],
            capture_output=True, text=True, timeout=120,
        )
        out = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if not out:
            return f"ERROR: 空响应. stderr={stderr[:200]}"
        return out
    except Exception as e:
        return f"ERROR: {e}"


def _parse_llm_response(response: str) -> list:
    """从 LLM 响应中提取 JSON AlphaSpec 列表"""
    if response.startswith("ERROR:"):
        return []

    # 提取 ```json ... ``` 块
    candidates = []
    blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)```', response)
    for block in blocks:
        block = block.strip()
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            # 尝试按行解析为多个 JSON 对象
            continue

        if isinstance(data, list):
            candidates.extend(data)
        elif isinstance(data, dict):
            candidates.append(data)

    return candidates


# ─── CLI 集成函数 ─────────────────────────────────────────

def cmd_discover(prompt_context: str = "", num_candidates: int = 3) -> dict:
    """CLI 入口: alpha:llm-discover

    如果没有提供 prompt_context，使用默认上下文
    """
    if not prompt_context:
        # 从现有因子列表中构建默认上下文
        try:
            from factor_lab.factor_base import list_factors
            factors = list_factors()
            categories = {}
            for f in factors:
                cat = f.get("category", "unknown")
                categories.setdefault(cat, []).append(f["name"])
            default_context_parts = ["Current factor catalog:"]
            for cat, names in sorted(categories.items()):
                default_context_parts.append(f"  {cat} ({len(names)} factors): {', '.join(names[:10])}")
            prompt_context = "\n".join(default_context_parts)
        except Exception:
            prompt_context = "Generate alpha factors for A-share market using standard data fields."

    return {"candidates_generated": 0, "results": generate_candidate_spec(prompt_context, num_candidates)}


def cmd_list_candidates(status: str = "") -> None:
    """CLI 入口: alpha:llm-candidates"""
    candidates = list_candidates(status)
    if not candidates:
        print("  (empty)")
        return
    for c in candidates:
        status_tag = "🟡" if c.get("status") == "pending_review" else "🟢" if c.get("status") == "approved" else "🔴"
        print(f"  {status_tag} {c['candidate_id'][:35]:35s} {c.get('name','?'):25s} {c['status']:20s}")


def cmd_approve(candidate_id: str) -> None:
    """CLI 入口: alpha:llm-approve"""
    result = approve_candidate(candidate_id)
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        print(f"✅ Approved → Alpha ID: {result['alpha_id']} (disabled by default)")


def cmd_reject(candidate_id: str, reason: str = "") -> None:
    """CLI 入口: alpha:llm-reject"""
    result = reject_candidate(candidate_id, reason)
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        print(f"❌ Rejected: {candidate_id}")


def cmd_rejected_report() -> None:
    """CLI 入口: alpha:llm-rejected-report"""
    report = generate_rejected_reason_report()
    print(f"\n{'='*60}")
    print(f"  📊 Rejected Candidate Report")
    print(f"  Total candidates: {report['total_candidates']}")
    print(f"  Rejected: {report['total_rejected']}")
    print(f"  Reason breakdown:")
    for reason, count in sorted(report.get("reason_counts", {}).items(), key=lambda x: -x[1]):
        print(f"    - {reason}: {count}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM Alpha Discovery V3.7")
    sub = parser.add_subparsers(dest="command")

    sp = sub.add_parser("discover")
    sp.add_argument("--context", default="", help="Prompt context")
    sp.add_argument("--num", type=int, default=3, help="Number of candidates to generate")

    sp = sub.add_parser("list")
    sp.add_argument("--status", default="", help="Filter by status (pending_review/approved/rejected)")

    sp = sub.add_parser("approve")
    sp.add_argument("--candidate-id", required=True)

    sp = sub.add_parser("reject")
    sp.add_argument("--candidate-id", required=True)
    sp.add_argument("--reason", default="")

    sp = sub.add_parser("rejected-report")

    sub.add_parser("validate")
    sp.add_argument("--spec", required=True, help="AlphaSpec JSON file path to validate")

    args = parser.parse_args()

    if args.command == "discover":
        result = cmd_discover(args.context, args.num)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "list":
        cmd_list_candidates(args.status)
    elif args.command == "approve":
        cmd_approve(args.candidate_id)
    elif args.command == "reject":
        cmd_reject(args.candidate_id, args.reason)
    elif args.command == "rejected-report":
        cmd_rejected_report()
    elif args.command == "validate":
        with open(args.spec) as f:
            spec = json.load(f)
        validator = AlphaSpecValidator()
        ok = validator.validate(spec)
        report = validator.get_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        parser.print_help()
