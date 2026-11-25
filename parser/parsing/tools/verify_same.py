"""리팩터링 뒤 결과가 그대로인지 확인한다 (기준 폴더와 비교, 해시·개수만 출력).

기준 폴더 (기본 secure/archive/verify_prev, --prev로 secure 아래 경로를 바꿈)에
  by_page_hashes.txt가 있으면 쪽별 덤프 파일을 바이트 해시로, by_page/ 폴더가 있으면 내용으로 비교한다
  (새로 생긴 "objects" 칸은 빼고 meta·lines·chars·regions·dropped만).
그 밖에 기준 폴더에 있는 파일 (regions.json, boxes.json, excluded_regions.csv, table_regions.jsonl, tables.jsonl)은 바이트 해시로 비교.
실행 (requirements.txt 환경): python parsing/tools/verify_same.py [--prev verify_prev2]
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # parsing/ (공용 모듈)
from safeio import RESULTS, SECURE, out, setup  # noqa: E402

CURRENT = {"regions.json": SECURE / "lines" / "regions.json", "boxes.json": SECURE / "lines" / "boxes.json",
           "excluded_regions.csv": RESULTS / "parsing" / "excluded_regions.csv",
           "table_regions.jsonl": SECURE / "tables" / "table_regions.jsonl", "tables.jsonl": SECURE / "tables" / "tables.jsonl"}
KEYS = ("meta", "lines", "chars", "regions", "dropped")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def main() -> int:
    setup("verify_same")
    name = sys.argv[sys.argv.index("--prev") + 1] if "--prev" in sys.argv else "archive/verify_prev"
    prev_dir = SECURE / name
    same_all = True
    cur_dir = SECURE / "lines" / "by_page"
    if (prev_dir / "by_page_hashes.txt").exists():
        prev = dict(line.split() for line in (prev_dir / "by_page_hashes.txt").read_text(encoding="utf-8-sig").splitlines()
                    if line.strip())
        diff = sorted(n for n in prev if not (cur_dir / n).exists() or sha(cur_dir / n) != prev[n])
        out("by_page_bytes", prev=len(prev), differ=len(diff), first=diff[:10])
        same_all &= not diff
    if (prev_dir / "by_page").is_dir():
        diff = []
        files = sorted((prev_dir / "by_page").glob("*.json"))
        for f in files:
            a = json.loads(f.read_text(encoding="utf-8"))
            b = json.loads((cur_dir / f.name).read_text(encoding="utf-8")) if (cur_dir / f.name).exists() else {}
            if any(a.get(k) != b.get(k) for k in KEYS):
                diff.append(f.name)
        out("by_page_content", prev=len(files), differ=len(diff), first=diff[:10])
        same_all &= not diff
    for fname, path in CURRENT.items():
        if (prev_dir / fname).exists():
            same = sha(prev_dir / fname) == sha(path)
            same_all &= same
            out("file", name=fname, same=same)
    out("result", same=same_all)
    return 0 if same_all else 1


if __name__ == "__main__":
    sys.exit(main())
