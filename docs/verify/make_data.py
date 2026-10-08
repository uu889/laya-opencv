"""Generate a small bilingual training set in Laya's {state, questions, expected} JSONL format.

The domain mirrors laya-opencv's numeric layer: a measurement sentence -> a pass/fail decision.
"""
import json
import random
import sys

random.seed(7)
rows = []
for i in range(60):
    defect = round(random.uniform(0, 12), 1)
    count = random.randint(0, 40)
    bad = defect > 5.0
    many = count > 20
    zh = f"钢管表面检测：缺陷占比 {defect}%，缺陷数量 {count} 个。阈值：缺陷占比超过 5% 判为不合格。"
    en = f"Steel pipe inspection: defect ratio {defect}%, defect count {count}. Threshold: ratio above 5% is a reject."
    for state in (zh, en):
        rows.append({
            "state": state,
            "questions": {
                "pass": {"type": "noul", "instructions": "Is the pipe acceptable? / 该钢管是否合格？"},
                "grade": {"type": "choice", "instructions": "Defect count level / 缺陷数量等级",
                          "criteria": {"few": "20 or fewer defects / 缺陷不超过 20 个",
                                       "many": "more than 20 defects / 缺陷超过 20 个"}},
            },
            "expected": {"pass": not bad, "grade": "many" if many else "few"},
        })
random.shuffle(rows)
out = sys.argv[1]
with open(out, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(rows), "rows ->", out)
