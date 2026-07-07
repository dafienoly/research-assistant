"""每日自动 evolve: 读最新排名 → LLM 生成 → 保存 → 通知"""
import sys, json, csv
sys.path.insert(0, "/home/ly/.hermes/research-assistant/commands")
from pathlib import Path
from factor_lab.evolution import generate_candidates

ranking_dir = sorted(Path("/mnt/d/HermesReports/factor_lab").glob("*/factor_ranking.csv"))
if not ranking_dir:
    print("无排名文件")
    sys.exit(1)

ranking = ranking_dir[-1]
existing = []
with open(ranking, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 10:
            break
        existing.append({
            "name": row["name"],
            "mean_ic": float(row.get("mean_ic", 0) or 0),
            "ir": float(row.get("ir", 0) or 0),
            "category": row.get("category", ""),
        })

cands = generate_candidates(existing)
print(f"生成 {len(cands)} 个候选")
for c in cands:
    print(f"  {c['name']}: {c['expression']}")

out_dir = "/mnt/d/HermesReports/factor_lab"
Path(out_dir).mkdir(parents=True, exist_ok=True)
p = Path(out_dir) / "evolved_candidates.json"
old = json.load(open(p)) if p.exists() else []
all_c = old + cands
seen = set()
uniq = []
for c in all_c:
    n = c.get("name", "")
    if n not in seen:
        seen.add(n)
        uniq.append(c)
json.dump(uniq, open(p, "w"), ensure_ascii=False, indent=2)
print(f"累计进化因子: {len(uniq)} 个")
