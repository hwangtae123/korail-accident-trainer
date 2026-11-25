"""쪽 목록. 포함 쪽과 구역은 문서 설정 config/docs/<doc_id>.yaml의 zones에서 읽는다.
평가용 쪽 (SAMPLE45 규칙 조정용, RANDOM15 검증용)과 구역 확인 범위는 문서 설정의 eval (선택)에서 읽는다.
eval이 없으면 샘플은 빈 목록이고 구역 확인·덤프 범위는 전체 쪽이다."""

import random

from config import doc, final_zones

N_PAGES = int(doc()["pages"])
_EVAL = doc().get("eval") or {}


def _pages(spec) -> list[int]:
    """[쪽 또는 [첫 쪽, 끝 쪽], ...] → 쪽 목록."""
    res = []
    for x in spec or []:
        res += list(range(int(x[0]), int(x[1]) + 1)) if isinstance(x, list) else [int(x)]
    return sorted(set(res))


SAMPLE45 = _pages(_EVAL.get("sample45"))
_R = _EVAL.get("random15") or {}
RANDOM_SEED = _R.get("seed")
RANDOM15 = (sorted(random.Random(RANDOM_SEED).sample(
    sorted(set(range(int(_R["from"][0]), int(_R["from"][1]) + 1)) - set(SAMPLE45)), int(_R.get("n", 15))))
    if _R else [])
# 구역 경계 확인 범위 (tools/zones.py)
ZONE_PAGES = _pages(_EVAL.get("zone_check_pages")) or list(range(1, N_PAGES + 1))
ALL_PAGES = sorted(SAMPLE45 + RANDOM15)
# 최종 구역: (첫 쪽, 끝 쪽, 구역, 포함)
FINAL_ZONES = final_zones()
INCLUDED_PAGES = [p for a, b, _, inc in FINAL_ZONES if inc for p in range(a, b + 1)]
DUMP_PAGES = sorted(set(ALL_PAGES) | set(ZONE_PAGES))


def zone_of(page: int) -> tuple[str, bool]:
    return next((z, inc) for a, b, z, inc in FINAL_ZONES if a <= page <= b)


def sample_set(page: int) -> str:
    return "sample45" if page in SAMPLE45 else "random15"


if __name__ == "__main__":
    from safeio import out, setup

    setup("samples")
    out("random15", seed=RANDOM_SEED, pages=RANDOM15)
