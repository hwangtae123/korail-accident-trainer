"""OCR: 글자를 읽을 수 없는 PDF(스캔, 글꼴에 문자 정보 없음)를 쪽 이미지로 바꿔 GPT 비전 모델로 읽는다.

언제 쓰나: parse.quick_text_check가 NeedsOCR를 내면 pipeline이 여기로 넘긴다. 결과는 레이아웃 파서와 같은 모양
("[p.N]\\n본문" 쪽 목록)이고, 섹션은 제목 정규식(parse.split_sections)으로 나눈다.

설정 (환경변수)
- OCR_ENABLED=0 이면 쓰지 않음 (그 보고서는 'OCR 필요'로 멈춘다). 기본은 LLM_PROVIDER=openai이고 키가 있으면 켜짐
- OCR_MODEL (기본 LLM_MODEL), OCR_DPI (기본 150 — 100dpi는 한글을 잘못 읽는 경우가 있었다)
- OCR_CONCURRENCY (기본 8 — 쪽당 약 5초라 100쪽도 1분 남짓. Vercel 함수 300초 안에 끝내려고)
비용 실측 (gpt-6-luna, 150dpi, 추론 끔): 쪽당 입력 2,655 + 출력 약 650 토큰 ≈ $0.0006
"""
import base64
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

PROMPT = ("이 쪽은 철도 사고조사보고서의 한 쪽을 찍은 이미지다. 보이는 글자를 빠짐없이 그대로 옮겨 적어라. "
          "읽는 순서대로, 장·절 제목과 번호(예: 1. 사실정보, 3.2 사고원인)는 한 줄에 그대로, 표는 Markdown 표로. "
          "머리글·쪽번호는 빼라. 글자가 없는 쪽(그림·사진만)은 빈 응답. 설명이나 요약은 쓰지 마라.")

# 테스트에서 끼워 넣는 가짜 OCR: (png 바이트, 쪽 번호) -> 글자
_stub: Callable[[bytes, int], str] | None = None


def set_stub(fn: Callable[[bytes, int], str] | None) -> None:
    global _stub
    _stub = fn


class OCRError(RuntimeError):
    pass


def enabled() -> bool:
    if _stub is not None:
        return True
    if os.getenv("OCR_ENABLED", "1") == "0":
        return False
    return bool(_ocr_providers())


def _ocr_providers():
    """OCR을 맡길 비전 모델 (순서대로): OpenAI(OCR_MODEL 또는 LLM_MODEL) -> Gemini(OCR_FALLBACK_MODEL 또는 LLM_FALLBACK_MODEL).
    키가 있는 것만."""
    from .llm import Provider, providers

    out = []
    for p in providers():
        if p.name == "openai" and os.getenv("OPENAI_API_KEY"):
            out.append(Provider("openai", os.getenv("OCR_MODEL") or p.model))
        elif p.name == "gemini" and os.getenv("GEMINI_API_KEY"):
            out.append(Provider("gemini", os.getenv("OCR_FALLBACK_MODEL") or p.model))
    return [p for p in out if p.model]


def _render(pdf_path: Path, dpi: int) -> list[bytes]:
    """쪽마다 흑백 PNG. 긴 변은 A4 150dpi 크기(1755px)를 넘지 않게 해서 이미지 토큰을 일정하게 둔다."""
    import pypdfium2 as pdfium

    out = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for page in doc:
            w, h = page.get_size()
            scale = min(dpi / 72, 1755 / max(w, h))
            img = page.render(scale=scale).to_pil().convert("L")
            buf = io.BytesIO()
            img.save(buf, "PNG", optimize=True)
            out.append(buf.getvalue())
    finally:
        doc.close()
    return out


def _read_with(p, b64: str) -> str:
    from .llm import openai_client

    kwargs = {}
    if p.name == "openai" and os.getenv("OCR_REASONING", "none") == "none":
        kwargs["reasoning_effort"] = "none"  # 실측: 추론을 끄면 출력 토큰 절반, 5초, 정확도 같음
    client = openai_client(p).with_options(timeout=float(os.getenv("OCR_TIMEOUT", "45")))
    r = client.chat.completions.create(model=p.model, messages=[{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
    ]}], **kwargs)
    return (r.choices[0].message.content or "").strip()


def _read_page(png: bytes, pno: int) -> str:
    """한 쪽 읽기: 기본 모델로 2번까지, 안 되면 대체 모델(Gemini)로 2번까지."""
    if _stub is not None:
        return _stub(png, pno)
    chain = _ocr_providers()
    if not chain:
        raise OCRError("OCR에 쓸 모델이 없습니다 (OPENAI_API_KEY·LLM_MODEL 또는 GEMINI_API_KEY)")
    b64 = base64.b64encode(png).decode()
    errors = []
    for p in chain:
        for attempt in range(2):
            try:
                return _read_with(p, b64)
            except Exception as e:  # 일시 오류(속도 제한 등)는 잠깐 쉬고 다시, 그래도 안 되면 다음 모델
                errors.append(f"{p.label}: {type(e).__name__}: {str(e)[:120]}")
                time.sleep(2 * (attempt + 1))
    raise OCRError(f"{pno}쪽 OCR 실패 — " + " / ".join(errors[-2:]))


def ocr_pdf(pdf_path: str | Path, progress: Callable[[int, int], None] | None = None) -> list[str]:
    """PDF 전체 -> ["[p.1]\\n글자", ...]. 여러 쪽을 동시에 읽는다. progress(끝난 쪽 수, 전체 쪽 수)."""
    pngs = _render(Path(pdf_path), int(os.getenv("OCR_DPI", "150")))
    n = len(pngs)
    texts: list[str | None] = [None] * n
    done = 0

    def work(i: int) -> None:
        nonlocal done
        texts[i] = _read_page(pngs[i], i + 1)
        done += 1
        if progress and (done % 5 == 0 or done == n):
            progress(done, n)

    with ThreadPoolExecutor(max_workers=max(1, int(os.getenv("OCR_CONCURRENCY", "8")))) as ex:
        for f in [ex.submit(work, i) for i in range(n)]:
            f.result()  # 한 쪽이라도 끝내 실패하면 OCRError
    return [f"[p.{i + 1}]\n{t or ''}" for i, t in enumerate(texts)]
