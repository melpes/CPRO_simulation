"""Fab_자료.docx 의 요소 순서만 재배치한다.

텍스트·서식은 일절 건드리지 않고 XML 요소의 위치만 옮긴다.
① 체크리스트 항목을 해당 설비 카드(Ⅲ장) 안으로 이동
② 공정 이해 파트(Ⅱ·Ⅳ)를 문서 뒤로 이동
"""
import shutil
from docx import Document
from docx.oxml.ns import qn

BASE = r"C:/Users/KangTaehui/KG/keti/CPRO_조립공정/원본자료"
SRC = f"{BASE}/Fab_자료.docx"

doc = Document(SRC)
body = doc.element.body


# ── 요소 인덱싱 ─────────────────────────────────────────────────────────
def para_of(el):
    from docx.text.paragraph import Paragraph
    return Paragraph(el, doc)


def is_heading(el, level=None):
    if el.tag != qn("w:p"):
        return False
    st = para_of(el).style.name
    if not st.startswith("Heading"):
        return False
    return level is None or st.endswith(str(level))


def text_of(el):
    return para_of(el).text.strip() if el.tag == qn("w:p") else ""


def find_heading(key, level=None):
    for el in body:
        if is_heading(el, level) and key in text_of(el):
            return el
    raise KeyError(key)


def section_els(start_el):
    """start_el(제목) 다음부터 같은/상위 레벨 제목 직전까지."""
    kids = list(body)
    lvl = int(para_of(start_el).style.name[-1])
    out = []
    for el in kids[kids.index(start_el) + 1:]:
        if el.tag == qn("w:sectPr"):
            break
        if is_heading(el):
            if int(para_of(el).style.name[-1]) <= lvl:
                break
        out.append(el)
    return out


def find_checkitem(snippet):
    """☐ 로 시작하는 체크 항목 문단을 본문 일부로 찾는다."""
    for el in body:
        if el.tag != qn("w:p"):
            continue
        t = text_of(el)
        if t.startswith("☐") and snippet in t:
            return el
    raise KeyError(snippet)


def move_block(els, anchor):
    """els 를 anchor 뒤로 순서대로 옮긴다."""
    cur = anchor
    for el in els:
        el.getparent().remove(el)
        cur.addnext(el)
        cur = el
    return cur


# ── ① 설비별 체크 항목 배치 ─────────────────────────────────────────────
# 각 설비 카드의 마지막 요소(현장 메모 표) 뒤에 붙인다
PLACEMENT = {
    "① 박막증착장비": [
        "챔버 개별 운전 가능 여부",
        "이송 로봇(TM)",
        "chB 장비 정보",
        "사양서상 5개 모듈",
        "IGZO 증착(#12)",
        "Sputter 타깃 교체",
        "스컴 애싱",
        "C-7. 사양서상 박막증착장비",
        "① chD·chE",
    ],
    "② 엣쳐/스트리퍼": [
        "엣쳐/스트리퍼 — 낱장 처리",
        "#29 Wet etching",
        "#21 Surface Treatment",
        "PR strip = runsheet상",
        "Manual stripper",
        "C-1 엣쳐/스트리퍼 사양서",
        "③ 엣쳐/스트리퍼",
    ],
    "③ 현상장비": [
        "현상장비 – 마스크얼라이너 물리적",
        "감광막 코팅·현상 = 현상장비만",
        "스핀디벨로퍼(370×470·수동)",
        "C-5. 현상장비",
        "② 현상장비 · 마스크얼라이너",
    ],
    "④ 마스크얼라이너": [
        "C-2 모델명 중복",
    ],
    "⑤ 고온진공오븐": [
        "고온진공오븐 — 1회 배치 매수",
        "UV-O₃ 처리(#13)",
        "#13의 UV-O₃",
        "C-6. 고온진공오븐",
        "④ 고온진공오븐 · 기판세정기",
    ],
    "⑥ 기판세정기": [
        "기판 세정 공정의 파라미터",
        "TEG-cell 흐름도 세정",
    ],
    "⑦ runsheet 미등장 설비": [
        "⑤ 유기스트리퍼 · 스크린프린터",
        "스핀디벨로퍼 — 수동 장비 추정",
        "스핀 트랙 · 마스크얼라이너(8인치) · PEALD",
        "8인치 라인 전용 제품",
    ],
}

moved = 0
for card_key, snippets in PLACEMENT.items():
    head = find_heading(card_key, level=2)
    tail = section_els(head)
    anchor = tail[-1] if tail else head
    els = []
    for s in snippets:
        try:
            els.append(find_checkitem(s))
        except KeyError:
            print(f"  [미발견] {card_key} ← {s}")
    anchor = move_block(els, anchor)
    moved += len(els)
    print(f"  {card_key} ← 체크 {len(els)}건")

print(f"\n설비 카드로 이동한 체크 항목 : {moved}건")

# ── ② 공정 이해 파트(Ⅱ·Ⅳ)를 문서 뒤로 ─────────────────────────────────
last = list(body)[-1]
if last.tag == qn("w:sectPr"):
    kids = list(body)
    last = kids[kids.index(last) - 1]

for key in ("Ⅱ. FAB 공정 기초", "Ⅳ. 공정 상세"):
    h = find_heading(key, level=1)
    block = [h] + section_els(h)
    last = move_block(block, last)
    print(f"  {key} → 문서 끝으로 ({len(block)}개 요소)")

doc.save(SRC)
print(f"\n저장 완료 : {SRC}")
