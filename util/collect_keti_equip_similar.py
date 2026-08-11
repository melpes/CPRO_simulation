"""ZEUS 예약 페이지의 '동일모델 장비목록'을 각 설비 폴더의 유사장비/ 하위로 수집한다.

설비 폴더 바로 하위에는 그 설비 자신의 자료만 두고,
다른 기관의 동일모델 장비는 전부 유사장비/ 안으로 넣는다.
"""

import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_keti_equip_zeus as Z  # noqa: E402

OUT_DIR = Z.OUT_DIR
RESV_READ = Z.BASE + "/resv/equip/read/"
CLOUD_READ = Z.BASE + "/cloud/resvEq/read/"
SIM_DIR = "유사장비"

# 동일모델 탭이 비어 있으나 제조사 검색으로 확보한 유사장비 (등록장비 상세 id)
# 44번 씨엔원 PEALD 는 KETI 보유분이 ZEUS 미등록이라 동일 제조사 타 기관 레코드를 대신 모은다
EXTRA_SIMILAR = {
    # 모델명 스윕으로 찾은 타 기관 동일모델 (제작사·모델명 일치 확인분만)
    # A320(항공기)·120L 처럼 모델명이 우연히 겹친 오탐은 제외했다
    4: [("20121018000000155613", "표면조도계 (삼성SDI, Tencor P-16+)"),
        ("20100105000000051951", "박막단차 측정기 (한국생산기술연구원, Tencor P-16+)")],
    5: [("20250513000000292372", "극저온 반도체 전기광학물성 분석 시스템 (경상국립대, M6100)"),
        ("20110114000000095260", "IVL 분석 장치 (금호전기, M6100)")],
    12: [("20241107000000286635", "박막두께측정기 (서울대 산학협력단, 케이맥 ST-4000)")],
    14: [("20130312000000161054", "입도분석기 (송강산업, Nanotrac NPA 252)"),
         ("20110125000000099832", "입도분석기 (잉크테크, Nanotrac NPA 252)")],
    15: [("20120726000000151034", "원통형점도계 ((재)홍천메디칼허브연구소, DV-II Pro)"),
         ("20130109000000159266", "디지털 회전형 점도계 ((재)강원테크노파크, DV-II Pro)"),
         ("20140512000000172754", "디지털점도계 ((주)아모텍, DV-II Pro)")],
    23: [("20150610000000191915", "재료프린터 (한국표준과학연구원, DMP-2831)"),
         ("20141231000000183780", "머티리얼 프린터 (서강대, DMP-2831)"),
         ("20160108000000197077", "인쇄전자용 프린터 (선문대, DMP-2831)")],
    25: [("20110131000000103264", "면저항측정기 ((재)대구테크노파크, CMT-SR3000S)"),
         ("20230314000000271594", "면저항 측정기 (충남테크노파크, CMT-SR3000S)")],
    33: [("20150309000000188731", "분극시험기 (한국생산기술연구원, PARSTAT 4000)"),
         ("20161227000000206747", "물분해 광전극 측정용 전기화학분석기 (광주과학기술원, PARSTAT 4000)")],
    38: [("20130520000000163389", "원자간력 현미경 ((주)코오롱중앙기술원, N-Tracer)"),
         ("20110317000000109417", "주사탐침현미경 컨트롤러 (한국표준과학연구원, N-Tracer)"),
         ("20100809000000060620", "주사탐침현미경 (충북대, N-Tracer)")],
    39: [("20200206000000244861", "광전자 분광기 (경희대 국제캠퍼스, AC-2)"),
         ("20200605000000247454", "일함수 측정기 (한국생산기술연구원, AC-2)")],
    40: [("20120926000000154545", "집속이온빔장치 (울산과학기술원, Quanta 3D FEG)"),
         ("20130906000000167407", "TEM샘플 제작 시스템 FIB (한국과학기술원, Quanta 3D FEG)"),
         ("20100426000000053375", "집속이온빔 II (한국나노기술원)")],
    41: [("20171130000000212613", "OLED전기광학측정시스템 (구미전자정보기술원, MST-12000C)")],
    # NTIS 구축과제에서 확인 — 나노기술집적센터 광주(한국생산기술연구원) 보유분.
    # KETI 전주와 같은 공정·같은 제조사라 파라미터 종류 참고가 된다.
    26: [("20250512000000292342", "스퍼터 증착기 (강원대 산학협력단) — Sputter 챔버 참고"),
         ("20260508000000303012", "12인치 스퍼터 시스템 (차세대융합기술연구원) — Sputter 챔버 참고"),
         ("20260226000000300935", "마그네트론 스퍼터 (순천향대 산학협력단, DSKPT-04-03L) — Sputter 챔버 참고"),
         ("20260326000000302079", "저온 플라즈마 화학기상 증착 장비 TEOS (한국표준과학연구원, PD-100ST) — PECVD 챔버 참고"),
         ("20251224000000298087", "마이크로파 플라즈마 화학기상 증착 시스템 (국립부경대, 연사이언스 MPECVD-R60) — PECVD 챔버 참고"),
         ("20260209000000300411", "유도결합 플라즈마 반응성 이온 식각 장비 (부산대, JICP-2000) — Dry Etcher 챔버 참고"),
         ("20260709000000304321", "유도결합플라즈마 식각 장비 (영남대 산학협력단, VITA6-HVICP) — Dry Etcher 챔버 참고"),
         ("20241227000000288253", "반도체 미세 식각 장비 (국립강릉원주대, 다다코리아 DIEC-1200) — Dry Etcher 챔버 참고"),
         ("20260121000000299709", "열증착기 (울산과학기술원, 진공증착기) — Thermal Evaporator 챔버 참고"),
         ("20100105000000051923", "스퍼터 (한국생산기술연구원, 셀코스 Cluster Type Sputtering)"),
         ("20071106000000000280", "유도결합형 플라즈마 화학기상증착장치 (한국생산기술연구원, Bmr HiDep)"),
         ("20090914000000045265", "전자빔 증착기 (한국생산기술연구원, 셀코스 E-Beam Evaporator)")
         ],
    17: [("20091019000000047209", "습식세정장치 (한국생산기술연구원, 아티스 Wet Station)")],
    34: [("20071126000000000847", "감광액 도포기 (한국생산기술연구원, 에스브이에스 MSX2000)")],
    # 제조사명 스윕 — 모델명이 "개발장비"·"제작품"이라 모델 검색에 안 걸린 공정설비용
    # 같은 제조사의 같은 계열 장비만 담았다 (제작사명 대조로 확인)
    20: [("20170712000000210474", "스크린프린터 (한국전자통신연구원, Seria SSA-PC250-2C)")],
    21: [("20121221000000158808", "노광기 ((재)철원플라즈마산업기술연구원, 코디엠 MA-1200)")],
    24: [
         # Plasma Treatment Chamber 보강 — 플라즈마 표면처리 전용 장비
         ("20240423000000282700", "표면처리기 (전남대 산학협력단, 플라솔 PS-150) — 플라즈마 Plasma Chamber 참고"),
         ("20241120000000286969", "플라즈마 표면처리기 (충북대, 펨토사이언스 CIONE6-ICP-1MP) — 플라즈마 Plasma Chamber 참고"),
         ("20260105000000298784", "8inch 표면나노구조 플라즈마 처리 장치 (한국재료연구원, 엘에이티) — 플라즈마 Plasma Chamber 참고"),
         # Organic Chamber 보강 — 유기물 진공 열증착
         ("20251229000000298424", "유기진공열 증착기 (전남대 산학협력단, 제이벡 JVEVA-F30k3p) — 유기 Organic Chamber 참고"),
         ("20260609000000303640", "진공열 증착기 (경상국립대, 대동하이텍 DDHT-SB086) — 유기 Organic Chamber 참고"),
         ("20260319000000301792", "열증착기 및 글로브박스 (서강대, Glove-PVs) — Metal Chamber·Glove Box 참고"),
         ("20260121000000299709", "열증착기 (울산과학기술원) — Metal Chamber 참고"),
         ("20251230000000298493", "페로브스카이트 태양전지 클러스터 (성균관대, Perovskite RD Line) — 클러스터 구성 참고"),
         ("20100917000000063764", "OLED 증착 장비 (한국과학기술원, 선익시스템 Sunicel plus 100)"),
         ("20090108000000042316", "유기 태양전지용 증착설비 (한국생산기술연구원, 선익시스템 Sunicel plus 200 — 동일 모델)"),
         ("20110107000000093617", "유기증착기 (한국생산기술연구원, 선익시스템 Sunicel plus 200 — 동일 모델)")],
    19: [("20210802000000256845", "Wet station (한국화학연구원, 울텍 AquaChem) — 습식 식각·스트립 라인 참고")],
    35: [("20210802000000256845", "Wet station (한국화학연구원, 울텍 AquaChem) — 습식 식각·스트립 라인 참고"),
         ("20260105000000298767", "웨이퍼회전건조기 (서강대, 세미트로닉스 SD-1505S2) — 스핀 건조 참고"),
         ("20260226000000300904", "플라즈마 애싱 시스템 (국립한국해양대, 울텍 EURA-200) — PR 제거(애싱) 참고")],
    36: [],
    43: [("20260112000000299217", "12인치 완전자동 트랙시스템 (차세대융합기술연구원, 에스브이에스 MSX3000)"),
         ("20251001000000295198", "12인치 정렬노광 및 다중공정 시스템 (차세대융합기술연구원, 에스브이에스)"),
         ("20241209000000287501", "포토레지스트 트랙 시스템 (울산과학기술원, 에스브이에스 SSP200)"),
         ("20071126000000000847", "감광액 도포기 (한국생산기술연구원, 에스브이에스 MSX2000 — 상위 모델)")],
    42: [("20071106000000000279", "노광기 (한국생산기술연구원, Suss Microtec MA8 — 동일 계열)")
         ],
    44: [
        ("20260315000000301606", "플라즈마 강화 원자층 증착 장비 (씨엔원 6 Atomic Premium System)"),
        ("20250626000000293175", "플라즈마 원자층 증착기 (씨엔원)"),
        ("20251218000000297673", "원자층증착기 (씨엔원 Atomic Premium)"),
        ("20240920000000285299", "원자층 증착 장비 (씨엔원 6 Atomic Premium System)")
    ],
}


def cell(s):
    """표 셀에 들어갈 문자열에서 개행·탭을 없앤다."""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def page_text(html):
    s = BeautifulSoup(html, "html.parser")
    art = s.find("article") or s
    return re.sub(r"\n{2,}", "\n", art.get_text("\n", strip=True))


def parse_same_list(html):
    """예약 페이지 HTML 에서 동일모델 장비목록 행을 뽑는다."""
    s = BeautifulSoup(html, "html.parser")
    sec = s.find(id="info_same")
    out = []
    if not sec:
        return out
    for tr in sec.select("tbody tr"):
        a = tr.find("a")
        if not a:
            continue
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        href = a.get("href") or ""
        m = re.search(r"/cloud/resvEq/read/([A-Za-z0-9\-_]+)\?cloudId=([A-Za-z0-9\-_]+)", href)
        out.append({
            "장비명": a.get_text(strip=True),
            "보유기관": tds[1] if len(tds) > 1 else "",
            "지역": tds[2] if len(tds) > 2 else "",
            "이용료": tds[3] if len(tds) > 3 else "",
            "resv_id": m.group(1) if m else None,
            "cloud_id": m.group(2) if m else None,
        })
    return out


def save_similar(folder, idx, name, html, kind):
    """유사장비 상세 1건을 저장하고 요약 정보를 돌려준다."""
    base = Z.safe_name(f"{idx:02d}_{name}")[:70]
    with open(os.path.join(folder, base + ".html"), "w", encoding="utf-8") as f:
        f.write(html)
    txt = page_text(html)
    with open(os.path.join(folder, base + ".txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    i = txt.find("특성")
    j = txt.find("용도설명")
    spec = txt[i + 2:j].strip() if 0 < i < j else ""
    return {"파일": base, "출처": kind, "특성_줄수": len([l for l in spec.split("\n") if l.strip()])}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    Z.sso_bootstrap()
    summary = []

    # 폴더가 증착/포토/프린터/기타 로 한 단계 더 묶여 있어 두 층을 다 훑는다
    targets = []
    for g in sorted(os.listdir(OUT_DIR)):
        gp = os.path.join(OUT_DIR, g)
        if not os.path.isdir(gp):
            continue
        if g[:2].isdigit():
            targets.append((g, gp))
            continue
        for sub in sorted(os.listdir(gp)):
            sp = os.path.join(gp, sub)
            if os.path.isdir(sp) and sub[:2].isdigit():
                targets.append((sub, sp))

    for d, folder in targets:
        no = int(d[:2])
        resv_html = os.path.join(folder, "_zeus_resv.html")

        rows = []
        if os.path.exists(resv_html):
            rows = parse_same_list(open(resv_html, encoding="utf-8").read())
        extra = EXTRA_SIMILAR.get(no, [])
        if not rows and not extra:
            continue

        sim = os.path.join(folder, SIM_DIR)
        os.makedirs(sim, exist_ok=True)
        saved = []

        for i, r in enumerate(rows, 1):
            if not r["resv_id"]:
                continue
            rr = Z.zget(CLOUD_READ + r["resv_id"], cloudId=r["cloud_id"] or "")
            info = save_similar(sim, i, r["장비명"], rr.text, "동일모델 장비목록")
            info.update(r)
            saved.append(info)
            time.sleep(0.2)

        for i, (zid, label) in enumerate(extra, len(saved) + 1):
            rr = Z.zget(Z.READ + zid)
            # 상세 사양(특성)은 예약 페이지에만 있으므로 있으면 그쪽을 저장한다
            m = re.search(r"/resv/equip/read/([A-Za-z0-9\-]+)", rr.text)
            org = re.search(r"보유기관명\s*</th>\s*<td[^>]*>\s*([^<]+)", rr.text)
            html = Z.zget(RESV_READ + m.group(1)).text if m else rr.text
            info = save_similar(sim, i, label, html, "제조사 검색(동일 제조사)")
            info.update({"장비명": label, "zeus_id": zid,
                         "보유기관": org.group(1).strip() if org else ""})
            saved.append(info)
            time.sleep(0.2)

        lines = [f"# {d} — 유사장비", "",
                 "이 폴더는 **다른 기관이 보유한 동일모델·동일제조사 장비**다. 대상 설비 본체 자료가 아니다.",
                 "파라미터 종류(스키마) 참고용으로만 쓰고, 수치를 대상 설비 값으로 옮기지 말 것.", "",
                 "| # | 장비명 | 보유기관 | 지역 | 이용료 | 특성 줄수 | 출처 |", "|---|---|---|---|---|---|---|"]
        for k, s in enumerate(saved, 1):
            lines.append(f"| {k} | {cell(s.get('장비명'))} | {cell(s.get('보유기관'))} | {cell(s.get('지역'))} "
                         f"| {cell(s.get('이용료'))} | {s.get('특성_줄수',0)} | {cell(s.get('출처'))} |")
        with open(os.path.join(sim, "목록.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        summary.append({"폴더": d, "유사장비": len(saved)})
        print(f"{d:34} 유사장비 {len(saved)}건")

    with open(os.path.join(OUT_DIR, "_similar_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n총", sum(s["유사장비"] for s in summary), "건")


if __name__ == "__main__":
    main()
