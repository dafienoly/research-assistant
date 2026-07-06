"""Alpha Review Queue V3.8 — 审核队列"""
QUEUE = []

def submit(alpha_id): QUEUE.append({"alpha_id": alpha_id, "status": "pending"})
def list_pending(): return [q for q in QUEUE if q["status"] == "pending"]
def approve(alpha_id): ...
def reject(alpha_id): ...
