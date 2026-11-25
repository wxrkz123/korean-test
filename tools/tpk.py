import re
def parse_tpk(path):
    lines = open(path, encoding="utf-8").read().split("\n")
    exam = None; groups = []; g = None; q = None; mode = None; poster = None
    for raw in lines:
        l = raw.rstrip()
        if l.startswith("# exam"):
            exam = int(l.split()[2]); continue
        if mode == "passage":
            if l == "<<<": mode = None; continue
            g["passage"].append(l); continue
        if mode == "poster":
            if l == "[/poster]": mode = None; continue
            q["poster"].append(l); continue
        if l.startswith("=== "):
            a, b = l[4:].split("-")
            g = {"range": [int(a), int(b)], "instruction": None, "passage": [], "questions": []}
            groups.append(g); q = None; continue
        if l == ">>>": mode = "passage"; continue
        if l.startswith("## "):
            q = {"n": int(l[3:]), "prompt": None, "text": [], "box": None, "poster": [], "img": None, "options": [], "answer": None}
            g["questions"].append(q); continue
        if not l.strip(): continue
        if q is None:
            if g["instruction"] is None: g["instruction"] = l.strip()
            else: raise ValueError(f"{path}: stray line {l!r}")
            continue
        if l == "[poster]": mode = "poster"; continue
        if l.startswith("[img] "): q["img"] = l[6:].strip(); continue
        if l.startswith("[box] "): q["box"] = l[6:].strip(); continue
        if l.startswith("? "): q["prompt"] = l[2:].strip(); continue
        m = re.match(r"^([1-4])\) (.*)$", l)
        if m and not q["text"] or (m and len(q["options"]) > 0) or (m and int(m.group(1)) == len(q["options"]) + 1 and int(m.group(1)) == 1):
            if m:
                assert int(m.group(1)) == len(q["options"]) + 1, (path, q["n"], l)
                q["options"].append(m.group(2).strip()); continue
        m2 = re.match(r"^= (\d|\?)$", l)
        if m2:
            q["answer"] = None if m2.group(1) == "?" else int(m2.group(1)); continue
        q["text"].append(l.strip())
    qs = [q for g in groups for q in g["questions"]]
    assert [q["n"] for q in qs] == list(range(1, 51)), (path, [q["n"] for q in qs])
    for q in qs:
        assert len(q["options"]) == 4, (path, q["n"], q["options"])
    return {"exam": exam, "groups": groups}

def text_fields(ex):
    """yield (key, text) for every displayable Korean text"""
    for gi, g in enumerate(ex["groups"]):
        yield (f"g{gi}.instruction", g["instruction"])
        for pi, p in enumerate(g["passage"]): yield (f"g{gi}.passage.{pi}", p)
        for q in g["questions"]:
            n = q["n"]
            if q["prompt"]: yield (f"q{n}.prompt", q["prompt"])
            if q["box"]: yield (f"q{n}.box", q["box"])
            for i, t in enumerate(q["poster"]): yield (f"q{n}.poster.{i}", t)
            for i, t in enumerate(q["text"]): yield (f"q{n}.text.{i}", t)
            for i, t in enumerate(q["options"]): yield (f"q{n}.opt.{i}", t)
