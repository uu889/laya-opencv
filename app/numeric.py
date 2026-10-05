# -*- coding: utf-8 -*-
"""数值层：让数字相关的结论由代码决定，而不是由判定模型去猜。只用标准库。

判定模型（Laya / Jev）读的是文本，不做算术。所以检测方案（recipe）里和数字有关的东西
都在这里用确定性的代码处理：

  1. 测量规格  每个测量值的单位、小数位、限值、档位、临界带（guard）
  2. 硬规则    用测量值写成的条件（all / any / not + 比较），结果是 是/否 或一个等级
  3. 文字化    把「82.3」写成「82.3 %（要求 ≥ 70：满足，高出 12.3）」再交给模型，
               模型只需要读懂结论，不需要自己比较大小
  4. 裁决      题目可以绑定硬规则：规则为准，模型的答案用来交叉核对，冲突或临界时转人工
  5. 自检      在每个阈值两侧自动生成边界用例，用来实测模型对数字的判断力

启动器和视觉服务都会导入这个文件。
"""
import math
import random

OPS = (">=", ">", "<=", "<", "==", "!=", "in", "between")
NUMERIC_OPS = (">=", ">", "<=", "<", "between")
SYMBOL = {">=": "≥", ">": ">", "<=": "≤", "<": "<", "==": "=", "!=": "≠"}

TEXT = {
    "zh": {
        "subject": "检测对象", "measures": "测量结果", "context": "补充信息", "quality": "图像质量", "notes": "说明",
        "higher": "高出 %s", "lower": "低 %s", "equal": "正好相等", "edge": "临界", "band": "档位：%s", "conf": "置信度 %s",
        "between": "%s ~ %s", "in": "属于 %s", "and": " 且 ", "or": " 或 ", "not": "不满足（%s）",
        "sep": "；", "comma": "，", "colon": "：", "lp": "（", "rp": "）", "else": "其余情况",
        "standard": "判定标准", "missing": "没有测到", "yes": "是", "no": "否",
        "r_conflict": "规则与模型的答案不一致，以规则为准", "r_marginal": "测量值落在临界带内",
        "r_low_conf": "模型置信度低于阈值", "r_missing": "缺少测量值：%s", "r_quality": "图像质量不合格：%s",
        "r_no_model": "模型没有返回这道题的答案", "r_rule_only": "模型不可用，仅按规则裁决",
        "q_blur": "画面模糊（清晰度 %s，要求 ≥ %s）", "q_dark": "画面过暗（亮度 %s，要求 ≥ %s）",
        "q_bright": "画面过亮（亮度 %s，要求 ≤ %s）", "q_ok": "合格",
    },
    "en": {
        "subject": "Subject", "measures": "Measurements", "context": "Context", "quality": "Image quality", "notes": "Notes",
        "higher": "%s above", "lower": "%s below", "equal": "exactly equal", "edge": "borderline", "band": "band: %s", "conf": "confidence %s",
        "between": "%s to %s", "in": "one of %s", "and": " and ", "or": " or ", "not": "not (%s)",
        "sep": "; ", "comma": ", ", "colon": ": ", "lp": " (", "rp": ")", "else": "otherwise",
        "standard": "Standard", "missing": "not measured", "yes": "yes", "no": "no",
        "r_conflict": "the rule and the model disagree; the rule decides", "r_marginal": "a measurement is inside the guard band",
        "r_low_conf": "model confidence is below the threshold", "r_missing": "missing measurement: %s",
        "r_quality": "image quality check failed: %s", "r_no_model": "the model returned no answer for this question",
        "r_rule_only": "the model is unavailable; decided by the rule alone",
        "q_blur": "blurry (sharpness %s, required ≥ %s)", "q_dark": "too dark (brightness %s, required ≥ %s)",
        "q_bright": "too bright (brightness %s, required ≤ %s)", "q_ok": "ok",
    },
}


def tx(lang, key, *args):
    text = TEXT["en" if lang == "en" else "zh"][key]
    return text % args if args else text


# ----------------------------------------------------------------- 数字格式

def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fmt(value, decimals=2):
    """按规格的小数位显示测量值。"""
    if not is_number(value):
        return str(value)
    decimals = max(0, min(6, int(decimals)))
    return "%.*f" % (decimals, round(float(value), decimals))


def fmt_short(value):
    """阈值、差值用的短格式：最多 4 位有效小数，去掉多余的 0。"""
    if not is_number(value):
        return str(value)
    text = "%.4f" % float(value)
    text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def spec_of(recipe, name):
    spec = (recipe.get("measurements") or {}).get(name)
    return spec if isinstance(spec, dict) else {}


def label_of(recipe, name):
    return str(spec_of(recipe, name).get("label") or name)


def unit_of(recipe, name):
    return str(spec_of(recipe, name).get("unit") or "")


def with_unit(text, unit):
    return ("%s %s" % (text, unit)) if unit else text


def normalize(recipe, values):
    """把测量值四舍五入到规格里的小数位。规则和文字说明都用这个值，保证「显示的数」和「拿来比较的数」是同一个。"""
    out = {}
    for name, value in (values or {}).items():
        if is_number(value) and not str(name).startswith("_"):
            decimals = max(0, min(6, int(spec_of(recipe, name).get("decimals", 2))))
            value = round(float(value), decimals)
        out[name] = value
    return out


# ----------------------------------------------------------------- 条件

def leaves(node):
    """条件树里所有的比较（叶子）。"""
    out = []
    if not isinstance(node, dict):
        return out
    if "all" in node or "any" in node:
        for kid in node.get("all") or node.get("any") or []:
            out.extend(leaves(kid))
    elif "not" in node:
        out.extend(leaves(node["not"]))
    elif "m" in node:
        out.append(node)
    return out


def guard_of(recipe, name, threshold):
    """临界带的半宽：测量值离阈值不超过它，就认为这次比较不可靠。"""
    spec = spec_of(recipe, name)
    guard = 0.0
    if is_number(spec.get("guard")):
        guard = max(guard, abs(float(spec["guard"])))
    if is_number(spec.get("guard_pct")) and is_number(threshold):
        guard = max(guard, abs(float(threshold)) * abs(float(spec["guard_pct"])) / 100.0)
    return guard


def compare(recipe, leaf, values):
    """算一次比较。返回 dict：ok（True / False / None=缺值）、edge（是否在临界带内）、margin（离阈值的距离）。"""
    name, op, target = leaf.get("m"), leaf.get("op", ">="), leaf.get("value")
    value = values.get(name)
    out = {"m": name, "op": op, "value": target, "actual": value, "ok": None, "edge": False, "margin": None}
    if value is None:
        return out
    if op in ("==", "!=", "in"):
        if op == "in":
            pool = target if isinstance(target, (list, tuple)) else [target]
            ok = any(_same(value, item) for item in pool)
        else:
            ok = _same(value, target)
            if op == "!=":
                ok = not ok
        out["ok"] = ok
        return out
    if not is_number(value):
        return out
    value = float(value)
    if op == "between":
        if not (isinstance(target, (list, tuple)) and len(target) == 2 and all(is_number(x) for x in target)):
            return out
        lo, hi = float(min(target)), float(max(target))
        out["ok"] = lo <= value <= hi
        distance = min(abs(value - lo), abs(value - hi))
        out["margin"] = distance
        guard = max(guard_of(recipe, name, lo), guard_of(recipe, name, hi))
        out["edge"] = guard > 0 and distance <= guard
        return out
    if not is_number(target):
        return out
    target = float(target)
    out["ok"] = {">=": value >= target, ">": value > target, "<=": value <= target, "<": value < target}[op]
    out["margin"] = abs(value - target)
    guard = guard_of(recipe, name, target)
    out["edge"] = guard > 0 and abs(value - target) <= guard
    return out


def _same(a, b):
    if is_number(a) and is_number(b):
        return float(a) == float(b)
    return str(a).strip().lower() == str(b).strip().lower()


def evaluate(recipe, node, values, trace=None):
    """算一棵条件树。返回 (lo, hi, missing)：

    lo / hi 是把临界带内的比较分别当成「不成立 / 成立」时整棵树的结果。lo == hi 说明结论稳定，
    不相等说明有测量值卡在临界带里，换一次测量结论就可能翻转。
    """
    if not isinstance(node, dict) or not node:
        return True, True, []
    if "all" in node or "any" in node:
        is_all = "all" in node
        parts = [evaluate(recipe, kid, values, trace) for kid in (node.get("all") if is_all else node.get("any")) or []]
        missing = [m for p in parts for m in p[2]]
        if is_all:
            return all(p[0] for p in parts), all(p[1] for p in parts), missing
        return any(p[0] for p in parts), any(p[1] for p in parts), missing
    if "not" in node:
        lo, hi, missing = evaluate(recipe, node["not"], values, trace)
        return (not hi), (not lo), missing
    result = compare(recipe, node, values)
    if trace is not None:
        trace.append(result)
    if result["ok"] is None:
        return False, False, [result["m"]]
    if result["edge"]:
        return False, True, []
    return result["ok"], result["ok"], []


def point(recipe, node, values):
    """不考虑临界带，按测量值本身算出的结果。"""
    if not isinstance(node, dict) or not node:
        return True
    if "all" in node:
        return all(point(recipe, kid, values) for kid in node["all"] or [])
    if "any" in node:
        return any(point(recipe, kid, values) for kid in node["any"] or [])
    if "not" in node:
        return not point(recipe, node["not"], values)
    return bool(compare(recipe, node, values)["ok"])


def run_rule(recipe, rule_id, values, lang="zh"):
    """算一条硬规则。返回 {id, label, type, result, marginal, missing, checks, text}。"""
    rule = (recipe.get("rules") or {}).get(rule_id) or {}
    kind = "grade" if "cases" in rule else "bool"
    out = {"id": rule_id, "label": str(rule.get("label") or rule_id), "type": kind, "result": None,
           "marginal": False, "missing": [], "checks": []}
    trace = []
    if kind == "bool":
        lo, hi, missing = evaluate(recipe, rule.get("when") or {}, values, trace)
        out["missing"] = sorted(set(missing))
        if not out["missing"]:
            out["result"] = point(recipe, rule.get("when") or {}, values)
            out["marginal"] = lo != hi
    else:
        chosen, marginal, missing_all = None, False, []
        for case in rule.get("cases") or []:
            when = case.get("when")
            if not when:                         # 没有条件的一档是兜底
                if chosen is None:
                    chosen = case.get("value")
                break
            lo, hi, missing = evaluate(recipe, when, values, trace)
            missing_all.extend(missing)
            if lo != hi:
                marginal = True
            if chosen is None and point(recipe, when, values):
                chosen = case.get("value")
                break
        out["missing"] = sorted(set(missing_all))
        if not out["missing"]:
            out["result"] = chosen
            out["marginal"] = marginal
    seen = set()
    for item in trace:                           # 同一个比较在多档里出现时只留一条
        key = (item["m"], item["op"], str(item["value"]))
        if key not in seen:
            seen.add(key)
            out["checks"].append(item)
    out["text"] = tx(lang, "sep").join(check_text(recipe, c, lang) for c in out["checks"])
    return out


# ----------------------------------------------------------------- 文字化

def threshold_text(recipe, name, op, target):
    unit = unit_of(recipe, name)
    if op == "between" and isinstance(target, (list, tuple)) and len(target) == 2:
        return with_unit("%s ~ %s" % (fmt_short(target[0]), fmt_short(target[1])), unit)
    if op == "in":
        pool = target if isinstance(target, (list, tuple)) else [target]
        return "∈ {%s}" % ", ".join(str(x) for x in pool)
    return "%s %s" % (SYMBOL.get(op, op), with_unit(fmt_short(target) if is_number(target) else str(target), unit))


def check_text(recipe, check, lang="zh"):
    """一次比较的完整说法，用在裁决说明里：成熟色占比 82.3 %（≥ 70 %：是）。"""
    name = check["m"]
    spec = spec_of(recipe, name)
    actual = check["actual"]
    shown = tx(lang, "missing") if actual is None else with_unit(fmt(actual, spec.get("decimals", 2)), unit_of(recipe, name))
    verdict = tx(lang, "missing") if check["ok"] is None else tx(lang, "yes" if check["ok"] else "no")
    text = "%s %s%s%s%s%s" % (label_of(recipe, name), shown, tx(lang, "lp"),
                              threshold_text(recipe, name, check["op"], check["value"]), tx(lang, "colon"), verdict)
    if check["edge"]:
        text += tx(lang, "comma") + tx(lang, "edge")
    return text + tx(lang, "rp")


def comparison_phrase(recipe, name, op, target, value, lang="zh"):
    """测量值旁边的括号内容：≥ 70 %：是，高出 12.3。

    写法和题目里的判定标准逐字对应（同样的符号、同样的阈值），后面直接给出这一条成立与否，
    再补一句测量值比阈值高多少或低多少。模型只需要把标准里的每一条对上「是 / 否」。
    """
    check = compare(recipe, {"m": name, "op": op, "value": target}, {name: value})
    head = threshold_text(recipe, name, op, target) + tx(lang, "colon")
    if check["ok"] is None:
        return head + tx(lang, "missing")
    parts = [tx(lang, "yes" if check["ok"] else "no")]
    if is_number(value) and is_number(target) and op in (">=", ">", "<=", "<"):
        gap = round(float(value) - float(target), 6)
        if gap == 0:
            parts.append(tx(lang, "equal"))
        else:
            parts.append(tx(lang, "higher" if gap > 0 else "lower", fmt_short(abs(gap))))
    if check["edge"]:
        parts.append(tx(lang, "edge"))
    return head + tx(lang, "comma").join(parts)


def band_of(recipe, name, value):
    """测量值落在哪一档。bands 从低到高写，每档的 max 是不含的上界，最后一档不写 max。"""
    bands = spec_of(recipe, name).get("bands")
    if not isinstance(bands, list) or not is_number(value):
        return None
    for band in bands:
        if not isinstance(band, dict):
            continue
        if not is_number(band.get("max")) or float(value) < float(band["max"]):
            return str(band.get("label") or "")
    return None


def thresholds_for(recipe, name):
    """这个测量值需要对照的所有阈值：规格里的 limit，加上规则里用到的。"""
    found, seen = [], set()

    def add(op, target):
        key = (op, str(target))
        if key not in seen:
            seen.add(key)
            found.append((op, target))

    limit = spec_of(recipe, name).get("limit")
    if isinstance(limit, dict):
        if is_number(limit.get("min")) and is_number(limit.get("max")):
            add("between", [limit["min"], limit["max"]])
        elif is_number(limit.get("min")):
            add(">=", limit["min"])
        elif is_number(limit.get("max")):
            add("<=", limit["max"])
    for rule in (recipe.get("rules") or {}).values():
        if not isinstance(rule, dict):
            continue
        nodes = [rule.get("when")] + [case.get("when") for case in rule.get("cases") or [] if isinstance(case, dict)]
        for node in nodes:
            for leaf in leaves(node):
                if leaf.get("m") == name and leaf.get("op", ">=") in OPS:
                    add(leaf.get("op", ">="), leaf.get("value"))
    return found


def describe(recipe, name, value, lang="zh", level="compared", detail=None):
    """一个测量值的文字说法。level="raw" 只有数值，"compared" 带上和每个阈值的比较结论。"""
    spec = spec_of(recipe, name)
    if value is None:
        return tx(lang, "missing")
    if not is_number(value):
        text = str(value)
        if isinstance(detail, dict) and is_number(detail.get("prob")):
            text += tx(lang, "lp") + tx(lang, "conf", fmt(detail["prob"], 2)) + tx(lang, "rp")
        return text
    text = with_unit(fmt(value, spec.get("decimals", 2)), unit_of(recipe, name))
    if level == "raw":
        return text
    notes = []
    band = band_of(recipe, name, value)
    if band:
        notes.append(tx(lang, "band", band))
    for op, target in thresholds_for(recipe, name):
        if op in ("==", "!=", "in"):
            continue
        notes.append(comparison_phrase(recipe, name, op, target, value, lang))
    if notes:
        text += tx(lang, "lp") + tx(lang, "sep").join(notes) + tx(lang, "rp")
    return text


def condition_text(recipe, node, lang="zh"):
    """把条件树写成一句话，用来放进题目和页面：成熟色占比 ≥ 70 % 且 病斑占比 ≤ 3 %。"""
    if not isinstance(node, dict) or not node:
        return ""
    if "all" in node or "any" in node:
        is_all = "all" in node
        parts = [condition_text(recipe, kid, lang) for kid in (node.get("all") if is_all else node.get("any")) or []]
        parts = [p for p in parts if p]
        joined = tx(lang, "and" if is_all else "or").join(parts)
        return joined
    if "not" in node:
        return tx(lang, "not", condition_text(recipe, node["not"], lang))
    name, op = node.get("m"), node.get("op", ">=")
    return "%s %s" % (label_of(recipe, name), threshold_text(recipe, name, op, node.get("value")))


def rule_text(recipe, rule_id, lang="zh"):
    rule = (recipe.get("rules") or {}).get(rule_id) or {}
    if "cases" not in rule:
        return condition_text(recipe, rule.get("when") or {}, lang)
    parts = []
    for case in rule.get("cases") or []:
        when = case.get("when")
        parts.append("%s%s%s" % (case.get("value"), tx(lang, "colon"), condition_text(recipe, when, lang) if when else tx(lang, "else")))
    return tx(lang, "sep").join(parts)


def build_state(recipe, values, lang="zh", level="compared", context=None, details=None, quality=None):
    """组装交给判定模型的素材（state）。"""
    state = {}
    if recipe.get("subject"):
        state[tx(lang, "subject")] = str(recipe["subject"])
    block = {}
    specs = recipe.get("measurements") or {}
    names = [n for n in specs if n in values] + [n for n in values if n not in specs]
    in_rules = set(leaf.get("m") for rule in (recipe.get("rules") or {}).values() if isinstance(rule, dict)
                   for node in [rule.get("when")] + [c.get("when") for c in rule.get("cases") or [] if isinstance(c, dict)]
                   for leaf in leaves(node))
    for name in names:
        if name.startswith("_") or spec_of(recipe, name).get("hidden"):
            continue
        if values.get(name) is None and name not in in_rules:
            continue                             # 没有值、规则也用不到的项（例如识别模型还没训练）不写进素材
        block[label_of(recipe, name)] = describe(recipe, name, values.get(name), lang, level, (details or {}).get(name))
    state[tx(lang, "measures")] = block
    if quality and not quality.get("ok", True):
        state[tx(lang, "quality")] = tx(lang, "sep").join(quality.get("problems") or [])
    if context:
        state[tx(lang, "context")] = context
    return state


def bound_questions(recipe, lang="zh", append_standard=True):
    """返回发给模型的题目：绑定了硬规则的题目，在题干后面附上判定标准。"""
    questions = {}
    bindings = recipe.get("bindings") or {}
    for qid, spec in (recipe.get("questions") or {}).items():
        if not isinstance(spec, dict):
            continue
        spec = dict(spec)
        bind = bindings.get(qid) or {}
        rule_id = bind.get("rule")
        if append_standard and rule_id and rule_id in (recipe.get("rules") or {}) and bind.get("show_standard", True):
            standard = rule_text(recipe, rule_id, lang)
            if standard:
                spec["instructions"] = "%s\n%s%s%s" % (str(spec.get("instructions") or "").rstrip(), tx(lang, "standard"),
                                                         tx(lang, "colon"), standard)
        questions[qid] = spec
    return questions


# ----------------------------------------------------------------- 图像质量

def check_quality(recipe, values, lang="zh"):
    """按方案里的 quality 设置检查清晰度和亮度。不合格的图不应该拿来下结论。"""
    cfg = recipe.get("quality") or {}
    problems = []
    sharp, bright = values.get("_sharpness"), values.get("_brightness")
    if is_number(cfg.get("min_sharpness")) and is_number(sharp) and sharp < cfg["min_sharpness"]:
        problems.append(tx(lang, "q_blur", fmt(sharp, 1), fmt_short(cfg["min_sharpness"])))
    limits = cfg.get("brightness")
    if isinstance(limits, (list, tuple)) and len(limits) == 2 and is_number(bright):
        if is_number(limits[0]) and bright < limits[0]:
            problems.append(tx(lang, "q_dark", fmt(bright, 1), fmt_short(limits[0])))
        if is_number(limits[1]) and bright > limits[1]:
            problems.append(tx(lang, "q_bright", fmt(bright, 1), fmt_short(limits[1])))
    return {"ok": not problems, "problems": problems, "sharpness": sharp, "brightness": bright}


# ----------------------------------------------------------------- 裁决

def question_type(spec):
    kind = (spec or {}).get("type")
    return kind if kind in ("noul", "choice", "score") else "noul"


def laya_value(answer, kind):
    """从模型的一道题答案里取出结论和置信度。"""
    if not isinstance(answer, dict):
        return None, None
    conf = answer.get("answer_confidence")
    if kind == "choice" and "choice" in answer:
        if conf is None and isinstance(answer.get("probabilities"), dict):
            probs = [p for p in answer["probabilities"].values() if is_number(p)]
            conf = max(probs) if probs else None
        return answer.get("choice"), conf
    if kind == "score" and "score" in answer:
        value = int(round(float(answer["score"]))) if is_number(answer.get("score")) else None
        if conf is None and isinstance(answer.get("probabilities"), dict):
            probs = [p for p in answer["probabilities"].values() if is_number(p)]
            conf = max(probs) if probs else None
        return value, conf
    if "noul" in answer and is_number(answer.get("noul")):
        p = float(answer["noul"])
        return p >= 0.5, (conf if conf is not None else max(p, 1 - p))
    return None, conf


def rule_value(result, kind):
    """把规则的结果换成和题目类型对应的值，便于和模型的答案比较。"""
    if result is None:
        return None
    if kind == "noul":
        return bool(result) if isinstance(result, bool) else str(result).strip().lower() in ("true", "yes", "1", "是")
    if kind == "score":
        try:
            return int(result)
        except (TypeError, ValueError):
            return None
    return str(result)


def same_answer(a, b, kind):
    if a is None or b is None:
        return None
    if kind == "choice":
        return str(a) == str(b)
    return a == b


def show_value(value, kind, spec, lang="zh"):
    if value is None:
        return "-"
    if kind == "noul":
        text = tx(lang, "yes" if value else "no")
        return text[:1].upper() + text[1:]
    if kind == "score":
        levels = (spec or {}).get("criteria")
        if isinstance(levels, list) and 0 <= int(value) < len(levels):
            return "%s · %s" % (value, levels[int(value)])
        return str(value)
    return str(value)


def decide(recipe, values, answers=None, lang="zh", min_confidence=None, quality=None, model_error=None):
    """逐题给出最终结论。

    answers 是模型返回的 answers（可以是 None：模型不可用时只按规则裁决）。
    每道题的结论来源：
      绑定了规则且 mode = enforce（默认）  规则为准，模型的答案只用来交叉核对
      绑定了规则且 mode = advise           模型为准，规则的结果作为参照
      没有绑定规则                          模型为准
    冲突、临界、低置信度、缺测量值、图像质量不合格，都会把 review 置为 True（建议人工复核）。
    """
    answers = answers if isinstance(answers, dict) else {}
    bindings = recipe.get("bindings") or {}
    rules_cache = {}
    verdicts = {}
    for qid, spec in (recipe.get("questions") or {}).items():
        if not isinstance(spec, dict):
            continue
        kind = question_type(spec)
        bind = bindings.get(qid) or {}
        rule_id = bind.get("rule") if bind.get("rule") in (recipe.get("rules") or {}) else None
        mode = "advise" if bind.get("mode") == "advise" else "enforce"
        item = {"type": kind, "instructions": str(spec.get("instructions") or ""), "final": None, "final_text": "-",
                "source": "none", "mode": mode if rule_id else "model", "rule": None, "model": None,
                "agree": None, "review": False, "reasons": []}

        rule_result = None
        if rule_id:
            if rule_id not in rules_cache:
                rules_cache[rule_id] = run_rule(recipe, rule_id, values, lang)
            rule = rules_cache[rule_id]
            rule_result = rule_value(rule["result"], kind)
            item["rule"] = {"id": rule_id, "label": rule["label"], "result": rule_result,
                            "result_text": show_value(rule_result, kind, spec, lang), "marginal": rule["marginal"],
                            "missing": rule["missing"], "checks": rule["checks"], "text": rule["text"],
                            "standard": rule_text(recipe, rule_id, lang)}
            if rule["missing"]:
                item["review"] = True
                item["reasons"].append(tx(lang, "r_missing", ", ".join(label_of(recipe, m) for m in rule["missing"])))
            if rule["marginal"]:
                item["review"] = True
                item["reasons"].append(tx(lang, "r_marginal"))

        model_result, conf = laya_value(answers.get(qid), kind)
        if qid in answers:
            item["model"] = {"result": model_result, "result_text": show_value(model_result, kind, spec, lang),
                             "confidence": conf, "answer": answers.get(qid)}
            if is_number(min_confidence) and is_number(conf) and conf < float(min_confidence):
                item["model"]["low_confidence"] = True
                if not rule_id or mode == "advise":          # 结论来自模型时，低置信度才需要复核
                    item["review"] = True
                    item["reasons"].append(tx(lang, "r_low_conf"))

        if rule_id and model_result is not None and rule_result is not None:
            item["agree"] = same_answer(rule_result, model_result, kind)
            if item["agree"] is False:
                item["review"] = True
                item["reasons"].append(tx(lang, "r_conflict"))

        if rule_id and mode == "enforce" and rule_result is not None:
            item["final"], item["source"] = rule_result, "rule"
        elif model_result is not None:
            item["final"], item["source"] = model_result, "model"
        elif rule_result is not None:                        # advise 模式下模型没给答案：退回规则
            item["final"], item["source"] = rule_result, "rule"
        if model_result is None:
            if rule_id and rule_result is not None:
                if model_error:
                    item["reasons"].append(tx(lang, "r_rule_only"))
            else:
                item["review"] = True
                item["reasons"].append(tx(lang, "r_no_model"))
        item["final_text"] = show_value(item["final"], kind, spec, lang)
        verdicts[qid] = item

    reasons = []
    if quality and not quality.get("ok", True):
        reasons.append(tx(lang, "r_quality", tx(lang, "sep").join(quality.get("problems") or [])))
    for item in verdicts.values():
        for reason in item["reasons"]:
            if reason not in reasons:
                reasons.append(reason)
    review = bool(quality and not quality.get("ok", True)) or any(v["review"] for v in verdicts.values())
    return {"verdicts": verdicts, "review": review, "reasons": reasons}


# ----------------------------------------------------------------- 检查方案

def validate(recipe):
    """检查方案里数值层相关的部分，返回问题列表（空 = 没问题）。"""
    problems = []
    if not isinstance(recipe, dict):
        return ["recipe must be an object"]
    specs = recipe.get("measurements") if isinstance(recipe.get("measurements"), dict) else {}
    rules = recipe.get("rules") if isinstance(recipe.get("rules"), dict) else {}
    questions = recipe.get("questions") if isinstance(recipe.get("questions"), dict) else {}
    for rule_id, rule in rules.items():
        if not isinstance(rule, dict):
            problems.append("rule '%s' must be an object" % rule_id)
            continue
        nodes = [rule.get("when")] + [c.get("when") for c in rule.get("cases") or [] if isinstance(c, dict)]
        if "cases" not in rule and not rule.get("when"):
            problems.append("rule '%s' needs 'when' or 'cases'" % rule_id)
        for node in nodes:
            for leaf in leaves(node):
                if leaf.get("m") not in specs:
                    problems.append("rule '%s' uses unknown measurement '%s'" % (rule_id, leaf.get("m")))
                if leaf.get("op", ">=") not in OPS:
                    problems.append("rule '%s' uses unknown operator '%s'" % (rule_id, leaf.get("op")))
    for qid, bind in (recipe.get("bindings") or {}).items():
        if qid not in questions:
            problems.append("binding '%s' has no matching question" % qid)
            continue
        rule_id = (bind or {}).get("rule")
        if rule_id not in rules:
            problems.append("binding '%s' points to unknown rule '%s'" % (qid, rule_id))
            continue
        kind = question_type(questions[qid])
        rule = rules[rule_id]
        if kind == "noul" and "cases" in rule:
            problems.append("question '%s' is yes/no but rule '%s' returns a grade" % (qid, rule_id))
        if kind != "noul" and "cases" not in rule:
            problems.append("question '%s' is %s but rule '%s' returns yes/no" % (qid, kind, rule_id))
        if kind == "choice" and "cases" in rule:
            criteria = questions[qid].get("criteria")
            labels = set(criteria) if isinstance(criteria, (dict, list)) else set()
            for case in rule.get("cases") or []:
                if labels and str(case.get("value")) not in set(str(x) for x in labels):
                    problems.append("rule '%s' returns '%s', which is not an option of question '%s'" % (rule_id, case.get("value"), qid))
    return problems


# ----------------------------------------------------------------- 边界用例（数字判断力自检）

OFFSETS = (-0.30, -0.10, -0.03, -0.005, 0.005, 0.03, 0.10, 0.30)


def _span(recipe, name):
    """测量值的取值范围，用来把生成的数值限制在合理区间。"""
    spec = spec_of(recipe, name)
    rng = spec.get("range")
    if isinstance(rng, (list, tuple)) and len(rng) == 2 and all(is_number(x) for x in rng):
        return float(rng[0]), float(rng[1])
    return (0.0, 100.0) if spec.get("unit") == "%" else (0.0, float("inf"))


def _clamp(recipe, name, value):
    lo, hi = _span(recipe, name)
    value = max(lo, min(hi, value))
    decimals = int(spec_of(recipe, name).get("decimals", 2))
    return round(value, decimals) if decimals > 0 else float(int(round(value)))


def _near(recipe, name, target, offset):
    """阈值旁边的一个数：偏离 offset（相对值），阈值是 0 时按取值范围偏移。"""
    target = float(target)
    lo, hi = _span(recipe, name)
    scale = abs(target) if target else (hi - lo if math.isfinite(hi - lo) and hi > lo else 1.0) * 0.1
    step = 10 ** (-int(spec_of(recipe, name).get("decimals", 2)))
    delta = offset * scale
    if abs(delta) < step:                        # 至少错开一个最小刻度，否则四舍五入后和阈值相等
        delta = step if offset > 0 else -step
    return _clamp(recipe, name, target + delta)


def _typical(recipe, name, good=True):
    """一个明显合格（或明显不合格）的取值，作为其它测量值的背景。"""
    spec = spec_of(recipe, name)
    if is_number(spec.get("typical")) and good:
        return _clamp(recipe, name, float(spec["typical"]))
    pairs = [(op, t) for op, t in thresholds_for(recipe, name) if op in (">=", ">", "<=", "<") and is_number(t)]
    if not pairs:
        lo, hi = _span(recipe, name)
        return _clamp(recipe, name, lo if not math.isfinite(hi) else (lo + hi) / 2)
    uppers = [float(t) for op, t in pairs if op in ("<=", "<")]
    lowers = [float(t) for op, t in pairs if op in (">=", ">")]
    if good:
        if uppers and not lowers:
            return _clamp(recipe, name, min(uppers) * 0.4)
        if lowers and not uppers:
            return _near(recipe, name, max(lowers), 0.3)
        return _clamp(recipe, name, (max(lowers) + min(uppers)) / 2)
    if uppers:
        return _near(recipe, name, max(uppers), 0.5)
    return _clamp(recipe, name, min(lowers) * 0.4)


def probe_cases(recipe, limit=48, seed=7):
    """为方案里绑定了硬规则的题目生成边界用例。

    每个用例是一组测量值，正确答案由 run_rule 算出，所以用例一定和规则一致。
    生成方式：每次让一个测量值落在某个阈值的两侧（±0.5%、±3%、±10%、±30%），其它测量值取明显合格的值；
    再补一些随机组合。离阈值最近的相对距离记在 distance 里，用来区分「贴近边界」和「远离边界」的表现。
    """
    bindings = recipe.get("bindings") or {}
    questions = recipe.get("questions") or {}
    rules = recipe.get("rules") or {}
    bound = [(qid, bindings[qid].get("rule")) for qid in questions
             if isinstance(bindings.get(qid), dict) and bindings[qid].get("rule") in rules]
    if not bound:
        return []
    used = []
    for _, rule_id in bound:
        rule = rules[rule_id]
        nodes = [rule.get("when")] + [c.get("when") for c in rule.get("cases") or [] if isinstance(c, dict)]
        for node in nodes:
            for leaf in leaves(node):
                if leaf.get("op", ">=") in NUMERIC_OPS and leaf.get("m") in (recipe.get("measurements") or {}):
                    used.append(leaf)
    names = []
    for leaf in used:
        if leaf["m"] not in names:
            names.append(leaf["m"])
    if not names:
        return []
    base_good = {n: _typical(recipe, n, True) for n in names}
    base_bad = {n: _typical(recipe, n, False) for n in names}
    rng = random.Random(seed)
    vectors, seen = [], set()

    def push(vec):
        key = tuple(vec[n] for n in names)
        if key not in seen:
            seen.add(key)
            vectors.append(dict(vec))

    for leaf in used:
        targets = leaf["value"] if leaf.get("op") == "between" else [leaf["value"]]
        for target in targets if isinstance(targets, (list, tuple)) else [targets]:
            if not is_number(target):
                continue
            for offset in OFFSETS:
                vec = dict(base_good)
                vec[leaf["m"]] = _near(recipe, leaf["m"], target, offset)
                push(vec)
    push(base_good)
    push(base_bad)
    thresholds = {n: [float(t) for op, t in thresholds_for(recipe, n) if is_number(t)] or [1.0] for n in names}
    for _ in range(limit * 4):
        if len(vectors) >= max(limit, 8):
            break
        vec = {}
        for n in names:
            target = rng.choice(thresholds[n])
            vec[n] = _near(recipe, n, target, rng.choice(OFFSETS + (-0.6, 0.6)))
        push(vec)
    if len(vectors) > limit:                     # 太多时均匀抽取，保持各个阈值都有用例
        step = len(vectors) / float(limit)
        vectors = [vectors[int(i * step)] for i in range(limit)]

    cases = []
    for vec in vectors:
        gold, marginal = {}, False
        for qid, rule_id in bound:
            result = run_rule(recipe, rule_id, vec)
            gold[qid] = rule_value(result["result"], question_type(questions[qid]))
            marginal = marginal or result["marginal"]
        distance = None
        for leaf in used:
            targets = leaf["value"] if isinstance(leaf["value"], (list, tuple)) else [leaf["value"]]
            for target in targets:
                if is_number(target) and is_number(vec.get(leaf["m"])):
                    lo, hi = _span(recipe, leaf["m"])
                    scale = abs(float(target)) or ((hi - lo) * 0.1 if math.isfinite(hi - lo) and hi > lo else 1.0)
                    d = abs(vec[leaf["m"]] - float(target)) / scale
                    distance = d if distance is None else min(distance, d)
        cases.append({"values": vec, "gold": gold, "distance": round(distance, 4) if distance is not None else None,
                      "marginal": marginal})
    return cases


def score_probe(recipe, cases, answers_list):
    """对照用例的正确答案给模型打分。answers_list 和 cases 一一对应，每项是模型返回的 answers。"""
    questions = recipe.get("questions") or {}
    report = {}
    for index, case in enumerate(cases):
        answers = answers_list[index] if index < len(answers_list) and isinstance(answers_list[index], dict) else {}
        for qid, gold in case["gold"].items():
            kind = question_type(questions.get(qid))
            got, conf = laya_value(answers.get(qid), kind)
            row = report.setdefault(qid, {"n": 0, "correct": 0, "near_n": 0, "near_correct": 0, "far_n": 0,
                                          "far_correct": 0, "conf_sum": 0.0, "conf_n": 0, "misses": []})
            if gold is None:
                continue
            ok = same_answer(gold, got, kind) is True
            near = case["distance"] is not None and case["distance"] <= 0.05
            row["n"] += 1
            row["correct"] += int(ok)
            row["near_n" if near else "far_n"] += 1
            row["near_correct" if near else "far_correct"] += int(ok)
            if is_number(conf):
                row["conf_sum"] += float(conf)
                row["conf_n"] += 1
            if not ok and len(row["misses"]) < 6:
                row["misses"].append({"values": case["values"], "expected": gold, "got": got, "confidence": conf,
                                      "distance": case["distance"]})
    for row in report.values():
        row["accuracy"] = round(row["correct"] / row["n"], 4) if row["n"] else None
        row["near_accuracy"] = round(row["near_correct"] / row["near_n"], 4) if row["near_n"] else None
        row["far_accuracy"] = round(row["far_correct"] / row["far_n"], 4) if row["far_n"] else None
        row["mean_confidence"] = round(row.pop("conf_sum") / row["conf_n"], 4) if row["conf_n"] else None
        row.pop("conf_n", None)
    return report


def finetune_records(recipe, cases, lang="zh", level="compared"):
    """把用例写成 {state, questions, gold} 记录，对应上游微调脚本读取的 JSONL 结构。"""
    questions = bound_questions(recipe, lang)
    records = []
    for case in cases:
        gold = {qid: value for qid, value in case["gold"].items() if value is not None}
        if not gold:
            continue
        records.append({"state": build_state(recipe, case["values"], lang, level),
                        "questions": {qid: questions[qid] for qid in gold if qid in questions}, "gold": gold})
    return records
