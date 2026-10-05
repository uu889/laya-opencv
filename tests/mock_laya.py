# -*- coding: utf-8 -*-
"""测试用的假 Laya 服务。只在开发和自动测试时用，不是判定模型，也不随工作台启动。

它实现 /health、/v1/systemone、/v1/systemone/batch，返回的结构和真的 Laya 一样，
答案来自对素材文字的简单解析：
  - 素材里带着数值层写好的比较结论（「≥ 70 %：是」）时，按题干里的判定标准把结论拼起来
  - 素材里只有裸数字时，它「看不懂」，给出接近瞎猜的答案
这正好用来验证工作台的两件事：接口对接是否正确，以及自检报告能否分辨这两种情况。

    python tests/mock_laya.py --port 8000 [--noise 0.03]
"""
import argparse
import hashlib
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOISE = 0.0


def flat(state):
    """把素材摊平成「标签: 内容」的行，嵌套对象的每一项各占一行。"""
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        lines = []
        for key, value in state.items():
            if isinstance(value, (dict, list)):
                lines.append(flat(value))
            else:
                lines.append("%s: %s" % (key, value))
        return "\n".join(lines)
    if isinstance(state, list):
        return "\n".join(flat(v) for v in state)
    return str(state)


def coin(*parts):
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2.0 ** 32


def clause_truth(clause, text):
    """一个条件（「成熟色占比 ≥ 70 %」）在素材里的结论。素材里没有对应的比较结论时返回 None。"""
    clause = clause.strip()
    m = re.match(r"^(.*?)\s*(≥|≤|>|<)\s*([-\d.]+)", clause)
    if not m:
        return None
    label, op, number = m.group(1).strip(), m.group(2), m.group(3)
    for line in text.splitlines():
        if not line.strip().startswith(label + ":"):
            continue
        hit = re.search(r"%s\s*%s(?![\d.])[^：:；;）)]*(?:：|: )(是|否|yes|no)" % (re.escape(op), re.escape(number)), line)
        if hit:
            return hit.group(1) in ("是", "yes")
    return None


def condition_truth(cond, text):
    cond = cond.strip()
    m = re.match(r"^(?:不满足（(.*)）|not \((.*)\))$", cond)
    if m:
        inner = condition_truth(m.group(1) or m.group(2), text)
        return None if inner is None else not inner
    for sep, func in ((" 或 ", any), (" or ", any), (" 且 ", all), (" and ", all)):
        if sep in cond:
            parts = [condition_truth(part, text) for part in cond.split(sep)]
            if any(p is None for p in parts):
                return None
            return func(parts)
    return clause_truth(cond, text)


def answer(qid, spec, text):
    kind = spec.get("type", "noul")
    instructions = str(spec.get("instructions") or "")
    standard = None
    m = re.search(r"(?:判定标准：|Standard: )(.*)$", instructions, re.S)
    if m:
        standard = m.group(1).strip()
    flip = coin("noise", qid, text) < NOISE
    if kind == "noul":
        truth = condition_truth(standard, text) if standard else None
        if truth is None:
            p = 0.35 + 0.3 * coin(qid, text)                 # 看不懂：接近 0.5 的瞎猜
        else:
            p = 0.93 if truth != flip else 0.08
        return {"type": "noul", "noul": round(p, 4), "answer_confidence": round(max(p, 1 - p), 4)}
    if kind == "choice":
        criteria = spec.get("criteria") or {}
        labels = list(criteria) if isinstance(criteria, (dict, list)) else []
        chosen = None
        if standard:
            for part in re.split(r"；|; ", standard):
                if "：" in part or ": " in part:
                    label, cond = re.split(r"：|: ", part, maxsplit=1)
                    if cond.strip() in ("其余情况", "otherwise"):
                        chosen = chosen or label.strip()
                        break
                    truth = condition_truth(cond, text)
                    if truth is None:
                        chosen = None
                        break
                    if truth:
                        chosen = label.strip()
                        break
        if chosen is None or chosen not in labels or flip:
            chosen = labels[int(coin(qid, text) * len(labels)) % len(labels)] if labels else ""
            top = 0.45
        else:
            top = 0.9
        rest = (1 - top) / max(1, len(labels) - 1)
        return {"type": "choice", "choice": chosen, "probabilities": {k: round(top if k == chosen else rest, 4) for k in labels},
                "answer_confidence": top}
    levels = spec.get("criteria") or []
    n = max(2, len(levels))
    bad = len(re.findall(r"(?:：|: )(?:否|no)\b", text))
    score = min(n - 1, bad) if bad else 0
    probs = {str(i): round(0.7 if i == score else 0.3 / (n - 1), 4) for i in range(n)}
    return {"type": "score", "score": float(score), "probabilities": probs,
            "legend": {str(i): levels[i] for i in range(len(levels))}, "answer_confidence": 0.7}


def predict(state, questions):
    text = flat(state)
    return {"model": "mock-laya", "answers": {qid: answer(qid, spec, text) for qid, spec in questions.items()},
            "usage": {"input_tokens": len(text) // 2, "output_tokens": 0}, "routing": {"reason": "mock"}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Inference-Time-Ms", "1.00")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(200, {"status": "ok", "loaded": ["mock-laya"], "revisions": {}, "device": "cpu"})
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8") or "{}")
        if not isinstance(body.get("questions"), dict):
            return self._json(400, {"detail": "request body must be an object with a 'questions' field"})
        if self.path.startswith("/v1/systemone/batch"):
            return self._json(200, {"results": [predict(s, body["questions"]) for s in body.get("states") or []]})
        if self.path.startswith("/v1/systemone"):
            return self._json(200, predict(body.get("state"), body["questions"]))
        self._json(404, {"detail": "not found"})


def main():
    global NOISE
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--noise", type=float, default=0.0)
    args = parser.parse_args()
    NOISE = args.noise
    print("mock Laya on http://127.0.0.1:%d (noise %.2f)" % (args.port, NOISE), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
