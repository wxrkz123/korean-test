"""Build data/*.json from source/: exam text (tpk), PDF margin glossary, translations, grammar patterns.
Usage: pip install kiwipiepy && python3 tools/build.py"""
import re, json, sys, os, glob, collections
sys.path.insert(0, os.path.dirname(__file__))
from tpk import parse_tpk
from kiwipiepy import Kiwi
import grammar as GR
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data")
os.makedirs(OUT, exist_ok=True)
kiwi = Kiwi()

# ---------- dictionary ----------
DICT = {}      # lemma -> zh
gloss = json.load(open(os.path.join(SRC, "gloss.json"), encoding="utf-8"))
PHRASES_RAW = []
for k, vs in gloss.items():
    zh = "；".join(vs)
    if k.startswith("-"): continue
    if "·" in k:
        ks = [x.strip() for x in k.split("·")]; zs = [x.strip() for x in zh.split("·")]
        if len(ks) == len(zs):
            for a, b in zip(ks, zs): DICT.setdefault(a, b)
        continue
    if " " in k:
        PHRASES_RAW.append((k, zh)); continue
    DICT[k] = zh
for f in [os.path.join(SRC, "translations.tsv")]:
    for line in open(f, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line: continue
        k, v = line.split("\t")
        DICT.setdefault(k, v)
# phrases also usable as single dictionary entries when written without spaces
VERB_KEYS = collections.defaultdict(list)
for k in DICT:
    if k.endswith("다") and len(k) >= 3: VERB_KEYS[k[0]].append(k)

def jamo(s):
    out = []
    for ch in s:
        c = ord(ch)
        if 0xAC00 <= c <= 0xD7A3:
            c -= 0xAC00; out += [chr(0x1100 + c // 588), chr(0x1161 + (c % 588) // 28)]
            if c % 28: out.append(chr(0x11A7 + c % 28))
        else: out.append(ch)
    return "".join(out)

NOUNISH = {"NNG","NNP","NR","NP","NNB","XR","XPN"}
VERBISH = {"VV","VA","VX","VCN"}
ADVISH = {"MAG","MAJ","MM","IC"}
def bt(t): return t.split("-")[0]

def resolve(morphs, surface):
    """morphs: list of (form, tag, start_in_eojeol). returns list of lemma strings"""
    words = []; i = 0; n = len(morphs)
    while i < n:
        f, t, st = morphs[i]
        if t in NOUNISH:
            r = i
            while r + 1 < n and (morphs[r+1][1] in NOUNISH - {"NNB"} or morphs[r+1][1] == "XSN"): r += 1
            best = None
            for k in range(r, i - 1, -1):
                cand = "".join(m[0] for m in morphs[i:k+1])
                if k + 1 < n and morphs[k+1][1] in ("XSV","XSA"):
                    c2 = cand + morphs[k+1][0] + "다"
                    if c2 in DICT: best = (c2, k + 1); break
                if cand in DICT: best = (cand, k); break
            if best:
                words.append(best[0]); i = best[1] + 1; continue
            if t == "XPN": i += 1; continue
            words.append(f); i += 1; continue
        if t in VERBISH:
            stem = f; lemma = f + "다"
            rest = jamo(surface[st:])
            best = None
            for key in VERB_KEYS.get(stem[0], []):
                ks = key[:-1]
                if len(ks) > len(stem) and rest.startswith(jamo(ks)) and (best is None or len(jamo(ks)) > len(jamo(best[:-1]))):
                    best = key
            if best:
                words.append(best); end = st + len(best) - 1
                i += 1
                while i < n and morphs[i][2] < end and morphs[i][1] not in NOUNISH: i += 1
                continue
            words.append(lemma); i += 1; continue
        if t in ADVISH:
            if i + 1 < n and morphs[i+1][1] in ("VV","XSV","XSA","VA") and (f + morphs[i+1][0] + "다") in DICT:
                words.append(f + morphs[i+1][0] + "다"); i += 2; continue
            words.append(f); i += 1; continue
        i += 1
    # dedupe keep order
    seen = set(); out = []
    for w in words:
        if w not in seen: seen.add(w); out.append(w)
    return out

MARKER = re.compile(r"^[\(（]?(가|나|다|라|중략|㉠|㉡|㉢|㉣|____)[\)）]?[.,]?$")
def normalize(text):
    text = re.sub(r"\(\s*([㉠㉡㉢㉣])\s*\)", r"(\1)", text)
    text = re.sub(r"\(\s{2,}\)", "(____)", text)
    text = re.sub(r"\(\s*\)", "(____)", text)
    # underline ranges
    ranges = []; out = ""; pos = 0
    for m in re.finditer(r"__(.+?)__", text):
        out += text[pos:m.start()]; s = len(out); out += m.group(1); ranges.append((s, len(out))); pos = m.end()
    out += text[pos:]
    return out, ranges

COMPILED = GR.compile_patterns()
W_IDX = {}; W_LIST = []
def widx(lemma):
    if lemma not in W_IDX:
        W_IDX[lemma] = len(W_LIST); W_LIST.append([lemma, DICT.get(lemma, "")])
    return W_IDX[lemma]
A_IDX = {}; A_LIST = []
def aidx(rec):
    if rec not in A_IDX:
        A_IDX[rec] = len(A_LIST); A_LIST.append([list(rec[0]), list(rec[1]), list(rec[2])])
    return A_IDX[rec]
P_LIST = []; P_PATTERNS = []
UNKNOWN = collections.Counter(); UNKNOWN_EX = {}

def analyze_eojeols(text):
    toks = kiwi.tokenize(text)
    ejs = [{"s": m.group(0), "start": m.start(), "end": m.end(), "morphs": []} for m in re.finditer(r"\S+", text)]
    j = 0
    for tk in toks:
        while j < len(ejs) and tk.start >= ejs[j]["end"]: j += 1
        if j < len(ejs): ejs[j]["morphs"].append((tk.form, bt(tk.tag), tk.start - ejs[j]["start"]))
    return ejs

def build_phrases():
    for k, zh in PHRASES_RAW:
        ejs = analyze_eojeols(k)
        pat = []
        for ej in ejs:
            ws = resolve(ej["morphs"], ej["s"])
            if not ws: pat = None; break
            pat.append(ws[0])
        if not pat or len(pat) < 2: 
            continue
        P_PATTERNS.append((pat, len(P_LIST))); P_LIST.append([k, zh])
build_phrases()

def tokenize_para(raw):
    text, ranges = normalize(raw)
    ejs = analyze_eojeols(text)
    words_per = []
    for ej in ejs:
        if MARKER.match(ej["s"]) or not re.search(r"[가-힣]", ej["s"]):
            words_per.append(None); continue
        ws = resolve(ej["morphs"], ej["s"])
        words_per.append(ws)
        for w in ws:
            if w not in DICT:
                UNKNOWN[w] += 1; UNKNOWN_EX.setdefault(w, ej["s"])
    # grammar
    flat = []
    for ei, ej in enumerate(ejs):
        for f, t, st in ej["morphs"]: flat.append((f, t, ei))
    gm = []
    for pi, eis in GR.match_all(flat, COMPILED):
        gm.append((pi, eis))
    # prune contained matches (by eojeol span & longer pattern)
    starts = {}
    # recompute with morph spans for containment
    spans = []
    for pi, (ms, label, zh) in enumerate(COMPILED):
        L = len(ms)
        for i in range(len(flat) - L + 1):
            ok = all((fs is None or flat[i+k][0] in fs) and any(flat[i+k][1] == x for x in ts) for k, (fs, ts) in enumerate(ms))
            if ok: spans.append((i, i + L, pi))
    keep = []
    for a in spans:
        dominated = any((b[0] <= a[0] and a[1] <= b[1] and (b[1]-b[0]) > (a[1]-a[0])) for b in spans)
        if not dominated: keep.append(a)
    gram_per = [set() for _ in ejs]
    for s, e, pi in keep:
        for k in range(s, e): gram_per[flat[k][2]].add(pi)
    # phrases
    phr_per = [set() for _ in ejs]
    for pat, pidx in P_PATTERNS:
        L = len(pat)
        for i in range(len(ejs) - L + 1):
            if all(words_per[i+k] and pat[k] in words_per[i+k] for k in range(L)):
                for k in range(L): phr_per[i+k].add(pidx)
    out = []
    for ei, ej in enumerate(ejs):
        u = any(not (ej["end"] <= s or ej["start"] >= e) for s, e in ranges)
        if words_per[ei] is None:
            tok = [ej["s"], -1]
        else:
            rec = (tuple(widx(w) for w in words_per[ei]), tuple(sorted(gram_per[ei])), tuple(sorted(phr_per[ei])))
            tok = [ej["s"], aidx(rec)]
        if u: tok.append(1)
        out.append(tok)
    return out

ORDER = [35, 37, 41, 47, 52, 64, 83, 91, 96, 102]
TITLES = {n: f"第{n}回" for n in ORDER}

# ---------- Chinese translations and explanations (source/zh) ----------
def _norm_key(t):
    return re.sub(r"\(\s*\)", "()", re.sub(r"\s+", " ", t.strip()))
COMMON_ZH = {}
_cp = os.path.join(SRC, "zh", "common.tsv")
if os.path.exists(_cp):
    for line in open(_cp, encoding="utf-8"):
        if "\t" in line:
            k, v = line.rstrip("\n").split("\t"); COMMON_ZH[_norm_key(k)] = v
def parse_zh(path):
    """=== a-b / P: passage paragraph ; ## n / T: text paragraph, B: box, S: poster line, O: a | b | c | d, E: explanation, Q: prompt"""
    groups, qs = {}, {}; cur = None
    for raw in open(path, encoding="utf-8"):
        l = raw.rstrip("\n").strip()
        if not l or l.startswith("#!"): continue
        m = re.match(r"^=== (\d+)-(\d+)$", l)
        if m: cur = groups.setdefault((int(m.group(1)), int(m.group(2))), {"P": []}); continue
        m = re.match(r"^## (\d+)$", l)
        if m: cur = qs.setdefault(int(m.group(1)), {"T": [], "S": []}); continue
        m = re.match(r"^([PTBSOEQ]):\s?(.*)$", l)
        if not m or cur is None: raise ValueError(f"{path}: bad line {l!r}")
        k, v = m.group(1), m.group(2).strip()
        if not v: raise ValueError(f"{path}: empty {k} line")
        if k in ("P", "T", "S"): cur.setdefault(k, []).append(v)
        elif k == "O": cur["O"] = [x.strip() for x in v.split(" | ")]
        else: cur[k] = v
    return groups, qs

def parse_exp(path):
    """Detailed explanations: '## n' followed by lines (思路：/关键句：/①○ /②× /词汇：...)."""
    out = {}; cur = None
    for raw in open(path, encoding="utf-8"):
        l = raw.rstrip("\n").strip()
        if not l or l.startswith("#!"): continue
        m = re.match(r"^## (\d+)$", l)
        if m: cur = out.setdefault(int(m.group(1)), []); continue
        if cur is None: raise ValueError(f"{path}: line before first ## : {l!r}")
        cur.append(l)
    return out

def _plain_ko(t):
    return re.sub(r"\s+", " ", t.replace("__", "")).strip()
YEARS = {35: "2014", 37: "2014", 41: "2015", 47: "2016", 52: "2017", 64: "2019", 83: "2022", 91: "2023", 96: "2024", 102: "2025"}
index = []
ZH_PROBLEMS = []; ZH_DONE = []
for n in ORDER:
    ex = parse_tpk(os.path.join(SRC, "tpk", f"{n}.tpk"))
    _zp = os.path.join(SRC, "zh", f"{n}.zh")
    ZH = parse_zh(_zp) if os.path.exists(_zp) else None
    _ep = os.path.join(SRC, "zh", f"{n}.exp")
    EXP = parse_exp(_ep) if os.path.exists(_ep) else {}
    if ZH is not None: ZH_DONE.append(n)
    groups = []
    for g in ex["groups"]:
        und = g["passage"] == ["[undisclosed]"]
        G = {"r": g["range"], "ins": tokenize_para(g["instruction"]), "pas": [] if und else [tokenize_para(p) for p in g["passage"]], "und": und, "qs": []}
        if ZH is not None:
            G["insZh"] = COMMON_ZH.get(_norm_key(g["instruction"]))
            if not G["insZh"]: ZH_PROBLEMS.append(f"{n} instruction {g['instruction']}")
            zg = ZH[0].get(tuple(g["range"]), {"P": []})
            if not und:
                if len(zg["P"]) != len(g["passage"]): ZH_PROBLEMS.append(f"{n} group {g['range']}: {len(zg['P'])} P lines for {len(g['passage'])} paragraphs")
                G["pasZh"] = zg["P"]
        for q in g["questions"]:
            Q = {"n": q["n"],
                 "prompt": tokenize_para(q["prompt"]) if q["prompt"] else None,
                 "box": tokenize_para(q["box"]) if q["box"] else None,
                 "poster": [tokenize_para(x) for x in q["poster"]],
                 "img": f"img/{q['img']}.png" if q["img"] else None,
                 "text": [tokenize_para(x) for x in q["text"]],
                 "opts": [tokenize_para(x) for x in q["options"]],
                 "ans": q["answer"]}
            if ZH is not None:
                z = ZH[1].get(q["n"])
                if z is None: ZH_PROBLEMS.append(f"{n} Q{q['n']}: missing")
                else:
                    zq = {}
                    if q["prompt"]:
                        zq["p"] = z.get("Q") or COMMON_ZH.get(_norm_key(q["prompt"]))
                        if not zq["p"]: ZH_PROBLEMS.append(f"{n} Q{q['n']}: prompt {q['prompt']}")
                    if len(z["T"]) != len(q["text"]): ZH_PROBLEMS.append(f"{n} Q{q['n']}: {len(z['T'])} T for {len(q['text'])} text")
                    zq["t"] = z["T"]
                    if q["box"]:
                        if not z.get("B"): ZH_PROBLEMS.append(f"{n} Q{q['n']}: missing B")
                        zq["b"] = z.get("B")
                    if q["poster"]:
                        if len(z["S"]) != len(q["poster"]): ZH_PROBLEMS.append(f"{n} Q{q['n']}: {len(z['S'])} S for {len(q['poster'])} poster lines")
                        zq["s"] = z["S"]
                    if len(z.get("O", [])) != 4: ZH_PROBLEMS.append(f"{n} Q{q['n']}: O has {len(z.get('O', []))}")
                    zq["o"] = z.get("O", [])
                    Q["zh"] = zq
                    if z.get("E"): Q["exp"] = z["E"]
                    elif q["answer"]: ZH_PROBLEMS.append(f"{n} Q{q['n']}: missing E")
            if q["n"] in EXP:
                lines = EXP[q["n"]]
                opts = [l for l in lines if re.match(r"^[①②③④][○×]", l)]
                good = [l for l in opts if l[1] == "○"]
                if len(opts) != 4: ZH_PROBLEMS.append(f"{n} Q{q['n']} exp: {len(opts)} option lines")
                if len(good) != 1 or "①②③④".index(good[0][0]) + 1 != q["answer"]:
                    ZH_PROBLEMS.append(f"{n} Q{q['n']} exp: ○ option does not match answer {q['answer']}")
                src_ko = _plain_ko(" ".join(g["passage"] + q["text"] + q["options"] + q["poster"] + [q["box"] or "", q["prompt"] or ""]))
                for qt in re.findall(r"「([^」]*[가-힣][^」]*)」", " ".join(lines)):
                    pos = 0; ok = True
                    for seg in [x for x in (_plain_ko(y) for y in qt.split("…")) if x]:
                        i = src_ko.find(seg, pos)
                        if i < 0: ok = False; break
                        pos = i + len(seg)
                    if not ok: ZH_PROBLEMS.append(f"{n} Q{q['n']} exp: quote not in text: {qt}")
                Q["expD"] = lines
            elif EXP and q["answer"] and q["n"] >= 30:
                ZH_PROBLEMS.append(f"{n} Q{q['n']}: missing detailed explanation")
            G["qs"].append(Q)
        groups.append(G)
    json.dump({"id": n, "title": TITLES[n], "groups": groups}, open(f"{OUT}/e{n}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    answerable = sum(1 for g in ex["groups"] for q in g["questions"] if q["answer"])
    index.append({"id": n, "title": TITLES[n], "year": YEARS[n], "count": 50, "answerable": answerable, "zh": ZH is not None,
                  "skip": [q["n"] for g in ex["groups"] for q in g["questions"] if not q["answer"]]})
from writebuild import build_write
if os.path.isdir(os.path.join(SRC, "write")):
    print("write: items %d, drills %d, expressions %d" % build_write(tokenize_para, SRC, OUT, ZH_PROBLEMS))
G_LIST = [[label, zh] for (_, label, zh) in COMPILED]
json.dump({"W": W_LIST, "G": G_LIST, "P": P_LIST, "A": A_LIST}, open(f"{OUT}/dict.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
json.dump(index, open(f"{OUT}/index.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("W", len(W_LIST), "A", len(A_LIST), "P", len(P_LIST), "G", len(G_LIST))
print("translations:", ZH_DONE)
if ZH_PROBLEMS:
    print("TRANSLATION PROBLEMS:"); [print("  " + x) for x in ZH_PROBLEMS]; sys.exit(1)
print("unknown lemmas", len(UNKNOWN), sum(UNKNOWN.values()))
if UNKNOWN and os.environ.get("UNKNOWN_OUT"):
    with open(os.environ["UNKNOWN_OUT"], "w", encoding="utf-8") as fo:
        for w, c in UNKNOWN.items(): fo.write(f"{w}\t{UNKNOWN_EX[w]}\t{c}\n")
elif UNKNOWN: print(UNKNOWN.most_common(100))
