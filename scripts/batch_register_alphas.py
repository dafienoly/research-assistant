"""批量注册并回填 20 个已验证因子到 Alpha Registry"""
import sys, json, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "commands"))

from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.registry import register_alpha, AlphaRegistry

# 1. 注册 20 个因子
with open("research_outputs/factor_validation/validation_leaderboard.csv") as f:
    rows = list(csv.DictReader(f))

count = 0
for r in rows:
    name = r["factor"]
    grade = r["overall_grade"]
    ic_mean = float(r["ic_mean"])
    
    alpha = AlphaSpec(
        name=name,
        description=f"{name} - IC={ic_mean:.4f} Grade={grade} V3.1.2",
        source="systematic_validation",
        version="1.0.0",
        tags=["validated", grade.lower(), "v3.1.2"],
    )
    result = register_alpha(alpha)
    if result.get("success"):
        count += 1

print(f"[1] Registered {count}/{len(rows)} Alpha entries")

# 2. 批量回填验证数据
reg = AlphaRegistry()
results = reg.batch_update_from_validation_dir("research_outputs/factor_validation")
updated = sum(1 for r in results if r.get("updated"))
print(f"[2] Batch updated: {updated}/{len(results)}")

# 3. 验证
index = reg.load_index()
print(f"[3] Registry entries: {len(index)}")
print()
print("Factor Validation Leaderboard (in Alpha Registry):")
print(f"{'Name':<20} {'IC':<8} {'Grade':<6} {'BeatsPeer':<10} {'Excess%':<8}")
print("-" * 55)
for aid, info in sorted(index.items()):
    s = info.get("spec", {})
    name = info.get("name", "")
    ic = s.get("ic_mean_history", [{}])[0].get("ic_mean", 0) if s.get("ic_mean_history") else 0
    grade = s.get("grade", "?")
    peer = s.get("peer_benchmark_result", {})
    beats = "✅" if peer.get("beats_peer") else "❌"
    excess = peer.get("excess_return_pct", 0)
    print(f"{name:<20} {ic:<8.4f} {grade:<6} {beats:<10} {excess:<8.2f}")
