"""KETI FAB 보유장비의 ZEUS(장비활용종합포털) 게시 정보와 사진을 수집한다.

ZEUS 는 모든 페이지가 SSO 확인을 한 번 거친 뒤에야 본문을 내려준다.
- 1) ksso.zeus.go.kr/sso/user/login/link 로 연동 요청
- 2) www.zeus.go.kr/nsso/login_check_result.jsp 콜백
- 3) 이후 모든 요청에 sso_status=N 을 붙이면 비로그인 상태로 본문 열람 가능

장비 식별키는 i-Tube 상세에서 얻은 시설장비등록번호(NFEC-....) 를 쓴다.
"""

import json
import os
import re
import sys
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ── 하드코딩 ─────────────────────────────────────────────────────────
OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
ITUBE_JSON = os.path.join(OUT_DIR, "_itube_mapping.json")
ZEUS_JSON = os.path.join(OUT_DIR, "_zeus_mapping.json")

BASE = "https://www.zeus.go.kr"
SSO_LINK = "https://ksso.zeus.go.kr/sso/user/login/link"
AGT_ID = "nfec-zeus-java"
SEARCH = BASE + "/search"
READ = BASE + "/search/equip/read/"
INST_NAME = "한국전자기술연구원"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 등록번호 검색만으로는 어긋나는 항목의 확정 매핑 (엑셀 제작사·모델명 대조로 확인)
# None = ZEUS 미등록으로 판단
ZEUS_OVERRIDE = {
    32: "20110118000000096358",   # 휘도계 Konica Minolta LS-110
    33: "20130620000000164560",   # 임피던스 분석기 Princeton Applied Research PARSTAT 4000
    42: "20260428000000302819",  # 마스크 얼라이너(8인치) Suss Microtec MA8 Gen4 (한글 "수스마이크로"로는 검색 안 됨)
    43: "20251216000000297522",   # 스핀 트랙 시스템 에스브이에스 MSX1000
    44: None,                     # PEALD 씨엔원 — KETI 보유분 ZEUS 검색 결과 없음
}

sess = requests.Session()
sess.headers["User-Agent"] = UA


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


def sso_bootstrap():
    tgt = BASE + "/search?rtn_method=GET"
    cb = BASE + "/nsso/login_check_result.jsp?rtn_url=" + quote(tgt, safe="")
    sess.post(SSO_LINK, data={"agt_id": AGT_ID, "agt_url": BASE, "redirect_url": cb}, timeout=30)
    sess.post(cb, data={"sso_code": "", "status": "N", "redirect_url": ""}, timeout=30)


def zget(url, **params):
    params["sso_status"] = "N"
    return sess.get(url, params=params, timeout=40)


# ── 검색 ─────────────────────────────────────────────────────────────
def search_ids(keyword):
    r = zget(SEARCH, keyword=keyword)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a[href*='/search/equip/read/']"):
        m = re.search(r"/search/equip/read/(\d+)", a.get("href") or "")
        if not m:
            continue
        txt = a.get_text(" ", strip=True)
        if m.group(1) not in [o["id"] for o in out]:
            out.append({"id": m.group(1), "title": txt})
    return out


# ── 상세 파싱 ────────────────────────────────────────────────────────
def parse_read(html):
    soup = BeautifulSoup(html, "html.parser")
    rec = {}

    art = soup.find("article") or soup
    text = art.get_text("\n", strip=True)
    rec["_본문"] = re.sub(r"\n{3,}", "\n\n", text)

    for dl in art.select("dl"):
        dt, dd = dl.find("dt"), dl.find("dd")
        if dt and dd:
            rec[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)
    for th in art.select("th"):
        td = th.find_next_sibling("td")
        if td:
            rec[th.get_text(strip=True)] = td.get_text("\n", strip=True)

    m = re.search(r"(NFEC-[\d\-]+)", html)
    rec["시설장비등록번호"] = m.group(1) if m else ""

    imgs = [BASE + s for s in re.findall(r'src="(/storage/images/equip/[^"]+)"', html)]
    rec["_images"] = sorted(set(i.replace("/.thumb/", "/") for i in imgs) | set(imgs))
    qr = re.search(r'src="(https://image-charts\.com/chart\?[^"]+)"', html)
    rec["_qr"] = qr.group(1) if qr else ""
    return rec


def download(url, folder, prefix="", fname=None):
    try:
        r = sess.get(url, timeout=60)
        if r.status_code != 200 or not r.content:
            return None
        name = fname or safe_name(prefix + url.split("/")[-1].split("?")[0]) or (prefix + "file")
        with open(os.path.join(folder, name), "wb") as f:
            f.write(r.content)
        return name
    except Exception as e:
        return f"ERROR: {e}"


# ── 실행 ─────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sso_bootstrap()
    itube = json.load(open(ITUBE_JSON, encoding="utf-8"))
    result = []

    for e in itube:
        idx, kname = e["no"], e["엑셀_국문명"]
        entry = {"no": idx, "엑셀_국문명": kname}
        nfec = (e.get("itube_정보") or {}).get("NTIS No", "").strip()
        entry["nfec_no"] = nfec

        if idx in ZEUS_OVERRIDE:
            zid = ZEUS_OVERRIDE[idx]
            entry["zeus_후보"] = []
            if zid is None:
                entry["상태"] = "ZEUS 미등록(제작사·모델명 대조 결과 동일 장비 없음)"
                result.append(entry)
                print(f"[{idx:2}] {kname}: ZEUS 미등록")
                continue
        else:
            hits = search_ids(nfec) if nfec else search_ids(kname + " " + INST_NAME)
            entry["zeus_후보"] = hits[:5]
            if not hits:
                entry["상태"] = "ZEUS 미검색"
                result.append(entry)
                print(f"[{idx:2}] {kname}: ZEUS 미검색")
                continue
            zid = hits[0]["id"]
        entry["zeus_id"] = zid
        entry["zeus_url"] = READ + zid

        folder = os.path.join(OUT_DIR, f"{idx:02d}_{safe_name(kname)}")
        os.makedirs(folder, exist_ok=True)

        r = zget(READ + zid)
        with open(os.path.join(folder, "_zeus_read.html"), "w", encoding="utf-8") as f:
            f.write(r.text)
        rec = parse_read(r.text)
        entry["zeus_본문"] = rec["_본문"]
        entry["zeus_등록번호"] = rec["시설장비등록번호"]

        saved = []
        for u in rec["_images"]:
            n = download(u, folder, "zeus_")
            if n:
                saved.append(n)
        if rec["_qr"]:
            n = download(rec["_qr"], folder, fname="zeus_qr.png")
            if n:
                saved.append("zeus_qr.png")
        entry["다운로드"] = saved

        # 장비예약 상세: 특성·용도설명·이용요금·예약단위·동일모델 목록이 여기에만 있다
        m = re.search(r"/resv/equip/read/([A-Za-z0-9\-]+)", r.text)
        if m:
            entry["zeus_활용번호"] = m.group(1)
            rr = zget(BASE + "/resv/equip/read/" + m.group(1))
            with open(os.path.join(folder, "_zeus_resv.html"), "w", encoding="utf-8") as f:
                f.write(rr.text)
            s2 = BeautifulSoup(rr.text, "html.parser")
            art2 = s2.find("article") or s2
            with open(os.path.join(folder, "_zeus_resv.txt"), "w", encoding="utf-8") as f:
                f.write(re.sub(r"\n{2,}", "\n", art2.get_text("\n", strip=True)))

        with open(os.path.join(folder, "_zeus.json"), "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

        result.append(entry)
        print(f"[{idx:2}] {kname} -> ZEUS {zid} / 파일 {len(saved)}개 / 예약 {entry.get('zeus_활용번호','-')}")
        time.sleep(0.3)

    with open(ZEUS_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {ZEUS_JSON}")


if __name__ == "__main__":
    main()
