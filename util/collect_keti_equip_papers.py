"""KETI 저자 논문에서 공정 조건을 찾아 각 설비 폴더의 논문/ 하위에 저장한다.

포털(ZEUS·i-Tube)에는 설비 사양만 있고 실제 공정 조건(온도·rpm·시간·가스 유량)이 없다.
같은 설비를 쓴 KETI 논문의 실험 파트에는 그 조건이 적혀 있는 경우가 있다.

출처는 OpenAlex (api.openalex.org) — 무료 공개 API, 키 불필요.
"""

import json
import os
import re
import sys
import time

import requests

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
PAPER_DIR = "논문"
API = "https://api.openalex.org/works"
KETI = "I4210131650"  # Korea Electronics Technology Institute
MAILTO = "vegakangtaehui@gmail.com"

# 설비번호: (검색어, 폴더 표기)
TARGETS = {
    24: "organic evaporation OLED thermal deposition",
    26: "RF magnetron sputtering deposition thin film",
    19: "wet etching ITO patterning etchant electrode",
    17: "substrate cleaning wet process glass",
    18: "photoresist coating developing lithography",
    21: "mask aligner exposure photolithography",
    34: "photoresist development line width patterning",
    43: "spin coater track bake photoresist",
    20: "screen printing electrode paste",
    31: "reverse offset printing pattern",
    23: "inkjet printing functional ink drop",
    9: "inkjet printing OLED polymer light emitting",
    44: "atomic layer deposition plasma enhanced ALD",
    27: "chemical bath deposition",
    22: "UV ozone cleaning surface treatment",
    2: "drying temperature ink film",
    12: "thin film thickness spectroscopic",
    14: "particle size distribution nanoparticle dispersion",
    25: "transparent electrode sheet resistance",
    30: "material printer droplet",
    37: "scanning electron microscopy nanostructure",
}

# 공정 조건으로 볼 단위
UNIT = r"(°C|℃|rpm|RPM|sccm|Torr|mTorr|mbar|Pa\b|W\b|kW|mW|nm|µm|μm|um\b|mm|s\b|sec|min|h\b|hr|%|mM|M\b|mJ)"

sess = requests.Session()
sess.headers["User-Agent"] = f"keti-fab-research (mailto:{MAILTO})"


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


def inverted_to_text(inv):
    """OpenAlex 의 abstract_inverted_index 를 평문으로 되돌린다."""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def search(query, n=8):
    params = {
        "search": query,
        "filter": f"authorships.institutions.lineage:{KETI}",
        "per-page": n,
        "sort": "cited_by_count:desc",
        "mailto": MAILTO,
    }
    r = sess.get(API, params=params, timeout=40)
    if r.status_code != 200:
        return []
    out = []
    for w in r.json().get("results", []):
        ab = inverted_to_text(w.get("abstract_inverted_index"))
        loc = (w.get("primary_location") or {})
        out.append({
            "제목": w.get("display_name", ""),
            "연도": w.get("publication_year"),
            "저널": ((loc.get("source") or {}).get("display_name") or ""),
            "doi": w.get("doi") or "",
            "인용": w.get("cited_by_count", 0),
            "오픈액세스": (w.get("open_access") or {}).get("is_oa", False),
            "pdf": (loc.get("pdf_url") or ""),
            "초록": ab,
            "조건줄수": len(re.findall(r"\d+\s*" + UNIT, ab)),
        })
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    folders = {int(d[:2]): d for d in os.listdir(OUT_DIR)
               if os.path.isdir(os.path.join(OUT_DIR, d)) and d[:2].isdigit()}
    summary = []

    for no, q in sorted(TARGETS.items()):
        d = folders.get(no)
        if not d:
            continue
        rows = search(q)
        if not rows:
            print(f"[{no:2}] {d[3:]:26} 0건")
            summary.append({"no": no, "건수": 0})
            continue

        pdir = os.path.join(OUT_DIR, d, PAPER_DIR)
        os.makedirs(pdir, exist_ok=True)

        for i, w in enumerate(rows, 1):
            fn = safe_name(f"{i:02d}_{w['연도']}_{w['제목']}")[:80] + ".txt"
            with open(os.path.join(pdir, fn), "w", encoding="utf-8") as f:
                f.write(f"{w['제목']}\n{w['저널']} ({w['연도']}) | 인용 {w['인용']}\n"
                        f"{w['doi']}\n{w['pdf']}\n\n" + "=" * 60 + "\n" + w["초록"])

        lines = [f"# {d} — KETI 저자 논문", "",
                 f"검색어: `{q}` / 기관: 한국전자기술연구원 (OpenAlex)", "",
                 "설비 사양이 아니라 **그 설비로 돌린 공정의 조건**을 찾기 위한 자료다.",
                 "조건줄수는 초록에 수치+단위가 나온 횟수 — 본문(PDF)에 더 있다.", "",
                 "| # | 제목 | 연도 | 저널 | 인용 | 조건줄 | OA |", "|---|---|---|---|---|---|---|"]
        for i, w in enumerate(rows, 1):
            oa = f"[PDF]({w['pdf']})" if w["pdf"] else ("OA" if w["오픈액세스"] else "-")
            lines.append(f"| {i} | [{w['제목'][:55]}]({w['doi']}) | {w['연도']} | {w['저널'][:28]} "
                         f"| {w['인용']} | {w['조건줄수']} | {oa} |")
        with open(os.path.join(pdir, "목록.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        tot = sum(w["조건줄수"] for w in rows)
        summary.append({"no": no, "건수": len(rows), "조건줄_합": tot})
        print(f"[{no:2}] {d[3:]:26} {len(rows)}건 / 조건줄 {tot}")
        time.sleep(0.5)

    with open(os.path.join(OUT_DIR, "_paper_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n총", sum(s.get("건수", 0) for s in summary), "건")


if __name__ == "__main__":
    main()
