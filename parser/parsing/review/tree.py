"""본문 트리 검증과 확인용 출력: 번호 흐름 검사 (check_tree, 기본 실행에서도 수치만 씀), 리포트 (results/parsing/tree_report.md),
구조 수치 (review/tree_structure.md), 사람 확인용 개요·조 전문·확인 그림 (secure/review/).

tree.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

from collections import Counter, defaultdict

from pdf_lines import md_table
from safeio import RESULTS, SECURE, result_path, review_write, secure_path, secure_review_write
from samples import RANDOM15


def check_tree(nodes: list[dict], byid: dict) -> dict[str, list]:
    """번호 흐름 검사: 계약 안 조 번호가 늘지 않음, 형제 항목 번호가 1씩 늘지 않음, 조 밖 내용."""
    res = defaultdict(list)
    # 청킹 단위: 보고서 모드 (제목 노드가 있음)는 가장 가까운 제목, 조문형은 조
    unit_key = "heading_id" if any(n["type"] == "heading" for n in nodes) else "article_id"
    for c in [n for n in nodes if n["type"] == "contract"]:
        arts = [n for n in nodes if n["type"] == "article" and n["contract_id"] == c["id"]]
        for a, b in zip(arts, arts[1:]):
            if tuple(b["number"]) <= tuple(a["number"]):
                res["article_not_increasing"].append(b["id"])
    for n in nodes:
        kids = [byid[k] for k in n["children"] if byid[k]["type"] == "item"]
        by_marker = defaultdict(list)
        for k in kids:
            by_marker[k["marker"]].append(k)
        for mk, ks in by_marker.items():
            nums = [k["number"] for k in ks]
            if nums and nums[0] not in (1, None):
                res["items_not_from_1"].append(ks[0]["id"])
            for a, b in zip(ks, ks[1:]):
                if a["number"] is not None and b["number"] is not None and b["number"] != a["number"] + 1:
                    res["item_number_jump"].append(b["id"])
        if len(by_marker) > 1:
            res["mixed_item_markers_siblings"].append(n["id"])
    for n in nodes:
        if n["type"] in ("contract", "pyeon", "gwan", "zone") and n["lines"]:
            res[f"text_directly_under_{n['type']}"].append(n["id"])
        for c in n.get("cites", []):
            if c["target"] is None:
                res["citation_unresolved"].append(n["id"])
        if n["type"] == "section" and not n.get("label"):
            res["section_without_label"].append(n["id"])
        if n["type"] in ("item", "note", "bold", "para") and n.get(unit_key) is None:
            res[f"content_outside_{unit_key[:-3]}"].append(n["id"])
    return res


def write_report(nodes, att, acc, checks, n_usable, gl) -> None:
    types = Counter(n["type"] for n in nodes)
    rows = [["포함 쪽 줄 (제외·쪽번호 아님)", n_usable], ["  트리 줄", acc["tree"]], ["  제목 띠 줄", acc["band"]],
            ["  표·박스 블록 영역 줄", acc["in_table_or_box"]], ["  표 아래 주석 줄", acc["table_note"]],
            ["  절 라벨 줄 (별표N 등)", acc["section_label"]],
            ["  예시 그림 아래 주석 줄", acc["figure_note"]],
            ["  합 = 포함 줄", acc["tree"] + acc["band"] + acc["in_table_or_box"] + acc["table_note"] + acc["section_label"]
             + acc["figure_note"]],
            ["트리 노드에 들어간 줄 (띠 제외)", acc["tree_lines_in_nodes"]]]
    rows += [[f"노드 {k}", v] for k, v in types.most_common()]
    art_depth = {n["id"]: n["depth"] for n in nodes if n["type"] == "article"}
    rows += [["항목 최대 깊이 (조 아래 단계 수)", max((n["depth"] - art_depth[n["article_id"]] for n in nodes if n["article_id"]), default=0)]]
    rows += [["예시 그림 (제외한 예시 상자 자리)", sum(len(n["figures"]) for n in nodes)]]
    rows += [["표·박스가 붙은 노드 종류", ", ".join(f"{k} {v}" for k, v in Counter(a["node_type"] for a in att).most_common())],
             ["  조 밖에 붙은 표·박스", sum(a["article_id"] is None for a in att)],
             ["용어집 소속 조항 채움", f"{sum(g['parent_article'] is not None for g in gl)} / {len(gl)}"],
             ["절 라벨 종류", ", ".join(f"{k} {v}" for k, v in Counter(str(n.get("label_kind")) for n in nodes if n["type"] == "section").most_common())],
             ["별표 등 인용", sum(len(n.get("cites", [])) for n in nodes)],
             ["  연결함", sum(c["target"] is not None for n in nodes for c in n.get("cites", []))]]
    rows += [[f"검사: {k}", len(v)] for k, v in sorted(checks.items())]
    parts = ["# 4단계 본문 트리 리포트 (수치만)", "", md_table(["항목", "값"], rows), ""]
    result_path(RESULTS / "parsing" / "tree_report.md").write_text("\n".join(parts), encoding="utf-8")


def write_structure(nodes, checks) -> None:
    """review/ (구조 수치만): 계약마다 쪽 범위, 편·절·관·조 수, 항목 수, 검사 걸린 수."""
    byc = defaultdict(Counter)
    flagged = {i for v in checks.values() for i in v}
    for n in nodes:
        if n["contract_id"]:
            byc[n["contract_id"]][n["type"]] += 1
            byc[n["contract_id"]]["flag"] += n["id"] in flagged
    rows = ["# 본문 트리 구조 (계약별 수치)", "", "| contract | 쪽 | 편 | 절 | 관 | 조 | 항목 | 주석 | 굵은 줄 | 검사 걸림 |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    pages = set()
    for n in nodes:
        if n["type"] != "contract":
            continue
        c = byc[n["id"]]
        end = max((m["page_end"] or 0) for m in nodes if m["contract_id"] == n["id"])
        if n["page_start"] in RANDOM15:
            continue
        pages.add(n["page_start"])
        rows.append(f"| {n['id']} | {n['page_start']}-{end} | {c['pyeon']} | {c['section']} | {c['gwan']} | {c['article']} | "
                    f"{c['item']} | {c['note']} | {c['bold']} | {c['flag']} |")
    review_write("tree_structure.md", rows[:200], "계약 (제목 띠)마다 편·관·조·항목 수와 번호 흐름 검사", pages)


def write_user_check(nodes, byid, checks, gl) -> None:
    """사람 확인용 (원문, secure/review): 목차 (구역·계약·편·절·관·조 제목)와 조 몇 개 전체, 검사 걸린 노드."""
    rows = ["# 본문 트리 목차 (사람 확인용)", "", "들여쓰기 = 단계. [별표N]은 약관 끝 별표 (라벨 없으면 [절]). 괄호 안은 쪽, 항목 수.", ""]
    for n in nodes:
        if n["type"] in ("zone", "contract", "pyeon", "section", "gwan", "article"):
            kids = sum(1 for k in n["children"] if byid[k]["type"] == "item")
            tag = {"section": f"[{n.get('label') or '절'}] ", "zone": "■ ", "contract": "◆ "}.get(n["type"], "")
            extra = f" (표 {len(n['tables'])}, 박스 {len(n['boxes'])})" if n["tables"] or n["boxes"] else ""
            rows.append(f"{'  ' * n['depth']}- {tag}{n['title'] or '(제목 없음)'} ({n['page_start']}, 항목 {kids}){extra}")
    secure_review_write("tree_outline.md", rows)

    def render(n, ind=0):
        out_ = []
        head = n["title"] or ""
        body = n["text"]
        label = {"note": "[주석] ", "bold": "[굵은 줄] ", "para": "[문단] "}.get(n["type"], "")
        out_.append(f"{'  ' * ind}- {label}{head}{' ' if head and body else ''}{body}")
        for t in n["tables"]:
            out_.append(f"{'  ' * (ind + 1)}- [표 {t}]")
        for b in n["boxes"]:
            out_.append(f"{'  ' * (ind + 1)}- [박스 {b}]")
        for k in n["children"]:
            out_ += render(byid[k], ind + 1)
        return out_

    arts = [n for n in nodes if n["type"] == "article" and n["page_start"] not in RANDOM15]
    pick, seenz = [], Counter()
    for a in arts:  # 구역마다 앞 조 2개 + 항목이 깊은 조 2개
        z = a["path"][0]
        if seenz[z] < 2:
            pick.append(a)
            seenz[z] += 1
    deep = sorted(arts, key=lambda a: -max((m["depth"] for m in nodes if m["article_id"] == a["id"]), default=0))[:2]
    pick += [a for a in deep if a not in pick]
    flagged = []
    for k, ids in sorted(checks.items()):
        for i in ids[:5]:
            n = byid[i]
            if n["page_start"] in RANDOM15:
                continue
            a = byid.get(n["article_id"]) if n["article_id"] else None
            flagged.append((k, n, a))
    rows = ["# 본문 트리 조 예시와 검사 걸린 노드 (사람 확인용)", ""]
    for a in pick:
        rows += [f"## {a['title']} (쪽 {a['page_start']}-{a['page_end']})", ""] + render(a) + [""]
    rows += ["## 검사 걸린 노드 (검사마다 앞 5개)", ""]
    for k, n, a in flagged:
        rows.append(f"- {k}: {n['type']} {n['id']} (쪽 {n['page_start']}), 조: {a['title'] if a else '-'}, 내용: "
                    f"{(n['title'] or '')} {n['text'][:80]}")
    secure_review_write("tree_articles.md", rows)


def write_spot_check(nodes, byid, checks, line_at: dict) -> int:
    """사람 확인용 (secure/review/tree_spots.md + tree_spots/*.png): 번호가 건너뛰거나 겹친 목록마다 형제 항목 첫 줄에 상자와 읽은 번호.
    파랑 = 목록의 부모 노드 첫 줄, 빨강 = 형제 항목 첫 줄 (옆 숫자 = 트리가 읽은 번호), 주황 = 검사에 걸린 항목."""
    from PIL import Image, ImageDraw, ImageFont

    from evalcore import pages_meta

    try:
        fnt = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        fnt = ImageFont.load_default()
    spots, seen = [], set()
    for i in checks.get("item_number_jump", []):
        n = byid[i]
        key = (n["parent_id"], n["marker"])
        if key in seen or n["page_start"] in RANDOM15:
            continue
        seen.add(key)
        spots.append(n)
    rows = ["# 번호 흐름 확인 (사람 확인용)", "",
            "쪽 그림: `secure/review/tree_spots/<번호>_p<쪽>.png`. 파랑 = 목록의 부모 (항·조 등) 첫 줄, 빨강 = 같은 목록 항목의 첫 줄",
            "(옆 숫자 = 트리가 읽은 번호), 주황 = 건너뛰거나 겹친 번호. PDF 쪽과 비교해 "
            "(1) PDF도 그 번호 순서인지, (2) 트리가 다른 목록 항목을 한 목록으로 묶었는지 봐 주세요.", ""]
    for k, n in enumerate(spots, 1):
        par = byid[n["parent_id"]]
        sibs = [byid[c] for c in par["children"] if byid[c]["type"] == "item" and byid[c].get("marker") == n["marker"]]
        bad = {b["id"] for a, b in zip(sibs, sibs[1:]) if a["number"] is not None and b["number"] is not None and b["number"] != a["number"] + 1}
        art = byid.get(n["article_id"]) if n["article_id"] else None
        pages = sorted({x["lines"][0]["page"] for x in sibs if x["lines"]} | ({par["lines"][0]["page"]} if par["lines"] else set()))
        rows += [f"## {k}. 쪽 {', '.join(map(str, pages))} — 번호 {[x['number'] for x in sibs]}", "",
                 f"- 조: {art['title'] if art else '(조 밖)'}",
                 f"- 부모 ({par['type'] if par['type'] != 'item' else par['marker']}): {(par['title'] or '')} {par['text'][:60]}"]
        rows += [f"  - {'**' if x['id'] in bad else ''}[{x['number']}] {x['text'][:70]}{'**' if x['id'] in bad else ''}" for x in sibs]
        for pg in pages:
            img = Image.open(SECURE / "renders" / f"p{pg:03d}.png").convert("RGB")
            sc = img.width / pages_meta()[pg]["width"]
            d = ImageDraw.Draw(img)
            marks = ([(par, (0, 90, 255))] if par["lines"] else []) + [(x, (255, 140, 0) if x["id"] in bad else (220, 0, 0)) for x in sibs]
            for x, col in marks:
                if not x["lines"] or x["lines"][0]["page"] != pg:
                    continue
                ln = line_at[(pg, x["lines"][0]["line_id"])]
                box = [ln["x0"] * sc - 3, ln["top"] * sc - 3, ln["x1"] * sc + 3, ln["bottom"] * sc + 3]
                d.rectangle(box, outline=col, width=3)
                if x is not par:
                    d.rectangle([box[0] - 44, box[1], box[0] - 4, box[1] + 22], fill=(255, 255, 255))
                    d.text((box[0] - 42, box[1] + 1), str(x["number"]), fill=col, font=fnt)
            img.save(secure_path(SECURE / "review" / "tree_spots" / f"{k}_p{pg:03d}.png"))
        rows += [f"- 그림: {', '.join(f'tree_spots/{k}_p{pg:03d}.png' for pg in pages)}", ""]
    secure_review_write("tree_spots.md", rows)
    return len(spots)
