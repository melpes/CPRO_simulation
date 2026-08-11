"""i-Tube·ZEUS 수집 결과를 하나의 인덱스 마크다운으로 정리한다."""

import json
import os
import re
import sys

import openpyxl

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
XLSX = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\KETI-FAB\2. 보유장비리스트_스마트_업데이트v2.xlsx"
INDEX = os.path.join(OUT_DIR, "README.md")

ITUBE_VIEW = "https://www.itube.or.kr/aplct/equipSrch/sharingView.do?g_menu_id=MNID210100&equip_no="
ZEUS_READ = "https://www.zeus.go.kr/search/equip/read/"


def load_excel():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["01-장비현황 및 실적"]
    rows = []
    for r in ws.iter_rows(min_row=4, max_row=47, max_col=9, values_only=True):
        if not r[0]:
            continue
        rows.append({"국문명": r[0], "영문명": r[1], "자산번호": r[3], "제작사": r[4], "모델명": r[7]})
    return rows


def folder_files(idx, kname):
    d = os.path.join(OUT_DIR, f"{idx:02d}_" + re.sub(r'[\\/:*?"<>|]', "_", kname).strip())
    if not os.path.isdir(d):
        return d, []
    files = [f for f in sorted(os.listdir(d)) if not f.startswith("_")]
    return d, files


NOISE = re.compile(
    r"정보를 제공하는 테이블입니다|^정보조회$|^\s*$"
    r"|^(통합검색|메인|본문|시설장비 조회|장비 정보 테이블|장비담당자정보"
    r"|QR코드출력|페이지인쇄|프린트하기|장비 QR코드 출력|장비QR코드"
    r"|예약 및 상담 신청하러 가기|위치보기)$"
)


def write_equip_md(folder, idx, row, z, t):
    """장비 하나의 두 포털 게시 내용을 사람이 읽는 형태로 남긴다."""
    out = [f"# {idx}. {row['국문명']} ({row['영문명']})", ""]
    out += ["## 엑셀 원장", "",
            f"- 제작사: {row['제작사']}", f"- 모델명: {row['모델명']}",
            f"- 고정자산관리번호: {row['자산번호']}", ""]

    out += ["## ZEUS 게시 내용", ""]
    if z.get("zeus_id"):
        out.append(f"출처: {ZEUS_READ}{z['zeus_id']}")
        out.append("")
        body = z.get("zeus_본문", "")
        for ln in body.split("\n"):
            ln = ln.strip()
            if ln and not NOISE.search(ln):
                out.append(ln)
    else:
        out.append(z.get("상태", "미확인"))
    out.append("")

    out += ["## i-Tube 게시 내용", ""]
    if t.get("itube_epn"):
        out.append(f"출처: {ITUBE_VIEW}{t['itube_epn']}")
        out.append("")
        for k, v in (t.get("itube_정보") or {}).items():
            if v and str(v).strip():
                out.append(f"- {k}: {str(v).strip()}")
        for f in t.get("매뉴얼_첨부", []):
            out.append(f"- 매뉴얼 첨부: {f.get('파일명')} ({f.get('크기',0):,} bytes)")
    else:
        out.append(t.get("상태", "미확인"))
    out.append("")

    with open(os.path.join(folder, "정보.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    xl = load_excel()
    itube = {e["no"]: e for e in json.load(open(os.path.join(OUT_DIR, "_itube_mapping.json"), encoding="utf-8"))}
    zeus = {e["no"]: e for e in json.load(open(os.path.join(OUT_DIR, "_zeus_mapping.json"), encoding="utf-8"))}

    lines = []
    lines.append("# KETI FAB 보유장비 — i-Tube·ZEUS 포털 수집")
    lines.append("")
    lines.append("`2. 보유장비리스트_스마트_업데이트v2.xlsx` 의 장비 44건을 두 포털에서 조회해 "
                 "게시 정보와 공개 다운로드 파일을 모은 결과다. 로그인이 필요한 자료는 받지 않았다.")
    lines.append("")
    lines.append("| 포털 | 주소 | 성격 |")
    lines.append("|---|---|---|")
    lines.append("| ZEUS 장비활용종합포털 | https://www.zeus.go.kr | 국가연구시설장비 등록·예약 (NFEC 운영) |")
    lines.append("| i-Tube | https://www.itube.or.kr | 산업기술개발장비 공동이용시스템 (KIAT 운영) |")
    lines.append("")

    n_z = sum(1 for e in zeus.values() if e.get("zeus_id"))
    n_i = sum(1 for e in itube.values() if e.get("itube_epn"))
    n_pdf = sum(len(e.get("매뉴얼_첨부", [])) for e in itube.values())
    lines.append(f"- ZEUS 등록 확인: **{n_z}/44** 건")
    lines.append(f"- i-Tube 등록 확인: **{n_i}/44** 건")
    lines.append(f"- 내려받은 매뉴얼 PDF: **{n_pdf}** 건 (i-Tube 만 첨부 제공, ZEUS 는 사진뿐)")
    lines.append("")
    lines.append("## 요약표")
    lines.append("")
    lines.append("| # | 장비명 | 제작사/모델 (엑셀) | ZEUS | i-Tube | 수집 파일 |")
    lines.append("|---|---|---|---|---|---|")

    detail = []
    for i, row in enumerate(xl, 1):
        z, t = zeus.get(i, {}), itube.get(i, {})
        d, files = folder_files(i, row["국문명"])
        zc = f"[{z['zeus_id']}]({ZEUS_READ}{z['zeus_id']})" if z.get("zeus_id") else "미등록"
        ic = f"[{t['itube_epn']}]({ITUBE_VIEW}{t['itube_epn']})" if t.get("itube_epn") else "미등록"
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        fcell = f"{len(files)}개" + (f" (PDF {len(pdfs)})" if pdfs else "")
        lines.append(f"| {i} | {row['국문명']} | {row['제작사']} / {row['모델명']} | {zc} | {ic} | {fcell} |")

        detail.append((i, row, z, t, os.path.basename(d), files))
        if os.path.isdir(d):
            write_equip_md(d, i, row, z, t)

    lines.append("")
    lines.append("## 장비별 상세")
    lines.append("")
    for i, row, z, t, dname, files in detail:
        lines.append(f"### {i}. {row['국문명']} ({row['영문명']})")
        lines.append("")
        lines.append(f"- 엑셀: 제작사 {row['제작사']} / 모델 {row['모델명']} / 고정자산 {row['자산번호']}")
        if z.get("zeus_id"):
            lines.append(f"- ZEUS: 등록번호 {z.get('zeus_등록번호','')} — {ZEUS_READ}{z['zeus_id']}")
        else:
            lines.append(f"- ZEUS: {z.get('상태','미확인')}")
        if t.get("itube_epn"):
            info = t.get("itube_정보", {})
            lines.append(f"- i-Tube: {t['itube_epn']} / i-Tube No. {info.get('i-Tube No.','')} — {ITUBE_VIEW}{t['itube_epn']}")
            if info.get("담당자"):
                lines.append(f"- 담당자: {info['담당자']}")
        else:
            lines.append(f"- i-Tube: {t.get('상태','미확인')}")
        sim = os.path.join(OUT_DIR, dname, "유사장비")
        if os.path.isdir(sim):
            n = len([f for f in os.listdir(sim) if f.endswith(".html")])
            lines.append(f"- 유사장비(타 기관 동일모델) {n}건: `docs/원본자료/keti-fab/포털수집/{dname}/유사장비`")
        if files:
            lines.append(f"- 수집 폴더: `docs/원본자료/keti-fab/포털수집/{dname}`")
            for f in files[:12]:
                lines.append(f"  - {f}")
            if len(files) > 12:
                lines.append(f"  - … 외 {len(files)-12}개")
        lines.append("")

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("생성:", INDEX)


if __name__ == "__main__":
    main()
