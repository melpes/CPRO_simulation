"""국산 장비 제조사의 특허를 Google Patents 에서 모아 각 설비 폴더의 특허/ 하위에 저장한다.

포털(ZEUS·i-Tube)에 없는 공정 파라미터는 제조사 특허 명세서에 나오는 경우가 있다.
국산 장비 제조사는 웹 데이터시트가 없어 특허가 사실상 유일한 공개 사양 출처다.
"""

import json
import os
import re
import sys
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
PAT_DIR = "특허"
XHR = "https://patents.google.com/xhr/query"
DETAIL = "https://patents.google.com/patent/{}/ko"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 설비번호: (폴더 접두, 출원인, 검색 키워드)
TARGETS = {
    17: ("에프엔에스테크", "기판 세정 장치"),
    18: ("에프엔에스테크", "현상 장치"),
    19: ("에프엔에스테크", "식각 스트립"),
    35: ("에프엔에스테크", "스트리퍼 박리"),
    20: ("세리아 엔지니어링", "스크린 인쇄"),
    24: ("선익시스템", "유기 증착"),
    26: ("테스", "박막 증착"),
    27: ("제우스", "화학 습식 증착"),
    31: ("나래나노텍", "옵셋 인쇄"),
    34: ("마이다스시스템", "스핀 현상"),
    43: ("에스브이에스", "반도체 처리 장치"),
    44: ("씨엔원", "원자층 증착"),
    21: ("코디엠", "노광 기판"),
}

# 수치 파라미터로 볼 단위
UNIT = r"(℃|°C|㎛|㎜|㎝|mm|cm|Torr|mTorr|sccm|slm|rpm|RPM|kW|kV|kPa|MPa|W\b|V\b|A\b|Hz|MHz|분|초|%|㎩|nm|㎚)"

sess = requests.Session()
sess.headers["User-Agent"] = UA


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


class Blocked(Exception):
    """Google 이 요청량 때문에 Sorry 페이지를 돌려준 상태."""


def search(assignee, keyword, num=10):
    inner = f"q={quote(keyword, safe='')}&assignee={quote(assignee, safe='')}"
    r = sess.get(XHR, params={"url": inner}, timeout=40)
    if "<title>Sorry" in r.text[:400]:
        raise Blocked("Google Patents 요청량 초과 — 시간을 두고 재시도할 것")
    try:
        res = r.json().get("results", {})
    except Exception:
        return []
    out = []
    for c in res.get("cluster") or []:
        for x in c.get("result", []):
            p = x.get("patent", {})
            asg = re.sub(r"<[^>]+>", "", p.get("assignee", ""))
            # 출원인이 실제로 일치하는 것만 (관련도 검색이라 무관한 건이 섞인다)
            if assignee.replace(" ", "") not in asg.replace(" ", ""):
                continue
            out.append({
                "번호": p.get("publication_number", ""),
                "제목": re.sub(r"<[^>]+>", "", p.get("title", "")).strip(),
                "출원인": asg,
                "공개일": p.get("publication_date", ""),
                "url": DETAIL.format(p.get("publication_number", "")),
            })
            if len(out) >= num:
                return out
    return out


def fetch_desc(num, tries=3):
    for i in range(tries):
        try:
            r = sess.get(DETAIL.format(num), timeout=50)
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            sec = soup.find("section", {"itemprop": "description"})
            if sec:
                return re.sub(r"\n{3,}", "\n\n", sec.get_text("\n", strip=True))
        except Exception:
            pass
        time.sleep(1.5)
    return ""


def param_lines(text):
    return [l for l in text.split("\n") if re.search(r"\d\s*" + UNIT, l)]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    summary = []
    folders = {int(d[:2]): d for d in os.listdir(OUT_DIR)
               if os.path.isdir(os.path.join(OUT_DIR, d)) and d[:2].isdigit()}

    for no, (assignee, keyword) in sorted(TARGETS.items()):
        d = folders.get(no)
        if not d:
            continue
        try:
            hits = search(assignee, keyword)
        except Blocked as e:
            print(f"[{no:2}] 중단: {e}")
            break
        time.sleep(3)
        if not hits:
            print(f"[{no:2}] {assignee} / {keyword}: 0건")
            summary.append({"no": no, "출원인": assignee, "건수": 0})
            continue

        pdir = os.path.join(OUT_DIR, d, PAT_DIR)
        os.makedirs(pdir, exist_ok=True)
        rows = []
        for i, h in enumerate(hits[:4], 1):
            txt = fetch_desc(h["번호"])
            pl = param_lines(txt)
            h["명세서_길이"] = len(txt)
            h["수치줄"] = len(pl)
            if txt:
                fn = safe_name(f"{i:02d}_{h['번호']}_{h['제목']}")[:80] + ".txt"
                with open(os.path.join(pdir, fn), "w", encoding="utf-8") as f:
                    f.write(f"{h['제목']}\n{h['번호']} | {h['출원인']} | {h['공개일']}\n{h['url']}\n\n"
                            + "=" * 60 + "\n" + txt)
                h["파일"] = fn
            rows.append(h)
            time.sleep(3)

        lines = [f"# {d} — 제조사 특허 ({assignee})", "",
                 "포털에 없는 공정 파라미터를 찾기 위해 제조사 특허 명세서를 모았다.",
                 "특허는 **그 제조사의 기술 일반**이지 이 설비의 실제 설정값이 아니다. 파라미터 종류·범위 참고용.", "",
                 "| # | 번호 | 제목 | 공개일 | 명세서(자) | 수치줄 |", "|---|---|---|---|---|---|"]
        for i, h in enumerate(rows, 1):
            lines.append(f"| {i} | [{h['번호']}]({h['url']}) | {h['제목'][:50]} | {h['공개일']} "
                         f"| {h.get('명세서_길이',0):,} | {h.get('수치줄',0)} |")
        with open(os.path.join(pdir, "목록.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        n_par = sum(h.get("수치줄", 0) for h in rows)
        summary.append({"no": no, "출원인": assignee, "건수": len(rows), "수치줄_합": n_par})
        print(f"[{no:2}] {assignee} / {keyword}: {len(rows)}건 / 수치줄 합 {n_par}")

    with open(os.path.join(OUT_DIR, "_patent_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n총", sum(s.get("건수", 0) for s in summary), "건")


if __name__ == "__main__":
    main()
