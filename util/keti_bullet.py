"""자료목록 엑셀에 넣을 문장을 개조식으로 바꾼다.

줄글은 셀 안에서 읽기 어렵다. 각 줄 앞에 * 를 붙이고 끝의 마침표는 뗀다.
강조 표시(**)도 셀에서는 그냥 글자로 보이므로 없앤다.
"""

import re

NL = chr(10)


def bullets(text, seps=None):
    """줄글 → 개조식. seps 는 줄을 나눌 구분자 정규식."""
    t = (text or "").strip()
    if not t:
        return ""
    if t.startswith("*"):        # 이미 개조식이면 그대로 둔다 (두 번 붙지 않게)
        return t
    t = t.replace("**", "")
    pat = seps or r"(?:\.\s+|\s+/\s+|\s+→\s+)"
    parts = [x.strip(" .·—-") for x in re.split(pat, t)]
    return NL.join("*" + x for x in parts if x)


def bullets_list(text):
    """쉼표로 나열된 이름 목록 → 개조식."""
    return bullets(text, r"\s*,\s*")


def bullets_loc(text):
    """위치 표기 → 개조식.

    쉼표로는 나누지 않는다. 'PECVD : SiO2, Si3N4' 처럼 값이 쉼표로 나열되기 때문이다.
    쪽 번호 나열(p37, p52 …)만 예외로 나눈다.
    """
    t = (text or "").strip()
    if re.search(r"p\d", t):
        return bullets(t, r"(?:\s*,\s*|\s+/\s+|\s+→\s+)")
    return bullets(t, r"(?:\s+/\s+|\s+→\s+)")


def search_keywords(evidences, limit=12):
    """특허 본문에서 Ctrl+F 로 칠 검색어를 만든다.

    슬롯 이름이 원문에 그대로 있으면 그것을 쓴다(가장 확실하다).
    없으면 원문에서 조사·숫자를 뺀 명사 덩어리를 골라 쓴다.
    숫자 중간에서 잘린 조각(`1:1 내지 3:`)은 검색어로 못 쓰므로 버린다.
    """
    out = []
    for nm, quote in evidences:
        q = " ".join((quote or "").split())
        if nm and nm in q:
            key = nm
        else:
            # 따옴표·괄호 안의 용어를 우선 집는다
            m = re.search(r"['\"‘“]([^'\"’”]{2,20})['\"’”]", q)
            if m:
                key = m.group(1)
            else:
                # 숫자로 시작하거나 끝나는 조각은 검색어로 쓸 수 없다
                m2 = re.search(r"([가-힣A-Za-z][가-힣A-Za-z ]{2,16})", q)
                key = m2.group(1) if m2 else ""
        key = key.strip(" ,.·'\"‘’“”")
        if len(key) < 2 or re.fullmatch(r"[\d\s:~.,\-]+", key):
            continue
        if key not in out:
            out.append(key)
    return NL.join("*" + k for k in out[:limit])
