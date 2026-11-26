"""Writing module (TOPIK II 51-54): source/write/*.wr -> data/write.json.

.wr format ('#!' comments, blank lines ignored):
  === <id>                 one item (or one guide section in guide.wr)
  S: source label (zh)     H: Korean title   HZ: Chinese title
  I: Korean instruction    IZ: its Chinese   (51/52 default to the standard instruction)
  K: passage/prompt line   KZ: its Chinese (must follow the K); 'K: # text' marks a heading line
  L: bullet question (54)  LZ: its Chinese
  C: chart spec (one-line JSON, 53)          CZ: Chinese description of the chart
  A: answer for blank (51/52: first A = ㉠, second = ㉡), variants separated by ' | '   AZ: Chinese of the first variant
  M: model-answer paragraph   MZ: its Chinese
  N: note line (zh; Korean quoted from the item in 「」, grammar forms in “”)
  X: key expression 'ko | zh'
  P: points/length line (guide only)
"""
import re, json, os

DEFAULT_INS = {
    51: ("다음을 읽고 ㉠과 ㉡에 들어갈 말을 각각 한 문장으로 쓰십시오. (각 10점)", "阅读下文，在㉠和㉡处各写一个完整的句子。（每空5分，共10分）"),
    52: ("다음을 읽고 ㉠과 ㉡에 들어갈 말을 각각 한 문장으로 쓰십시오. (각 10점)", "阅读下文，在㉠和㉡处各写一个完整的句子。（每空5分，共10分）"),
}
LENGTH = {53: (200, 300), 54: (600, 700)}
PAIRED = {"KZ": "K", "LZ": "L", "AZ": "A", "MZ": "M"}


def parse_wr(path):
    items, cur = [], None
    for no, raw in enumerate(open(path, encoding="utf-8"), 1):
        l = raw.rstrip("\n").strip()
        if not l or l.startswith("#!"):
            continue
        m = re.match(r"^=== (\S+)$", l)
        if m:
            cur = {"id": m.group(1), "K": [], "L": [], "A": [], "M": [], "N": [], "X": [], "CZ": []}
            items.append(cur)
            continue
        m = re.match(r"^(KZ|LZ|AZ|MZ|HZ|IZ|CZ|K|L|A|M|N|X|S|H|I|C|P):\s?(.*)$", l)
        if not m or cur is None:
            raise ValueError(f"{path}:{no}: bad line {l!r}")
        k, v = m.group(1), m.group(2).strip()
        if not v:
            raise ValueError(f"{path}:{no}: empty {k} line")
        if k in ("K", "L", "A", "M"):
            cur[k].append({"ko": v})
        elif k in PAIRED:
            base = cur[PAIRED[k]]
            if not base or "zh" in base[-1]:
                raise ValueError(f"{path}:{no}: {k} without a preceding {PAIRED[k]}")
            base[-1]["zh"] = v
        elif k in ("N", "X", "CZ"):
            cur[k].append(v)
        else:
            if k in cur:
                raise ValueError(f"{path}:{no}: duplicate {k}")
            cur[k] = v
    return items


def _plain(t):
    return re.sub(r"\s+", " ", t.replace("__", "")).strip()


def _strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, list):
        for x in obj:
            _strings(x, out)
    elif isinstance(obj, dict):
        for x in obj.values():
            _strings(x, out)
    return out


def _tok_spec(obj, tok):
    """Replace every string containing Hangul with {'t': tokens} so the page can render it with the dictionary."""
    if isinstance(obj, str):
        return {"t": tok(obj)} if re.search(r"[가-힣]", obj) else obj
    if isinstance(obj, list):
        return [_tok_spec(x, tok) for x in obj]
    if isinstance(obj, dict):
        return {k: _tok_spec(v, tok) for k, v in obj.items()}
    return obj


def check_quotes(where, lines, source_text, problems):
    src = _plain(source_text)
    for qt in re.findall(r"「([^」]*[가-힣][^」]*)」", " ".join(lines)):
        pos, ok = 0, True
        for seg in [x for x in (_plain(y) for y in qt.split("…")) if x]:
            i = src.find(seg, pos)
            if i < 0:
                ok = False
                break
            pos = i + len(seg)
        if not ok:
            problems.append(f"{where}: quote not in text: {qt}")


def build_write(tok, src_dir, out_dir, problems):
    wd = os.path.join(src_dir, "write")
    guide = {}
    for g in parse_wr(os.path.join(wd, "guide.wr")):
        guide[g["id"]] = {"h": g.get("H", ""), "p": g.get("P", ""), "n": g["N"]}
    items = []
    for t in (51, 52, 53, 54):
        for it in parse_wr(os.path.join(wd, f"{t}.wr")):
            where = f"write {it['id']}"
            if not it["id"].startswith(f"{t}-"):
                problems.append(f"{where}: id must start with {t}-")
            for k in ("K", "L", "A", "M"):
                for x in it[k]:
                    if "zh" not in x:
                        problems.append(f"{where}: {k} without {k}Z: {x['ko'][:30]}")
            ins, ins_zh = it.get("I"), it.get("IZ")
            if not ins:
                ins, ins_zh = DEFAULT_INS.get(t, (None, None))
            if not ins or not ins_zh:
                problems.append(f"{where}: missing I/IZ")
            for k in ("S", "H", "HZ"):
                if not it.get(k):
                    problems.append(f"{where}: missing {k}")
            spec = None
            src_strings = [x["ko"] for x in it["K"] + it["L"] + it["M"]] + [ins or ""]
            for a in it["A"]:
                src_strings += [v.strip() for v in a["ko"].split(" | ")]
            if it.get("C"):
                try:
                    spec = json.loads(it["C"])
                except ValueError as e:
                    problems.append(f"{where}: chart JSON: {e}")
                    spec = None
                if spec is not None:
                    src_strings += _strings(spec, [])
            if t in (51, 52):
                if len(it["A"]) != 2:
                    problems.append(f"{where}: needs exactly 2 A lines, has {len(it['A'])}")
                body = " ".join(x["ko"] for x in it["K"])
                for mk in "㉠㉡":
                    if f"({mk})" not in body:
                        problems.append(f"{where}: passage lacks ({mk})")
            if t == 53 and spec is None:
                problems.append(f"{where}: 53 needs a chart (C:)")
            if t == 54 and len(it["L"]) < 2:
                problems.append(f"{where}: 54 needs at least 2 L bullet lines")
            count = sum(len(x["ko"]) for x in it["M"])
            if t in LENGTH:
                lo, hi = LENGTH[t]
                if not (lo <= count <= hi):
                    problems.append(f"{where}: model answer is {count} characters, needs {lo}-{hi}")
            if t in (51, 52) and it["M"]:
                problems.append(f"{where}: 51/52 use A lines, not M")
            for x in it["X"]:
                if " | " not in x:
                    problems.append(f"{where}: X needs 'ko | zh': {x}")
            if not it["N"]:
                problems.append(f"{where}: no notes (N:)")
            check_quotes(where, it["N"], " ".join(src_strings), problems)
            K = []
            for x in it["K"]:
                hd = x["ko"].startswith("# ")
                ko = x["ko"][2:] if hd else x["ko"]
                o = {"t": tok(ko), "z": x.get("zh", "")}
                if hd:
                    o["hd"] = 1
                K.append(o)
            out = {
                "id": it["id"], "type": t, "src": it.get("S", ""), "h": it.get("H", ""), "hz": it.get("HZ", ""),
                "ins": tok(ins) if ins else [], "insZh": ins_zh or "",
                "k": K,
                "l": [{"t": tok(x["ko"]), "z": x.get("zh", "")} for x in it["L"]],
                "a": [{"v": [v.strip() for v in x["ko"].split(" | ")], "t": tok(x["ko"].split(" | ")[0].strip()), "z": x.get("zh", "")} for x in it["A"]],
                "m": [{"t": tok(x["ko"]), "z": x.get("zh", ""), "ko": x["ko"]} for x in it["M"]],
                "n": it["N"], "x": [x.split(" | ", 1) for x in it["X"]], "len": count,
            }
            if spec is not None:
                out["chart"] = _tok_spec(spec, tok)
                out["cz"] = it["CZ"]
                if not it["CZ"]:
                    problems.append(f"{where}: chart without CZ")
            items.append(out)
    ids = [x["id"] for x in items]
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        problems.append(f"write: duplicate ids {sorted(dup)}")

    json.dump({"guide": guide, "items": items},
              open(os.path.join(out_dir, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return len(items)
