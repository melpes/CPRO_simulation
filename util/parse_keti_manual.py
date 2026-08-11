"""설비 매뉴얼 PDF 에서 유닛별 사양 항목을 뽑는다.

매뉴얼 사양표는 '유닛 이름' 아래에 '항목  값' 이 이어지는 구조다.
콜론이 없어서 포털 파서(split_pair)로는 안 잡히므로 별도로 처리한다.
"""

import glob
import json
import os
import re
import sys

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
CACHE = os.path.join(OUT_DIR, "_manual_params.json")

# 유닛 머리글로 볼 줄 (사양표에서 그룹을 여는 줄)
UNIT_HEAD = re.compile(
    r"^\s*((?:[A-Z][A-Za-z0-9/\-\.]*\s+){0,3}"
    r"(?:Robot|Unit|Plate|Coater|Developer|Chamber|Module|Box|Stage|System|Port|Pump|Cabinet)"
    r"(?:\s*\([^)]*\))?(?:\s*-\s*\d+\s*Unit)?)\s*$")

# 값에 들어가면 사양으로 볼 단위
UNIT_TOKEN = (r"(?:℃|°C|rpm|RPM|sccm|Torr|mmHg|kgf|kPa|MPa|bar|VAC|V\b|A\b|KVA|kW|W\b|Hz"
              r"|mm|㎜|cm|㎝|um|㎛|µm|nm|inch|\"|ℓ/\s*min|l/min|scfm|sec|초|min|hrs?|WPH|Kg|%|pls)")
VAL = re.compile(r"\d[\d,\.\s~\-±≤≥<>/×\*x]*\s*" + UNIT_TOKEN)

NOISE = re.compile(r"^\s*(표\s*\d|그림\s*\d|[\d\s]+$|목\s*차|주의|경고|위험)")
# 사양표가 있는 쪽에만 적용한다 (부품목록·조작설명 쪽은 제외)
SPEC_PAGE = re.compile(r"Specification|Capabilit|Utility|Hook\s*-?\s*Up|사양|성능|제원", re.I)
# 부품목록(BOM) 쪽 — 볼트·스크류 규격이 사양으로 잡히는 것을 막는다
BOM = re.compile(r"BOLT|WRENCH|SCREW|WASHER|NUT|SUS304[A-Z]", re.I)


def parse(path, max_pages=None):
    import pypdf
    r = pypdf.PdfReader(path)
    pages = r.pages if max_pages is None else r.pages[:max_pages]
    rows = []
    for pno, pg in enumerate(pages, 1):
        text = pg.extract_text() or ""
        if not SPEC_PAGE.search(text):        # 사양표가 없는 쪽은 건너뛴다
            continue
        if len(BOM.findall(text)) >= 3:       # 부품목록 쪽 제외
            continue
        unit = "(설비 공통)"                    # 유닛 머리글은 쪽을 넘기지 않는다
        for raw in text.split("\n"):
            ln = re.sub(r"\s+", " ", raw).strip()
            if not ln or len(ln) > 160 or NOISE.match(ln) or BOM.search(ln):
                continue
            h = UNIT_HEAD.match(ln)
            if h and not VAL.search(ln):
                unit = h.group(1).strip()
                continue
            m = VAL.search(ln)
            if not m:
                continue
            name = ln[:m.start()].strip(" .:·-")
            value = ln[m.start():].strip()
            if not name or len(name) > 60 or len(name) < 2:
                continue
            rows.append({"유닛": unit, "파라미터명": name, "값": value[:120], "쪽": pno})
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = {}
    # 폴더가 증착/포토/프린터/기타 로 한 단계 더 묶여 있어 두 층을 다 훑는다
    folders = []
    for g in sorted(os.listdir(OUT_DIR)):
        gp = os.path.join(OUT_DIR, g)
        if not os.path.isdir(gp):
            continue
        if g[:2].isdigit():
            folders.append((g, gp))
            continue
        for d in sorted(os.listdir(gp)):
            dp = os.path.join(gp, d)
            if os.path.isdir(dp) and d[:2].isdigit():
                folders.append((d, dp))

    for d, folder in folders:
        # 설비 최상위의 PDF 만 매뉴얼 (논문 PDF 는 논문/ 하위에 있다)
        pdfs = [p for p in glob.glob(os.path.join(folder, "*.pdf"))]
        if not pdfs:
            continue
        rows = []
        for p in pdfs:
            try:
                got = parse(p)
            except Exception as e:
                print(f"{d:30} {os.path.basename(p)[:34]:36} 파싱실패 {str(e)[:30]}")
                continue
            for g in got:
                g["파일"] = os.path.basename(p)
            rows += got
        if not rows:
            continue
        # 중복 제거
        seen, keep = set(), []
        for g in rows:
            k = (g["유닛"], g["파라미터명"], g["값"])
            if k in seen:
                continue
            seen.add(k)
            keep.append(g)
        out[d] = keep
        units = sorted({g["유닛"] for g in keep})
        print(f"{d:30} {len(keep):>4}건 / 유닛 {len(units)}개")
        for u in units[:8]:
            n = sum(1 for g in keep if g["유닛"] == u)
            print(f"      {u[:44]:46} {n}건")

    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {CACHE}")


if __name__ == "__main__":
    main()
