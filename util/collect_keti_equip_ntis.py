"""설비를 구축한 국가R&D 과제를 NTIS 에서 찾아 각 설비 폴더의 NTIS/ 하위에 저장한다.

특허·논문은 '그 제조사의 기술 일반'이거나 '그 공정을 쓴 다른 연구'지만,
장비 구축 과제의 보고서는 **이 설비 그 자체**의 문서다.
과제정보(세부과제명·주관기관·연구책임자·수행기간)는 ZEUS 등록장비 상세에 이미 실려 있어 그것을 검색 키로 쓴다.
"""

import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
ZEUS_JSON = os.path.join(OUT_DIR, "_zeus_mapping.json")
NTIS_DIR = "NTIS"

BASE = "https://www.ntis.go.kr"
SEARCH = BASE + "/ThSearchProjectList.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

sess = requests.Session()
sess.headers["User-Agent"] = UA


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


def boot():
    sess.get(BASE + "/ThMain.do", timeout=30)


def project_info(zeus_body):
    """ZEUS 본문에서 시설장비 과제정보를 뽑는다."""
    d = {}
    for k in ["세부과제명", "세부사업명", "주관기관", "연구책임자", "과제수행기간"]:
        m = re.search(r"\n" + k + r"\n([^\n]+)", "\n" + zeus_body)
        d[k] = m.group(1).strip() if m else ""
    return d


def search_projects(keyword, leader="", n=10):
    r = sess.get(SEARCH, params={"searchWord": keyword, "pageSize": "30"}, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for li in soup.select("ul.result-list > li"):
        cb = li.select_one("input[type=checkbox]")
        pid = cb.get("value") if cb else ""
        txt = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
        a = li.find("a", href=re.compile(r"pjtInfo\.do"))
        title = a.get_text(" ", strip=True) if a else txt[:80]
        year = (re.search(r"\b(19|20)\d{2}\b", txt) or [""])[0]
        # 연구내용 블록 (있으면 사양·구축 내용이 들어 있다)
        body = txt.split("연구내용")[-1] if "연구내용" in txt else ""
        out.append({
            "과제고유번호": pid,
            "과제명": re.sub(r"\s+", " ", title)[:120],
            "연도": year,
            "url": f"{BASE}/project/pjtInfo.do?pjtId={pid}" if pid else "",
            "요약": body.strip()[:1200],
            "_raw": txt[:600],
        })
        if len(out) >= n:
            break
    if leader:
        pref = [o for o in out if leader in o["_raw"]]
        if pref:
            return pref + [o for o in out if o not in pref]
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    boot()
    zeus = {e["no"]: e for e in json.load(open(ZEUS_JSON, encoding="utf-8"))}
    folders = {int(d[:2]): d for d in os.listdir(OUT_DIR)
               if os.path.isdir(os.path.join(OUT_DIR, d)) and d[:2].isdigit()}

    cache = {}       # 같은 과제는 한 번만 검색한다
    summary = []

    for no in sorted(folders):
        e = zeus.get(no, {})
        if not e.get("zeus_id"):
            continue
        p = project_info(e.get("zeus_본문", ""))
        if not p["세부과제명"]:
            continue

        key = (p["세부과제명"], p["연구책임자"])
        if key not in cache:
            cache[key] = search_projects(p["세부과제명"], p["연구책임자"])
            time.sleep(1.0)
        hits = cache[key]

        d = folders[no]
        ndir = os.path.join(OUT_DIR, d, NTIS_DIR)
        os.makedirs(ndir, exist_ok=True)

        with open(os.path.join(ndir, "과제정보.json"), "w", encoding="utf-8") as f:
            json.dump({"설비": d, "ZEUS_과제정보": p, "NTIS_검색결과": hits}, f,
                      ensure_ascii=False, indent=2)

        lines = [f"# {d} — 구축 과제 (NTIS)", "",
                 "## ZEUS 에 실린 과제정보", "",
                 f"- 세부과제명: {p['세부과제명']}",
                 f"- 세부사업명: {p['세부사업명']}",
                 f"- 주관기관: {p['주관기관']}",
                 f"- 연구책임자: {p['연구책임자']}",
                 f"- 과제수행기간: {p['과제수행기간']}", "",
                 "## NTIS 검색 결과", "",
                 "보고서 원문은 NTIS 로그인·승인이 필요할 수 있다. 아래는 공개 요약이다.", "",
                 "| # | 과제고유번호 | 과제명 | 연도 |", "|---|---|---|---|"]
        for i, h in enumerate(hits[:10], 1):
            link = f"[{h['과제고유번호']}]({h['url']})" if h["url"] else h["과제고유번호"]
            lines.append(f"| {i} | {link} | {h['과제명'][:60]} | {h['연도']} |")
        for i, h in enumerate(hits[:5], 1):
            if h["요약"]:
                lines += ["", f"### {i}. {h['과제명'][:60]}", "", h["요약"]]
        with open(os.path.join(ndir, "과제.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        summary.append({"no": no, "설비": d, "세부과제명": p["세부과제명"], "NTIS건수": len(hits)})
        print(f"[{no:2}] {d[3:]:26} {p['세부과제명'][:34]:36} NTIS {len(hits)}건")

    with open(os.path.join(OUT_DIR, "_ntis_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n고유 과제 {len(cache)}개 / 설비 {len(summary)}건")


if __name__ == "__main__":
    main()
