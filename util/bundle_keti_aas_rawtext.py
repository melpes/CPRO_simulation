"""12개 AAS 별로 사양 원문을 통째로 묶는다.

파싱으로는 계층 구조('- Electrodes / : parallel plate / : gap 29 mm')를 못 살린다.
그래서 여기서는 자르지 않고 원문 그대로 모으고, 파라미터 정리는 별도 에이전트가 한다.
각 문단 앞에 출처와 URL 을 붙여 근거를 잃지 않게 한다.
"""

import glob
import json
import os
import re
import sys

BASE = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package"
R = os.path.join(BASE, r"docs\원본자료\keti-fab\포털수집")
OUT = os.path.join(BASE, r"docs\원본자료\keti-fab\AAS원문묶음")

ZEUS_READ = "https://www.zeus.go.kr/search/equip/read/"
ZEUS_RESV = "https://www.zeus.go.kr/resv/equip/read/"
ITUBE_VIEW = "https://www.itube.or.kr/aplct/equipSrch/sharingView.do?g_menu_id=MNID210100&equip_no="
ITUBE_FILE = "https://www.itube.or.kr/unitc/equipuse/myequip/fileDownMyEquip.do?g_menu_id=&equip_file_no="

# (분류, AAS 이름, 설비 폴더들, 그 AAS 로 볼 유사장비 파일 키워드)
AAS = [
    ("증착", "박막증착장비-PECVD", ["증착/26_박막증착장비"], ["화학기상", "TEOS", "PECVD"]),
    ("증착", "박막증착장비-Sputter", ["증착/26_박막증착장비"], ["스퍼터", "Sputter"]),
    ("증착", "박막증착장비-DryEtcher", ["증착/26_박막증착장비"], ["식각", "에칭"]),
    ("증착", "박막증착장비-ThermalEvaporator", ["증착/26_박막증착장비"], ["열증착", "전자빔"]),
    ("증착", "유기증착기-PlasmaChamber", ["증착/24_유기증착기"], ["플라즈마"]),
    ("증착", "유기증착기-OrganicChamber", ["증착/24_유기증착기"], ["유기", "OLED", "Sunicel"]),
    ("증착", "유기증착기-MetalChamber", ["증착/24_유기증착기"], ["열증착"]),
    ("증착", "PEALD", ["증착/44_PEALD"], ["*"]),
    ("포토", "현상장비", ["포토/43_스핀 트랙 시스템", "포토/18_현상장비",
                          "포토/34_스핀디벨로퍼"], ["*"]),
    ("포토", "마스크 얼라이너", ["포토/42_마스크 얼라이너(8인치)", "포토/21_마스크얼라이너"], ["*"]),
    ("포토", "식각/스트립", ["포토/19_엣쳐_스트리퍼", "포토/35_유기스트리퍼"], ["*"]),
    ("프린터", "프린팅", ["프린터/20_스크린프린터", "프린터/09_잉크젯 프린터 for PLED #1",
                    "프린터/13_잉크젯 프린터 for PLED #2", "프린터/23_잉크젯 프린터(lab)",
                    "프린터/30_잉크젯프린터(lab #2)", "프린터/31_리버스 옵셋 프린터"], ["*"]),
    ("참고", "CBD", ["증착/27_화학 습식 증착(CBD)"], ["*"]),
]


def safe_aas(name):
    """파일·폴더·시트 이름용. 경로에 못 쓰는 / 만 _ 로 바꾼다."""
    return name.replace("/", "_")


def from_safe(name):
    """safe_aas 로 만든 이름을 원래 AAS 이름으로 되돌린다."""
    for _g, a, _f, _k in AAS:
        if safe_aas(a) == name:
            return a
    return name


def seg(text, start, ends):
    i = text.find(start)
    if i < 0:
        return ""
    j = min([text.find(e, i + 1) for e in ends if text.find(e, i + 1) > 0] or [len(text)])
    return text[i + len(start):j].strip()


def blocks_for(folder_rel, sim_keys, zeus, itube, manual):
    """설비 폴더 하나에서 (제목, 출처, URL, 원문) 블록들을 만든다."""
    d = os.path.join(R, folder_rel)
    name = os.path.basename(folder_rel)
    no = int(name[:2])
    out = []

    ze = zeus.get(no, {})
    zid = ze.get("zeus_id")
    if zid:
        body = seg(ze.get("zeus_본문", ""), "구성 및 성능", ["사용/활용 예", "시설장비 문의번호"])
        if body.strip():
            out.append((f"{name} · 본설비", "ZEUS 등록장비 상세", ZEUS_READ + zid, body))
        use = seg(ze.get("zeus_본문", ""), "사용/활용 예", ["시설장비 문의번호"])
        if use.strip():
            out.append((f"{name} · 본설비 사용/활용 예", "ZEUS 등록장비 상세", ZEUS_READ + zid, use))

    rv = os.path.join(d, "_zeus_resv.txt")
    rh = os.path.join(d, "_zeus_resv.html")
    rid = None
    if os.path.exists(rh):
        m = re.search(r"/resv/equip/read/([A-Za-z0-9\-]+)", open(rh, encoding="utf-8").read())
        rid = m.group(1) if m else None
    if os.path.exists(rv):
        t = open(rv, encoding="utf-8").read()
        body = seg(t, "특성", ["용도설명"])
        if body.strip():
            out.append((f"{name} · 본설비(예약페이지)", "ZEUS 장비예약 상세",
                        ZEUS_RESV + rid if rid else ZEUS_READ + (zid or ""), body))

    te = itube.get(no, {})
    epn = te.get("itube_epn")
    if epn:
        info = te.get("itube_정보") or {}
        keep = {k: v for k, v in info.items()
                if str(v).strip() and k not in ("국문명", "영문명", "온라인예약가능여부")}
        if keep:
            body = "\n".join(f"{k} : {v}" for k, v in keep.items())
            out.append((f"{name} · i-Tube", "i-Tube 상세", ITUBE_VIEW + epn, body))
        for f in te.get("매뉴얼_첨부", []):
            rows = manual.get(name, [])
            if rows:
                body = "\n".join(f"[{g['유닛']}] {g['파라미터명']} : {g['값']}  (p{g['쪽']})" for g in rows)
                out.append((f"{name} · 설비 매뉴얼 PDF", "i-Tube 매뉴얼 다운로드",
                            ITUBE_FILE + f.get("파일번호", ""), body))
            break

    for f in sorted(glob.glob(os.path.join(d, "유사장비", "*.txt"))):
        b = os.path.basename(f)
        if sim_keys != ["*"] and not any(k in b for k in sim_keys):
            continue
        t = open(f, encoding="utf-8").read()
        m = re.search(r"시설장비활용번호\s*\n\s*([A-Za-z0-9\-]+)", t)
        url = ZEUS_RESV + m.group(1) if m else "https://www.zeus.go.kr/search"
        body = seg(t, "특성", ["용도설명"]) or seg(t, "구성 및 성능", ["사용/활용 예", "시설장비 문의번호"])
        if body.strip():
            out.append((f"유사장비 · {b.replace('.txt','')}", "ZEUS 타 기관 장비", url, body))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    zeus = {e["no"]: e for e in json.load(open(os.path.join(R, "_zeus_mapping.json"), encoding="utf-8"))}
    itube = {e["no"]: e for e in json.load(open(os.path.join(R, "_itube_mapping.json"), encoding="utf-8"))}
    manual = json.load(open(os.path.join(R, "_manual_params.json"), encoding="utf-8"))

    index = []
    for i, (grp, name, folders, keys) in enumerate(AAS, 1):
        blocks = []
        for fr in folders:
            blocks += blocks_for(fr, keys, zeus, itube, manual)
        lines = [f"# {grp} / {name}", "",
                 "이 파일은 사양 **원문**이다. 파싱하지 않고 그대로 옮겼다.",
                 "각 블록 머리에 출처와 URL 이 있으니 파라미터를 뽑을 때 그 URL 을 근거로 달 것.", ""]
        for title, src, url, body in blocks:
            lines += ["---", "", f"## {title}", f"- 출처: {src}", f"- URL: {url}", "", "```", body, "```", ""]
        fn = f"{i:02d}_{name}.md"
        with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        chars = sum(len(b[3]) for b in blocks)
        index.append({"파일": fn, "분류": grp, "AAS": name, "블록": len(blocks), "원문자수": chars})
        print(f"{grp:5} {name:30} 블록 {len(blocks):>2} / 원문 {chars:>6}자 → {fn}")

    with open(os.path.join(OUT, "_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
