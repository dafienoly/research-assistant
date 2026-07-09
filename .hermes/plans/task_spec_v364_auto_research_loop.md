# V3.6.4 全自动因子研究闭环 — 子代理 Spec

## 依赖：V3.6.2 (prompt增强) + V3.6.3 (LLM诊断) 建议先完成
## 依赖：V3.1.1 (真实benchmark) ✅
## 依赖：V3.2.1 (因子正交化) ✅
## 依赖：V3.3.1 (因子加权组合) ✅
## 依赖：V3.1.2 (因子验证管线) ✅

## 背景

所有组件已就位，就差一个**自动循环**把它们串起来：

```
LLM生成因子 → 批量回测 → IC分析 → 同池等权对比
    → WalkForward → LLM诊断 → 失败归因
    → 收敛判断 → (继续/停止)
```

## 目标

实现全自动因子研究循环：定时运行、自动生成 N 个候选、评估、分析、决定是否继续、注册最优因子。

## 修改文件

### 新建或修改: commands/factor_lab/research_loop.py

在现有 ResearchLoop 类基础上增强：

```python
"""V3.6.4 全自动因子研究闭环

循环流程:
  Phase 0: Context Loading — 加载知识库 + 失败记录 + 现有因子状态
  Phase 1: Factor Design — LLM 生成 3-5 个候选因子（含失败模式参考）
  Phase 2: Batch Backtest — 使用 V3.1.2 验证管线并行评估
  Phase 3: LLM Diagnosis — 调用 V3.6.3 诊断每个候选
  Phase 4: Failure Recording — 淘汰因子写入 V3.6.1 FailureDatabase
  Phase 5: Convergence Check — 连续 N 轮无改善则停止
  Phase 6: Report — 输出本轮结果 + 注册最优因子

配置:
  max_rounds: 10
  candidates_per_round: 3
  convergence_window: 3  # 连续 3 轮无改善即收敛
  min_ic_threshold: 0.02  # 最低 IC 要求
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json, sys

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")

class AutoResearchLoop:
    """V3.6.4 全自动因子研究闭环"""
    
    def __init__(self, config: dict = None):
        self.config = {
            "max_rounds": 10,
            "candidates_per_round": 3,
            "convergence_window": 3,
            "convergence_threshold": 0.01,
            "min_ic_threshold": 0.02,
            "output_dir": str(BASE / "auto_research"),
            ** (config or {}),
        }
        self.round = 0
        self.history = []  # 每轮结果
        self.best_score = 0.0
        self.no_improvement_rounds = 0
        self.output_dir = Path(self.config["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def run(self, market_context: str = "") -> dict:
        """执行完整的研究循环"""
        start_time = datetime.now(CST)
        print(f"🚀 自动研究循环启动 — 最多 {self.config['max_rounds']} 轮")
        
        while self.round < self.config["max_rounds"]:
            self.round += 1
            print(f"\n{'='*50}")
            print(f"🔬 第 {self.round}/{self.config['max_rounds']} 轮")
            
            # Phase 1: 生成候选因子
            candidates = self._phase1_generate(market_context)
            
            # Phase 2: 批量回测
            results = self._phase2_backtest(candidates)
            
            # Phase 3: LLM 诊断
            diagnoses = self._phase3_diagnose(results)
            
            # Phase 4: 记录失败
            self._phase4_record_failures(diagnoses)
            
            # Phase 5: 收敛判断
            best = self._phase5_convergence(results)
            
            # Phase 6: 报告
            self._phase6_report(results, diagnoses)
            
            if self.no_improvement_rounds >= self.config["convergence_window"]:
                print(f"\n✅ 收敛: 连续 {self.no_improvement_rounds} 轮无改善")
                break
        
        return {
            "status": "completed",
            "rounds": self.round,
            "stop_reason": f"连续 {self.no_improvement_rounds} 轮无改善" if self.no_improvement_rounds >= self.config["convergence_window"] else "达到最大轮次",
            "best_score": self.best_score,
            "total_candidates": sum(r.get("n_candidates", 0) for r in self.history),
            "registered": [r.get("best_factor") for r in self.history if r.get("best_factor")],
            "duration_seconds": (datetime.now(CST) - start_time).total_seconds(),
        }
    
    def _phase1_generate(self, market_context: str) -> list:
        """生成候选因子"""
        from factor_lab.alpha.llm_alpha_discovery import generate_candidate_spec
        return generate_candidate_spec(
            prompt_context=market_context or "A股量化因子研究",
            num_candidates=self.config["candidates_per_round"],
        )
    
    def _phase2_backtest(self, candidates: list) -> list:
        """批量回测评估"""
        # TODO: 使用 V3.1.2 validate_factor 管线
        return []
    
    def _phase3_diagnose(self, results: list) -> list:
        """LLM 诊断"""
        return []
    
    def _phase4_record_failures(self, diagnoses: list):
        """淘汰因子写入 FailureDatabase"""
        from factor_lab.alpha.failure_db import FailureDatabase, FailureRecord
        
        db = FailureDatabase()
        for d in diagnoses:
            if d.get("verdict") in ("watch", "retire"):
                record = FailureRecord(
                    factor_name=d.get("factor_name", "unknown"),
                    rejection_reason=d.get("failure_risks", {}).get("ic_decay", "unknown"),
                    created_by="auto_research",
                )
                db.record_failure(record)
    
    def _phase5_convergence(self, results: list) -> float:
        """检查收敛"""
        if not results:
            return 0.0
        
        best = max(results, key=lambda r: r.get("score", {}).get("overall_score", 0))
        score = best.get("score", {}).get("overall_score", 0)
        
        if score > self.best_score + self.config["convergence_threshold"]:
            self.best_score = score
            self.no_improvement_rounds = 0
        else:
            self.no_improvement_rounds += 1
        
        return score
    
    def _phase6_report(self, results: list, diagnoses: list):
        """输出本轮结果"""
        round_report = {
            "round": self.round,
            "n_candidates": len(results),
            "best_score": self.best_score,
            "no_improvement_rounds": self.no_improvement_rounds,
            "results": results,
            "diagnoses": diagnoses,
        }
        self.history.append(round_report)
        
        # 持久化
        round_dir = self.output_dir / f"round_{self.round:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        with open(round_dir / "report.json", "w") as f:
            json.dump(round_report, f, indent=2, ensure_ascii=False, default=str)
        
        # 输出摘要
        print(f"  候选: {len(results)} 个")
        for r in results:
            s = r.get("score", {})
            print(f"    {r.get('factor_name', '?')}: Grade={s.get('grade', '?')} Score={s.get('overall_score', 0):.1f}")
```

### 验证

```python
from factor_lab.research_loop import AutoResearchLoop

# 测试初始化
loop = AutoResearchLoop(config={"max_rounds": 3, "candidates_per_round": 2})
assert loop.config["max_rounds"] == 3
assert loop.round == 0
print("✅ 自动研究循环初始化完成")

# 测试收敛判断
loop.best_score = 80.0
loop._phase5_convergence([
    {"factor_name": "test", "score": {"overall_score": 80.5, "grade": "A"}}
])
assert loop.best_score == 80.5, "80.5 > 80.0 + 0.01 应更新 best_score"
assert loop.no_improvement_rounds == 0, "有改善应重置计数"

loop._phase5_convergence([
    {"factor_name": "test", "score": {"overall_score": 80.1, "grade": "A"}}
])
assert loop.no_improvement_rounds == 1, "80.1 < 80.5 + 0.01 不应更新"

print(f"✅ 收敛判断正确: best={loop.best_score}, no_improvement={loop.no_improvement_rounds}")

# 测试持久化
loop._phase6_report(
    [{"factor_name": "test_mom", "score": {"overall_score": 85, "grade": "A"}}],
    [{"factor_name": "test_mom", "verdict": "promote"}],
)
round_dir = loop.output_dir / "round_01"
assert round_dir.exists()
assert (round_dir / "report.json").exists()
print(f"✅ 报告持久化: {round_dir}")

# 清理
import shutil
shutil.rmtree(loop.output_dir, ignore_errors=True)

print("\n🎉 V3.6.4 全自动研究闭环验证通过")
```

## 注意事项
1. 循环有 `max_rounds` 天花板，防止无限执行
2. 收敛检测：连续 N 轮最优分数无显著改善
3. 每轮结果持久化到 `/mnt/d/HermesReports/auto_research/`
4. 注册最优因子到 Alpha Registry
5. 淘汰因子写入 FailureDatabase
