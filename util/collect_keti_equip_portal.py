"""KETI FAB 보유장비의 i-Tube 게시 정보와 다운로드 파일을 수집한다.

- i-Tube (itube.or.kr, 산업기술개발장비 공동이용시스템) 는 비로그인으로 상세 페이지 열람 가능
- 장비 매칭은 sharingList.do POST 검색(기관명=한국전자기술연구원) 결과와 엑셀을 대조해 미리 확정한 EPN 번호를 사용
"""

import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

# ── 하드코딩 ─────────────────────────────────────────────────────────
OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
MAP_JSON = os.path.join(OUT_DIR, "_itube_mapping.json")

BASE = "https://www.itube.or.kr"
VIEW = BASE + "/aplct/equipSrch/sharingView.do"
LIST = BASE + "/aplct/equipSrch/sharingList.do"
MANUAL = BASE + "/unitc/equipuse/joinEquipUse/popupJoinEquipUseFileDown.do"
MANUAL_TYPE_CD = "D14001"
FILEDOWN = BASE + "/unitc/equipuse/myequip/fileDownMyEquip.do"
INST_NAME = "한국전자기술연구원"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 엑셀 44건 ↔ i-Tube EPN 번호 (browser 대조로 확정, '-' 는 i-Tube 미등록)
MAPPING = [
    ("광학현미경(CCD)", "EPN0001756"),
    ("항온 건조기", None),
    ("수명 측정 시스템", "EPN0001758"),
    ("2차원 단차 측정기", "EPN0001760"),
    ("IVL 측정 System", "EPN0001762"),
    ("접촉각 측정기", "EPN0001763"),
    ("스크라이버 장비", "EPN0001765"),
    ("브레이커 장비", "EPN0001764"),
    ("잉크젯 프린터 for PLED #1", "EPN0001757"),
    ("광학현미경 with UV", "EPN0001761"),
    ("3차원 형상 측정기", "EPN0001766"),
    ("두께측정기", "EPN0001771"),
    ("잉크젯 프린터 for PLED #2", "EPN0001767"),
    ("입도분석기", "EPN0003702"),
    ("점도계", "EPN0184713"),
    ("분산 안정성 측정기", "EPN0003703"),
    ("기판세정기(수용액크리너)", "EPN0003709"),
    ("현상장비", "EPN0003706"),
    ("엣쳐/스트리퍼", "EPN0003708"),  # i-Tube 등록명은 "에처/스트립퍼"
    ("스크린프린터", "EPN0003710"),
    ("마스크얼라이너", "EPN0003711"),
    ("자외선 클리너", "EPN0003712"),
    ("잉크젯 프린터(lab)", "EPN0003713"),
    ("유기증착기", "EPN0001330"),
    ("면저항측정기", "EPN0003705"),
    ("박막증착장비", "EPN0001308"),
    ("화학 습식 증착(CBD)", "EPN0005526"),
    ("열화상카메라", "EPN0016939"),
    ("발광균일도측정시스템", "EPN0007651"),
    ("잉크젯프린터(lab #2)", "EPN0007652"),
    ("리버스 옵셋 프린터", "EPN0021012"),
    ("휘도계", None),
    ("임피던스 분석기", None),  # PARSTAT 4000 은 i-Tube 미등록(전주 소재 동일 장비 없음)
    ("스핀디벨로퍼", None),
    ("유기스트리퍼", "EPN0202245"),
    ("유기증착 마스크 정렬모듈", "EPN0202247"),
    ("주사전자현미경", "EPN0001755"),
    ("주사 탐침 현미경", "EPN0001769"),
    ("표면분석기", "EPN0003704"),
    ("듀얼빔 이온집속장치", "EPN0001352"),
    ("프로브스테이션", "EPN0005528"),
    ("마스크 얼라이너(8인치)", None),  # EPN0003711 은 21번(코디엠) 레코드 — 8인치 신규분은 i-Tube 미등록
    ("스핀 트랙 시스템", "EPN0242129"),
    ("PEALD", None),
]

# ── 세션 ─────────────────────────────────────────────────────────────
sess = requests.Session()
sess.headers["User-Agent"] = UA


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


# ── i-Tube 검색: 장비명으로 EPN 보정 ────────────────────────────────
def search_epn(keyword):
    body = {"search_value": keyword, "search_cpny_nm": INST_NAME, "pageIndex": "1"}
    r = sess.post(LIST, data=body, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("ul.table-list-body-3rd > li a.list_item"):
        m = re.search(r"EPN\d+", a.get("onclick") or "")
        head = a.select_one(".table-list-header-3rd p")
        ps = [p.get_text(strip=True) for p in a.select(".detail-info-3rd p")]
        out.append({
            "epn": m.group(0) if m else None,
            "name": head.get_text(strip=True) if head else "",
            "maker": ps[0].replace("제작사 :", "").strip() if len(ps) > 0 else "",
            "model": ps[1].replace("모델명 :", "").strip() if len(ps) > 1 else "",
            "org": ps[2] if len(ps) > 2 else "",
        })
    return out


# ── i-Tube 상세 파싱 ─────────────────────────────────────────────────
def parse_view(html):
    soup = BeautifulSoup(html, "html.parser")
    rec = {}

    hdr = soup.select_one(".view-card-header-3rd dl")
    if hdr:
        dd, dt = hdr.find("dd"), hdr.find("dt")
        rec["영문명"] = dd.get_text(strip=True) if dd else ""
        rec["국문명"] = dt.get_text(strip=True) if dt else ""
    st = soup.select_one(".view-card-header-3rd .badge-state-3rd")
    rec["가동상태"] = st.get_text(strip=True) if st else ""

    for li in soup.select(".view-card-body-3rd li"):
        em = li.find("em")
        sp = li.find("span")
        if em and sp:
            rec[em.get_text(strip=True)] = sp.get_text(" ", strip=True)

    for li in soup.select("ul.falling-table-3rd > li"):
        blocks = li.select("div") or [li]
        for b in blocks:
            sp, p = b.find("span"), b.find("p")
            if sp and p:
                rec[sp.get_text(strip=True)] = p.get_text("\n", strip=True)

    imgs = []
    for img in soup.select("img[src^='/equipimg/']"):
        imgs.append(BASE + img["src"])
    rec["_images"] = sorted(set(imgs))

    btn = soup.select_one("#btn_manual")
    rec["_manual_button"] = bool(btn) and "hidden" not in (btn.get("class") or [])
    return rec


def fetch_manual(epn, folder):
    """매뉴얼 팝업에서 첨부파일(EPF...)을 찾아 내려받는다."""
    r = sess.get(MANUAL, params={"g_menu_id": "", "equip_no": epn,
                                 "equip_file_type_cd": MANUAL_TYPE_CD}, timeout=30)
    if r.status_code != 200 or not r.text.strip():
        return []
    with open(os.path.join(folder, "_manual_popup.html"), "w", encoding="utf-8") as f:
        f.write(r.text)

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a[id^='filedown_']"):
        efn = a["id"][len("filedown_"):]
        td = a.find_parent("td") or a.parent
        label = td.get_text(" ", strip=True) if td else efn
        d = sess.get(FILEDOWN, params={"g_menu_id": "", "equip_file_no": efn}, timeout=120)
        if d.status_code != 200 or not d.content:
            out.append({"파일번호": efn, "파일명": label, "저장": "실패"})
            continue
        # Content-Disposition 의 파일명은 EUC-KR 바이트가 latin-1 로 실려 온다
        fname = label
        cd = d.headers.get("Content-Disposition", "")
        m = re.search(r'filename="([^"]+)"', cd)
        if m:
            try:
                fname = m.group(1).encode("latin-1").decode("euc-kr")
            except Exception:
                fname = m.group(1)
        fname = safe_name(fname)
        with open(os.path.join(folder, fname), "wb") as f:
            f.write(d.content)
        out.append({"파일번호": efn, "파일명": fname, "크기": len(d.content), "저장": "완료"})
    return out


def download(url, folder, fname=None):
    try:
        r = sess.get(url, timeout=60)
        if r.status_code != 200 or not r.content:
            return None
        name = fname or safe_name(url.split("/")[-1].split("?")[0])
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(r.content)
        return name
    except Exception as e:
        return f"ERROR: {e}"


# ── 실행 ─────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT_DIR, exist_ok=True)
    result = []

    for idx, (kname, epn) in enumerate(MAPPING, 1):
        entry = {"no": idx, "엑셀_국문명": kname, "itube_epn": epn}

        if not epn:
            hits = search_epn(kname)
            entry["itube_검색결과"] = hits[:5]
            entry["상태"] = "i-Tube 미등록(추정)" if not hits else "후보만 존재"
            result.append(entry)
            print(f"[{idx:2}] {kname}: 미매칭 (후보 {len(hits)})")
            continue

        folder = os.path.join(OUT_DIR, f"{idx:02d}_{safe_name(kname)}")
        os.makedirs(folder, exist_ok=True)

        r = sess.get(VIEW, params={"g_menu_id": "MNID210100", "equip_no": epn}, timeout=30)
        with open(os.path.join(folder, "_itube_view.html"), "w", encoding="utf-8") as f:
            f.write(r.text)

        rec = parse_view(r.text)
        entry["itube_url"] = f"{VIEW}?g_menu_id=MNID210100&equip_no={epn}"
        entry["itube_정보"] = {k: v for k, v in rec.items() if not k.startswith("_")}

        saved = []
        for u in rec["_images"]:
            n = download(u, folder)
            if n:
                saved.append(n)
        entry["다운로드_이미지"] = saved

        entry["매뉴얼_첨부"] = fetch_manual(epn, folder)

        with open(os.path.join(folder, "_itube.json"), "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

        result.append(entry)
        print(f"[{idx:2}] {kname} -> {epn} / 이미지 {len(saved)}개 / 매뉴얼 {len(entry['매뉴얼_첨부'])}개")
        time.sleep(0.3)

    with open(MAP_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {MAP_JSON}")


if __name__ == "__main__":
    main()
