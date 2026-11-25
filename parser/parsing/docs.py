"""data/의 PDF와 문서 설정 (config/docs/<doc_id>.yaml) 짝짓기.

- 문서 설정 찾기: sha256이 같은 파일, 없으면 pdf 경로가 같은 파일.
- 짝이 없는 새 PDF: 파일 이름으로 doc_id를 만들고 문서 설정을 쓴다. 프로필은 parsing/profile_draft.py가 고른다
  (폰트가 맞는 기존 프로필, 없으면 config/profiles/<doc_id>.yaml 초안). 구역은 임시 (zones_status: provisional, 전체 쪽)이고
  덤프 뒤 auto_zones.py가 쪽마다 구역을 정해 zones_status: auto로 바꾼다.
- 경로는 같은데 sha256이 다름 (PDF를 바꿔 넣음): 자동 구역이면 임시로 되돌리고 덤프부터 다시, 사람이 확인한 구역이면 멈춘다.
- 내용이 같은 PDF가 data/에 두 번 있으면 하나만 쓴다.

zones_status: provisional (덤프 전 임시) / auto (자동 구역, 확인 전) / 없음 (사람이 확인한 구역. 자동으로 고치지 않는다).
자동 구역을 확인해 고쳤다면 zones_status 줄을 지운다. 문서 설정의 다른 줄 (profile, params, eval)은 자동으로 고치지 않는다.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from safeio import DATA_DIR, DOCS_DIR, ROOT, rel


@dataclass
class Doc:
    doc_id: str
    pdf: Path
    sha256: str
    config: Path
    status: str  # matched (문서 설정 있음) / new (새로 만듦) / changed (PDF가 바뀜) / conflict (멈춤)
    #              / duplicate (data/에 같은 내용 PDF가 이미 있음, 건너뜀)
    profile_note: str = ""  # 새 문서: reused / drafted / no_text


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def page_count(pdf: Path) -> int:
    import pypdfium2 as pdfium

    d = pdfium.PdfDocument(str(pdf))
    try:
        return len(d)
    finally:
        d.close()


def _rel(p: Path) -> str:
    """문서 설정의 pdf 경로: 파서 폴더 기준 (PDF 폴더가 밖이면 ../data/…)."""
    return rel(p)


def _q(v: str) -> str:
    return yaml.safe_dump(v, allow_unicode=True).splitlines()[0]


def slug(stem: str) -> str:
    """파일 이름 → doc_id. 글자·숫자·_·-·. 만 남긴다 (한글 유지)."""
    s = re.sub(r"[^\w.\-]+", "_", stem).strip("._")
    return s or "doc"


def _zone_rows(zones: list[list]) -> list[str]:
    return [f"  - [{a}, {b}, {z}, {'true' if inc else 'false'}]" for a, b, z, inc in zones]


def new_config(path: Path, doc_id: str, pdf: Path, sha: str, pages: int, profile: str, body_font: str | None = None) -> None:
    """새 문서 설정 (형식은 CUSTOMIZE.md)."""
    rows = [
        "# 문서 설정. 자동으로 만든 파일 (parsing/docs.py). 고쳐 쓰는 법은 CUSTOMIZE.md.",
        f"doc_id: {_q(doc_id)}",
        f"pdf: {_q(_rel(pdf))}",
        f"sha256: {sha}",
        f"pages: {pages}",
        f"profile: {_q(profile)}            # config/profiles/<이름>.yaml",
        f"body_font: {_q(body_font or 'UNSET/0')}   # 글자가 가장 많은 폰트 (프로필 fonts.body: auto일 때 씀)",
        "",
        "# 이 문서에만 쓰는 임계값 (config/params.yaml 위에 덮어씀). 예: {tree: {item_align_tol_pt: 4}}",
        "params: {}",
        "",
        "# 구역: 자동 (덤프 뒤 auto_zones.py). 확인해 고쳤다면 zones_status 줄을 지운다 (그 뒤로는 자동으로 고치지 않음).",
        "zones_status: provisional",
        "# [첫 쪽, 끝 쪽, 구역, 포함]",
        "zones:",
        *_zone_rows([[1, pages, "본문", True]]),
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def set_fields(path: Path, **fields) -> None:
    """맨 위 'key: 값' 줄만 바꾼다 (주석·다른 줄은 그대로). 없는 key는 zones: 앞에 넣는다."""
    text = path.read_text(encoding="utf-8")
    for k, v in fields.items():
        rx = re.compile(rf"(?m)^{k}:[ \t]*[^\n#]*?([ \t]*#[^\n]*)?$")
        if rx.search(text):  # 값만 바꾸고 줄 끝 주석은 둔다
            text = rx.sub(lambda m: f"{k}: {v}{m.group(1) or ''}", text, 1)
        else:
            text = re.sub(r"(?m)^(# \[첫 쪽.*\n)?zones:", lambda m: f"{k}: {v}\n" + m.group(0), text, 1)
    path.write_text(text, encoding="utf-8")


def set_zones(path: Path, zones: list[list], status: str) -> None:
    """zones 목록과 zones_status만 바꾼다."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^zones:\n(?:[ \t]+-.*\n?)*", "zones:\n" + "\n".join(_zone_rows(zones)) + "\n", text, 1)
    path.write_text(text, encoding="utf-8")
    set_fields(path, zones_status=status)


def _configs() -> list[tuple[Path, dict]]:
    return [(p, yaml.safe_load(p.read_text(encoding="utf-8")) or {}) for p in sorted(DOCS_DIR.glob("*.yaml"))]


def discover() -> list[Doc]:
    """data/의 PDF마다 문서 설정을 찾거나 만든다."""
    from profile_draft import ensure_profile

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    configs = _configs()
    used_ids = {cfg.get("doc_id") or p.stem for p, cfg in configs}
    docs: list[Doc] = []
    for pdf in sorted({*DATA_DIR.glob("*.pdf"), *DATA_DIR.glob("*.PDF")}):
        sha = sha256_of(pdf)
        dup = next((d for d in docs if d.sha256 == sha), None)
        if dup:  # 같은 PDF를 이름만 바꿔 두 번 넣음
            docs.append(Doc(dup.doc_id, pdf, sha, dup.config, "duplicate"))
            continue
        by_sha = next(((p, c) for p, c in configs if str(c.get("sha256", "")).lower() == sha), None)
        if by_sha:
            p, c = by_sha
            docs.append(Doc(c.get("doc_id") or p.stem, pdf, sha, p, "matched"))
            continue
        by_path = next(((p, c) for p, c in configs if c.get("pdf") and (ROOT / c["pdf"]).resolve() == pdf.resolve()), None)
        if by_path:
            p, c = by_path
            did = c.get("doc_id") or p.stem
            if c.get("zones_status") in ("provisional", "auto"):
                n = page_count(pdf)
                set_fields(p, sha256=sha, pages=n)
                set_zones(p, [[1, n, "본문", True]], "provisional")
                docs.append(Doc(did, pdf, sha, p, "changed"))
            else:
                docs.append(Doc(did, pdf, sha, p, "conflict"))
            continue
        did, k = slug(pdf.stem), 2
        base = did
        while did in used_ids:
            did, k = f"{base}_{k}", k + 1
        used_ids.add(did)
        prof, note, body = ensure_profile(did, pdf, os.environ.get("PARSE_PROFILE"))
        path = DOCS_DIR / f"{did}.yaml"
        new_config(path, did, pdf, sha, page_count(pdf), prof, body)
        configs.append((path, yaml.safe_load(path.read_text(encoding="utf-8"))))
        docs.append(Doc(did, pdf, sha, path, "new", note))
    return docs
