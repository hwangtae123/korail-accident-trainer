"""줄바꿈 잇기 (보고서 프로필 smart_line_join).

글자 단위로 줄을 나누는 문서 (한글 문서 편집기 기본값)는 단어 중간에서도 줄이 바뀐다 ("무도상궤|도로로", "같|이").
줄을 공백으로 이으면 "무도상궤 도로로"가 되므로, 줄 끝 어절 a와 다음 줄 첫 어절 b를 보고 공백을 넣을지 정한다
(위에서부터 먼저 맞는 규칙):
  1. a가 문장부호·닫는 괄호로 끝나거나 b가 글머리 기호 (ㅇ ○ - • ※ ①…)로 시작하면 공백
  2. b가 조사 하나 ("탈선사고"+"가")나 "하다·되다" 활용 ("보완"+"할 것")이면 붙임
  3. a + b 첫 글자로 시작하는 어절이 같은 문서 다른 곳에 있으면 붙임 ("압축"+"력과": 문서에 "압축력"이 있음)
  4. a가 숫자로 끝나면 붙임 ("2.475"+"㎞)의", "14"+"번째")
  5. a가 숫자+단위 ("13시", "5월", "14일")로 끝나거나 b가 숫자로 시작하면 공백
  6. a가 영문·기호 (㎜, m, kr)로 끝나고 b가 한글이면 공백
  7. a와 b (2글자 이상)가 둘 다 문서 다른 곳에도 어절로 나오면 공백 ("레일"+"위를")
  8. a (2글자 이상)의 어간 (조사 뗀 것)이 문서 다른 곳에도 나오면 공백 ("부식"+"정도가"; 줄 끝 조각 "무도상궤"는
     한 번뿐이라 해당 없음)
  9. a가 조사·어미로 끝나면 공백 ("차륜이"+"레일을")
 10. 나머지는 붙임 (글자 단위 줄바꿈에서는 단어 중간이 더 흔하다)
어휘는 문서의 줄 글자에서 공백으로 나눈 어절 (앞뒤 문장부호 뺌).
"""

import bisect
import re
from collections import Counter

PUNCT_END = tuple(",.;:!?)]}」』〉》”’%·")
# 어절 끝에 흔한 조사·어미 (줄 끝 어절이 이 글자로 끝나면 단어 경계로 본다)
WORD_END = set("은는이가을를에의와과로도만서써고며면다요께및등한된할인던")
BULLETS = set("ㅇ○●◦•-–※□■▶▷◆◇") | {chr(c) for c in range(ord("①"), ord("⑳") + 1)}
DIGITS = set("0123456789")
STRIP = "()[]{}「」『』<>〈〉《》\"'“”‘’,.;:!?·"
PARTICLES = ("에서는", "에서", "으로는", "으로써", "으로", "에게", "까지", "부터", "보다", "처럼", "에는", "에도", "이다", "이며", "이고",
             "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "로", "도", "만")
VERB_START = re.compile(r"^(하[여고는였기면며지게]|할|한|했|함|되[어었는고기면며지]|된|될|됐|됨|시키|시킨)")
NUM_UNIT_END = re.compile(r"\d\s*(년|월|일|시|분|초|회|명|개|량|호|건|차례)$")


def tokens(text: str) -> list[str]:
    return [t.strip(STRIP) for t in text.split() if t.strip(STRIP)]


def stem(t: str) -> str:
    for p in PARTICLES:
        if t.endswith(p) and len(t) > len(p) + 1:
            return t[: -len(p)]
    return t


class Vocab:
    """문서 어절 목록 (앞부분 일치 검색, 어절·어간 개수)."""

    def __init__(self, texts):
        self.count = Counter(t for x in texts for t in tokens(x))
        self.stems = Counter()
        for t, n in self.count.items():
            self.stems[stem(t)] += n
        self.words = sorted(self.count)

    def has_prefix(self, p: str) -> bool:
        i = bisect.bisect_left(self.words, p)
        return i < len(self.words) and self.words[i].startswith(p)


def need_space(a_line: str, b_line: str, vocab: Vocab | None) -> bool:
    a_line, b_line = a_line.rstrip(), b_line.lstrip()
    if not a_line or not b_line:
        return False
    if a_line.endswith(PUNCT_END):
        return True
    a = a_line.split()[-1].lstrip(STRIP)
    b = b_line.split()[0]
    bw = b.strip(STRIP)
    if not a or not bw or bw[0] in BULLETS:
        return True
    hangul_a, hangul_b = bool(re.match(r"[가-힣]", a[-1])), bool(re.match(r"[가-힣]", bw[0]))
    if hangul_a and (bw in PARTICLES or VERB_START.match(bw)):
        return False
    if vocab is not None and hangul_b and vocab.has_prefix(a + bw[0]):
        return False
    if a[-1] in DIGITS:  # ②처럼 isdigit()이 참인 원문자는 빼고 아라비아 숫자만
        return False
    if NUM_UNIT_END.search(a) or bw[0] in DIGITS:
        return True
    if not hangul_a and hangul_b:
        return True
    if vocab is not None:
        if vocab.count[a] >= 2 and len(bw) >= 2 and vocab.count[bw] >= 2:
            return True
        if len(a) >= 2 and vocab.stems[stem(a)] >= 2:
            return True
    return a[-1] in WORD_END


def join_lines(parts: list[str], vocab: Vocab | None, sep: str = " ") -> str:
    """줄 목록을 잇는다. vocab이 None이면 늘 sep."""
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        return ""
    if vocab is None:
        return sep.join(parts)
    out = parts[0]
    for p in parts[1:]:
        out += (" " if need_space(out, p, vocab) else "") + p
    return out
