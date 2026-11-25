"""양식 프로필 초안: 새 PDF의 폰트 분포를 보고 config/profiles/의 프로필을 고르거나 초안을 만든다.

PDF를 직접 읽는다 (덤프 전에 돈다). 쪽이 많으면 고르게 MAX_PAGES쪽만 본다.
  - 폰트 키별 글자 수, 줄 수, 줄 맨 앞이 "제N편"·"제N관"·"제N조"·"1.2 …"(소수점 번호)·"Ⅱ. …"인 줄 수를 센다.
  - 보고서 모양 (소수점·로마 숫자 제목 줄 ≥ 5, 제N조 줄이 그 1/5 미만)이고 config/profiles/report.yaml이 있으면 report.
  - 기존 프로필 중 body 폰트가 같고 (조 줄이 있으면) article_title 폰트도 이 문서의 조 줄 폰트인 것이 있으면 그것을 쓴다.
  - 없으면 초안: body = 글자가 가장 많은 폰트, article/gwan/pyeon_title = 그 패턴 줄에 가장 많이 쓰인 폰트 (body가 아닌 것 우선),
    title_band = 본문보다 1.4배 이상 큰 폰트 (위 제목 폰트 제외), small = 본문보다 1.5pt 이상 작은 폰트 중 가장 많은 것,
    section_title·form_code = UNSET/0 (사람이 정함). 박스 라벨·예시·참조 규칙은 default 프로필에서 복사한다.
화면에는 폰트 키와 수치만 낸다 (원문 없음).

실행 (requirements.txt 환경):
  python parsing/profile_draft.py --doc <doc_id>            폰트 표만 보기
  python parsing/profile_draft.py --doc <doc_id> --write    초안을 config/profiles/<doc_id>.yaml에 쓰고 문서 설정의 profile을 바꿈
"""

import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safeio import ROOT, Trusted, out  # noqa: E402

PROFILES_DIR = ROOT / "config" / "profiles"
UNSET = "UNSET/0"
MAX_PAGES = int(os.environ.get("PARSE_FONT_SAMPLE_PAGES", "120"))  # 폰트 분포를 볼 쪽 수 (고르게)
HEAD_RE = {"pyeon": re.compile(r"제\s*\d+\s*편"), "gwan": re.compile(r"제\s*\d+\s*관"),
           "article": re.compile(r"제\s*\d+\s*(?:-\s*\d+\s*)?조"),
           "decimal": re.compile(r"\d+(?:\.\d+)+\.?\s+\S"), "roman": re.compile(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.\s*\S")}


def fkey(fontname: str, size: float) -> str:
    return f"{fontname.split('+', 1)[-1]}/{round(size, 1):g}"


def size_of(key: str) -> float:
    return float(key.rsplit("/", 1)[1])


def font_stats(pdf_path: Path) -> dict:
    """폰트 키별 {chars, lines, pyeon, gwan, article} (줄 맨 앞 패턴 수)."""
    import pdfplumber

    st: dict[str, Counter] = defaultdict(Counter)
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
        pages = range(n) if n <= MAX_PAGES else sorted({round(i * (n - 1) / (MAX_PAGES - 1)) for i in range(MAX_PAGES)})
        for i in pages:
            page = pdf.pages[i]
            for line in page.extract_text_lines(return_chars=True, strip=True):
                chars = [c for c in line["chars"] if c["text"].strip()]
                if not chars:
                    continue
                cnt = Counter(fkey(c["fontname"], c["size"]) for c in chars)
                for k, v in cnt.items():
                    st[k]["chars"] += v
                key = cnt.most_common(1)[0][0]
                st[key]["lines"] += 1
                text = line["text"].lstrip()
                for kind, rx in HEAD_RE.items():
                    if rx.match(text):
                        st[key][kind] += 1
                        break
            page.flush_cache()
    return {k: dict(v) for k, v in st.items()}


def _pick(stats: dict, kind: str, body: str) -> str:
    c = Counter({k: v.get(kind, 0) for k, v in stats.items() if v.get(kind)})
    if not c:
        return UNSET
    total = sum(c.values())
    for k, v in c.most_common():
        if k != body and v >= 0.3 * total:
            return k
    return c.most_common(1)[0][0]


def draft(stats: dict, base: dict) -> dict:
    """폰트 통계로 프로필 초안 (base = default 프로필에서 양식 무관 항목을 가져옴)."""
    body = max(stats, key=lambda k: stats[k].get("chars", 0))
    bs = size_of(body)
    art, gwan, pyeon = _pick(stats, "article", body), _pick(stats, "gwan", body), _pick(stats, "pyeon", body)
    heads = {art, gwan, pyeon}
    band = [k for k, v in sorted(stats.items(), key=lambda kv: -kv[1].get("lines", 0))
            if size_of(k) >= bs * 1.4 and k not in heads and v.get("lines")][:3] or [UNSET]
    total = sum(v.get("chars", 0) for v in stats.values())
    small = [k for k, v in sorted(stats.items(), key=lambda kv: -kv[1].get("chars", 0))
             if size_of(k) <= bs - 1.5 and v.get("chars", 0) >= 0.01 * total]
    bold = sorted({k.rsplit("/", 1)[0] for k in (art,) if k != UNSET and k.rsplit("/", 1)[0] != body.rsplit("/", 1)[0]})
    return {
        "auto_zones": "generic",
        "fonts": {"body": body, "article_title": art, "gwan_title": gwan, "pyeon_title": pyeon, "section_title": UNSET,
                  "title_band": band, "small": small[0] if small else UNSET, "form_code": UNSET},
        "bold_font_prefixes": bold,
        **{k: base[k] for k in ("box_labels", "box_kinds_not_table", "example", "form_code_regex", "references") if k in base},
        "box_label_fills": [],
        "box_label_fill_tol": base.get("box_label_fill_tol", 0.02),
    }


def body_font(stats: dict) -> str:
    return max(stats, key=lambda k: stats[k].get("chars", 0))


def is_report(stats: dict) -> bool:
    heads = sum(v.get("decimal", 0) + v.get("roman", 0) for v in stats.values())
    arts = sum(v.get("article", 0) for v in stats.values())
    return heads >= 5 and arts * 5 < heads


def choose_existing(stats: dict) -> str | None:
    """보고서 모양이면 report 프로필, 아니면 body 폰트 (와 조 줄 폰트)가 맞는 기존 프로필 이름."""
    if is_report(stats) and (PROFILES_DIR / "report.yaml").exists():
        return "report"
    body = body_font(stats)
    art_fonts = {k for k, v in stats.items() if v.get("article")}
    for p in sorted(PROFILES_DIR.glob("*.yaml")):
        f = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("fonts", {})
        if f.get("body") == body and (not art_fonts or f.get("article_title") in art_fonts):
            return p.stem
    return None


def write_profile(name: str, prof: dict, stats: dict, pdf_name: str) -> Path:
    rows = [f"# 양식 프로필 초안 (parsing/profile_draft.py가 {pdf_name}의 폰트 분포로 만듦). 확인하고 고쳐 쓴다 (CUSTOMIZE.md).",
            "# 폰트 키 = <폰트 이름>/<크기>. UNSET/0 = 이 문서에 없는 역할 (어느 줄과도 맞지 않음).",
            "# 폰트 분포 (글자 수 많은 순, 최대 15개): 폰트 키 | 글자 | 줄 | 줄 맨 앞 제N편·제N관·제N조",
            ]
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1].get("chars", 0))[:15]:
        rows.append(f"#   {k:<32} chars={v.get('chars', 0):<7} lines={v.get('lines', 0):<6} "
                    f"pyeon={v.get('pyeon', 0)} gwan={v.get('gwan', 0)} article={v.get('article', 0)}")
    rows.append("")
    rows.append(yaml.safe_dump(prof, allow_unicode=True, sort_keys=False, default_flow_style=None, width=200))
    path = PROFILES_DIR / f"{name}.yaml"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def ensure_profile(doc_id: str, pdf_path: Path, force: str | None = None) -> tuple[str, str, str | None]:
    """새 문서의 프로필: (이름, reused|drafted|no_text, 본문 폰트). 맞는 기존 프로필이 없으면
    config/profiles/<doc_id>.yaml 초안을 쓴다. 본문 폰트는 문서 설정 body_font로 (프로필 fonts.body: auto가 읽음)."""
    stats = font_stats(pdf_path)
    if not stats:  # 글자 층이 없는 PDF (스캔본)
        return force or "default", "no_text", None
    if force:  # 환경 변수 PARSE_PROFILE로 프로필을 정함 (백엔드는 늘 report)
        return force, "forced", body_font(stats)
    name = choose_existing(stats)
    if name:
        return name, "reused", body_font(stats)
    base = yaml.safe_load((PROFILES_DIR / "default.yaml").read_text(encoding="utf-8")) or {}
    write_profile(doc_id, draft(stats, base), stats, pdf_path.name)
    return doc_id, "drafted", body_font(stats)


def main() -> int:
    from safeio import setup

    setup("profile_draft", shared=True)
    if "--doc" not in sys.argv:
        out("usage", cmd=Trusted("python parsing/profile_draft.py --doc <doc_id> [--write]"))
        return 2
    did = sys.argv[sys.argv.index("--doc") + 1]
    from safeio import DOCS_DIR

    cfg_path = DOCS_DIR / f"{did}.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    stats = font_stats(ROOT / cfg["pdf"])
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1].get("chars", 0))[:15]:
        out("font", key=Trusted(k), **{x: v.get(x, 0) for x in ("chars", "lines", "pyeon", "gwan", "article", "decimal", "roman")})
    out("existing_match", profile=Trusted(choose_existing(stats) or "-"))
    if "--write" in sys.argv:
        base = yaml.safe_load((PROFILES_DIR / "default.yaml").read_text(encoding="utf-8")) or {}
        path = write_profile(did, draft(stats, base), stats, Path(cfg["pdf"]).name)
        text = cfg_path.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^profile:.*$", f"profile: {did}", text) if re.search(r"(?m)^profile:", text) \
            else text.replace("\nzones", f"\nprofile: {did}\nzones", 1)
        cfg_path.write_text(text, encoding="utf-8")
        out("written", profile=Trusted(path.relative_to(ROOT).as_posix()), doc=Trusted(cfg_path.relative_to(ROOT).as_posix()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
