"""참조 연결 (4단계, tree.py가 부른다).

link_citations: 본문 노드의 "별표N"·"유첨N" 인용을 절 노드에 잇고 노드의 cites에 적는다.
extract_refs: 조·항·호·목 참조와 별표·유첨 인용을 한 형식으로 모은다 → secure/tree/refs.jsonl (형식은 docs/refs_schema.md).
  "제N조" / "제N-M조" / "제N조의K" (+ 괄호 조 제목) 뒤에 "제N항", "제N호", "가목"이 이어질 수 있다.
  "같은 조", "이 조", "동조", "본조" (항·호도 같음)는 참조가 나온 노드 기준. 앞 참조와 및·,·부터 등으로만 떨어진 참조는
  앞 참조의 조 (항)를 이어받는다 ("제3조제1항 및 제2항"의 제2항은 제3조의 항).
  조는 같은 약관 (contract)에서 먼저 찾고, 없으면 다른 약관에서 같은 번호 조 (괄호 제목이 있으면 제목도 같은 조)가
  하나뿐일 때 다른 약관 참조로 잇는다. 「…법」·같은 법 등 법령 인용은 대상 없이 기록만 한다.
"""

import re
from collections import defaultdict

from config import profile

HANGUL_ORDER = "가나다라마바사아자차카타파하"
REF_RE = re.compile(
    r"(?:(?P<self>같은|이|동|본)\s*(?P<self_lv>조|항|호)\s*)?"
    r"(?:제\s*(?P<jo>\d+)\s*(?:-\s*(?P<jo2>\d+)\s*)?조(?:\s*의\s*(?P<jo3>\d+))?(?:\s*[(\[](?P<title>[^()\[\]]{1,40})[)\]])?)?"
    r"(?:\s*제\s*(?P<hang>\d+)\s*항)?"
    r"(?:\s*제\s*(?P<ho>\d+)\s*호)?"
    r"(?:\s*(?P<mok>[가나다라마바사아자차카타파하])\s*목)?")
REF_AMOUNT = re.compile(r"\s*[원억만]")
REF_PARTICLES = ("에서", "으로", "부터", "까지", "에도", "의", "에", "을", "를", "은", "는", "와", "과", "로", "및", "도", "만")
REF_CONNECT = re.compile(r"\s*(?:,|및|또는|내지|부터|와|과|·|ㆍ|~|∼|-|이나|나)?\s*")
REF_WINDOW = 40  # 조 참조 앞에서 법령·다른 약관 이름을 찾는 글자 수 (법령 이름 + 공백 수준)


# ---------------------------------------------------------------- 별표·유첨 인용

def annex_index(nodes: list[dict]) -> tuple[list[dict], re.Pattern | None]:
    """라벨이 있는 절 (별표·유첨)과 인용 정규식 (라벨 종류 + 번호, 긴 라벨부터)."""
    secs = [n for n in nodes if n["type"] == "section" and n.get("label_kind")]
    kinds = sorted({n["label_kind"] for n in secs}, key=len, reverse=True)
    rx = re.compile("(" + "|".join(r"\s*".join(map(re.escape, k)) for k in kinds) + r")\s*(\d+)?") if kinds else None
    return secs, rx


def annex_hits(secs: list[dict], m: re.Match, contract_id: str | None) -> tuple[str, list[dict]]:
    """인용 하나의 (라벨, 대상 후보). 같은 계약의 같은 라벨 절, 없으면 계약 밖 절 (유첨 등).
    번호 없는 "별표"는 후보가 하나일 때만."""
    kind, num = re.sub(r"\s", "", m.group(1)), int(m.group(2)) if m.group(2) else None
    same = [s for s in secs if s["label_kind"] == kind and s["label_number"] == num]
    hit = [s for s in same if s["contract_id"] == contract_id] or [s for s in same if s["contract_id"] is None]
    if num is None and len(hit) > 1:
        hit = []
    return f"{kind}{num if num is not None else ''}", hit


def link_citations(nodes: list[dict], byid: dict) -> None:
    """본문 노드 글자의 "별표N" (라벨 종류 + 번호) 인용을 같은 계약의 같은 라벨 절에 잇는다. 같은 계약에 없으면 다른 구역
    (유첨 등) 중 계약 밖 절에서 찾는다. 번호 없는 "별표"는 그 계약에 번호 없는 절이 하나뿐일 때만 잇는다."""
    secs, rx = annex_index(nodes)
    if rx is None:
        return
    for n in nodes:
        if n["type"] in ("zone", "contract", "section"):
            continue
        cites = []
        for m in rx.finditer((n["title"] or "") + " " + n["text"]):
            label, hit = annex_hits(secs, m, n["contract_id"])
            cites.append({"label": label, "target": hit[0]["id"] if len(hit) == 1 else None, "candidates": len(hit)})
        if cites:
            n["cites"] = cites


# ---------------------------------------------------------------- 조·항·호·목 참조

def _ref_scope(before: str, contract_title: str | None) -> str:
    """조 참조 바로 앞 글자로 범위를 정한다: internal / law / other_contract."""
    ref = profile()["references"]
    tail = before[-REF_WINDOW:]
    m = re.search(r"「([^「」]*)」\s*(?:의\s*)?$", tail)
    if m:
        name = re.sub(r"\s", "", m.group(1))
        if name.endswith(tuple(ref["contract_name_suffixes"])):
            return "internal" if contract_title and name in re.sub(r"\s", "", contract_title) else "other_contract"
        return "law" if name.endswith(tuple(ref["law_suffixes"])) else "other_contract"
    if re.search(r"(?:" + "|".join(map(re.escape, ref["other_contract_words"])) + r")\s*(?:약관\s*)?(?:의\s*)?$", tail):
        return "other_contract"
    if re.search(r"(?:같은|동)\s*법(?:\s*시행령|\s*시행규칙)?\s*(?:의\s*)?$", tail) or \
            re.search(r"[가-힣](?:" + "|".join(map(re.escape, ref["law_suffixes"])) + r")\s*(?:의\s*)?$", tail):
        return "law"
    return "internal"


def _paren_title(title: str | None) -> str | None:
    """조 머리글의 괄호 안 제목 (공백 제거). 머리글은 [제목], 본문 참조는 (제목)으로 적혀 둘 다 본다."""
    m = re.search(r"[(\[]([^()\[\]]*)[)\]]", title or "")
    return re.sub(r"\s", "", m.group(1)) if m else None


def _ref_self_ok(text: str, m: re.Match) -> bool:
    """"이 조", "같은 항" 뒤가 한글이면 조사일 때만 참조 ("이 조건", "이 항목"은 아님)."""
    rest = text[m.end("self_lv"):]
    return not rest or not ("가" <= rest[0] <= "힣") or rest.startswith(REF_PARTICLES)


def _ref_sources(nodes, byid, tables, blocks, figures, att) -> list[tuple]:
    """참조를 찾을 글자: (from_kind, from_id, row, 기준 노드, 글자, 별표 인용용 글자).
    노드 글자 (제목 줄 제외), 박스 블록, 표 행 (칸을 " | "로 이음)·표 주석, 예시 그림 주석. 박스·표·그림은 붙은 노드가 기준."""
    host = {(a["kind"], a["id"]): a["node_id"] for a in att}
    sources = []
    for n in nodes:
        if n["type"] not in ("zone", "contract", "section"):
            sources.append(("node", n["id"], None, n, n["text"], (n["title"] or "") + " " + n["text"]))
    for b in blocks:
        sources.append(("box", b["block_id"], None, byid.get(host.get(("box", b["block_id"]))), b["text"], b["text"]))
    for t in tables:
        hn = byid.get(host.get(("table", t["table_id"])))
        for i, r in enumerate(t["rows"]):
            s = " | ".join(c for c in r if c)
            sources.append(("table_row", t["table_id"], i, hn, s, s))
        for i, s in enumerate(t["notes"]):
            sources.append(("table_note", t["table_id"], i, hn, s, s))
    for f in figures:
        for i, s in enumerate(f["notes"]):
            sources.append(("figure_note", f["id"], i, byid.get(host.get(("figure", f["id"]))), s, s))
    return sources


def _find_article(g: dict, scope: str, con: dict | None, arts_by_contract: dict) -> tuple:
    """적힌 조 번호의 대상 조. (조 노드, 범위, 못 찾은 이유, 다른 약관 후보 수).
    같은 약관에서 먼저, 없으면 다른 약관에서 같은 번호 조 (괄호 제목이 있으면 제목도 같은 조)가 하나뿐일 때."""
    number = [int(g["jo"]), int(g["jo2"] or 0), int(g["jo3"] or 0)]
    art = None
    if scope == "internal" and con:
        art = next((a for a in arts_by_contract.get(con["id"], []) if a["number"] == number), None)
    if art is not None or scope not in ("internal", "other_contract"):
        return art, scope, None, 0
    cands = [a for k, v in arts_by_contract.items() if k != (con or {}).get("id") for a in v if a["number"] == number]
    if g["title"]:
        cands = [a for a in cands if _paren_title(a["title"]) == re.sub(r"\s", "", g["title"])] or cands
    if len(cands) == 1:
        return cands[0], "other_contract", None, 1
    scope = "other_contract" if cands or scope == "other_contract" else scope
    reason = "ambiguous_other_contract" if len(cands) > 1 else "not_found" if con else "no_contract_context"
    return None, scope, reason, len(cands)


def extract_refs(nodes: list[dict], byid: dict, tables: list[dict], blocks: list[dict], figures: list[dict],
                 att: list[dict]) -> list[dict]:
    """조·항·호·목 참조와 별표·유첨 인용을 한 형식으로 모은다 (노드는 바꾸지 않는다). 형식은 docs/refs_schema.md.
    별표·유첨 인용은 link_citations와 같은 규칙 (노드 출처는 노드의 cites와 같은 결과)."""
    arts_by_contract = defaultdict(list)
    for n in nodes:
        if n["type"] == "article":
            arts_by_contract[n["contract_id"]].append(n)
    secs, annex_rx = annex_index(nodes)

    def item_child(parent, marker, number):
        return next((byid[k] for k in parent["children"]
                     if byid[k].get("marker") == marker and byid[k].get("number") == number), None) if parent else None

    def hang_of(art, number):
        """조의 항: 조 바로 아래 ①부터, 없으면 조 안 어디든 그 번호 ①이 하나뿐일 때 (▶ 안내 줄 아래에 항이 있는 조)."""
        if art is None:
            return None
        direct = item_child(art, "circled", number)
        if direct is not None:
            return direct
        hits, todo = [], list(art["children"])
        while todo:
            x = byid[todo.pop()]
            if x.get("marker") == "circled" and x.get("number") == number:
                hits.append(x)
            todo += x["children"]
        return hits[0] if len(hits) == 1 else None

    def up(n, pred):
        while n is not None and not pred(n):
            n = byid.get(n["parent_id"])
        return n

    refs = []
    for fk, fid, row, cn, text, annex_text in _ref_sources(nodes, byid, tables, blocks, figures, att):
        con = byid.get(cn["contract_id"]) if cn and cn["contract_id"] else None
        here_art = byid.get(cn["article_id"]) if cn and cn["article_id"] else None
        here_hang = up(cn, lambda x: x.get("marker") == "circled" and x["article_id"] == (here_art or {}).get("id")) if here_art else None
        here_ho = up(cn, lambda x: x.get("marker") == "num_dot") if here_art else None
        base = {"from": {"kind": fk, "id": fid, "row": row, "node_id": cn["id"] if cn else None},
                "contract_id": con["id"] if con else None}
        prev = None  # 앞 참조: (끝 위치, 범위, 조 노드, 조 번호, 항 노드, 조를 적었거나 이어받았는지)
        for m in REF_RE.finditer(text):
            g = m.groupdict()
            self_lv = g["self_lv"] if g["self"] and _ref_self_ok(text, m) else None
            if not (self_lv or g["jo"] or g["hang"] or g["ho"]) or (g["mok"] and not (g["ho"] or self_lv == "호")):
                continue
            if g["jo"]:
                jo_end = text.index("조", m.end("jo2") if g["jo2"] else m.end("jo")) + 1
                if REF_AMOUNT.match(text, jo_end):  # "…조원" 같은 금액
                    continue
            start = m.start("self") if self_lv else m.start()
            start += len(text[start:m.end()]) - len(text[start:m.end()].lstrip())
            linked = prev is not None and REF_CONNECT.fullmatch(text[prev[0]:start]) is not None
            hang, ho, reason, elsewhere = None, None, None, 0
            # 조: 적혀 있으면 찾고, 이어진 참조면 앞 참조의 조, 아니면 나온 노드의 조
            if g["jo"]:
                scope = _ref_scope(text[:start], con["title"] if con else None)
                number = [int(g["jo"]), int(g["jo2"] or 0), int(g["jo3"] or 0)]
                art, scope, reason, elsewhere = _find_article(g, scope, con, arts_by_contract)
            elif linked and prev[5] and not self_lv:
                scope, art, number = prev[1], prev[2], prev[3]
                reason = None if art is not None or scope == "law" else "not_found"
            else:
                scope, art = "internal", here_art
                number = here_art["number"] if here_art else None
                if art is None:
                    reason = "no_article_context"
            if scope == "law":
                reason = "law"
            # 항·호·목
            if g["hang"]:
                hang = hang_of(art, int(g["hang"]))
            elif g["ho"] and linked and not g["jo"] and prev[4] is not None:
                hang = prev[4]
            elif self_lv in ("항", "호") or (g["ho"] and not g["jo"]):
                hang = here_hang
            if g["ho"]:
                ho = item_child(hang if hang is not None else (art if not g["hang"] else None), "num_dot", int(g["ho"]))
            elif self_lv == "호":
                ho = here_ho
            mok = item_child(ho, "hangul_dot", HANGUL_ORDER.index(g["mok"]) + 1) if g["mok"] else None
            level = "mok" if g["mok"] else "ho" if (g["ho"] or self_lv == "호") else "hang" if (g["hang"] or self_lv == "항") else "article"
            kind = ("this_" + level) if self_lv and not (g["hang"] or g["ho"] or g["jo"]) else level
            to = {"article": art, "hang": hang, "ho": ho, "mok": mok}[level] if scope != "law" else None
            if scope != "law" and to is None and reason is None:
                reason = "no_target_node"
            title_match = _paren_title(art["title"]) == re.sub(r"\s", "", g["title"]) if g["title"] and art is not None else None
            refs.append({**base, "kind": kind, "scope": scope, "text": text[start:m.end()].strip(), "start": start, "end": m.end(),
                         "path": {"article": number, "hang": int(g["hang"]) if g["hang"] else None,
                                  "ho": int(g["ho"]) if g["ho"] else None, "mok": g["mok"]},
                         "relative": not g["jo"], "linked_to_previous": linked and not g["jo"],
                         "to": to["id"] if to else None, "to_type": to["type"] if to else None,
                         "resolved": to is not None, "reason": None if to is not None else reason,
                         "candidates_elsewhere": elsewhere, "title_given": bool(g["title"]), "title_match": title_match})
            prev = (m.end(), scope, art, number, hang, bool(g["jo"]) or (linked and prev[5] and not self_lv))
        if annex_rx:
            for m in annex_rx.finditer(annex_text):
                label, hit = annex_hits(secs, m, (cn or {}).get("contract_id"))
                to = hit[0] if len(hit) == 1 else None
                refs.append({**base, "kind": "annex", "scope": "internal", "text": m.group(0).strip(), "start": m.start(), "end": m.end(),
                             "path": {"label": label}, "relative": False,
                             "linked_to_previous": False, "to": to["id"] if to else None, "to_type": "section" if to else None,
                             "resolved": to is not None, "reason": None if to else "no_target_node",
                             "candidates_elsewhere": 0, "title_given": False, "title_match": None})
    for i, r in enumerate(refs):
        r["ref_id"] = f"R{i:05d}"
    return refs
