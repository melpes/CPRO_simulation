"""각 설비의 확보 파라미터 수량을 집계해 AAS 제작 가능성을 판단한다.

집계를 두 종류로 나눈다.
  - 확정 집계 : ZEUS·i-Tube 의 '항목 : 값' 구조화 사양. 개수가 정확하다.
  - 하한 집계 : 매뉴얼·논문·특허 PDF. 전량 추출하지 않고 '문서 n건 · 최소 m건' 으로만 적는다.
                m 은 수치+단위가 붙은 표현을 센 값이라 실제로는 그보다 많다.

파라미터명은 출처 표기를 그대로 쓴다 (임의 개명 금지).
"""

import csv
import glob
import html
import json
import os
import re
import sys
from collections import OrderedDict

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
MASTER_MD = os.path.join(OUT_DIR, "_파라미터_통합.md")
MASTER_CSV = os.path.join(OUT_DIR, "_파라미터_통합.csv")
MASTER_JSON = os.path.join(OUT_DIR, "_파라미터_통합.json")

ZEUS_JSON = os.path.join(OUT_DIR, "_zeus_mapping.json")
ITUBE_JSON = os.path.join(OUT_DIR, "_itube_mapping.json")
MANUAL_JSON = os.path.join(OUT_DIR, "_manual_params.json")

# 대장 정보 — 설비를 식별·관리하는 값이지 공정 파라미터가 아니다
LEDGER = {"가동상태", "i-Tube No.", "NTIS No", "설치기관", "주소", "담당자", "취득일", "취득금액",
          "내용연수", "구분", "용도", "표준 분류", "장비활용범위", "설치형태", "사용료 형태",
          "장비 사용료", "인증정보", "기능", "장비 상세설명", "제작사", "모델 명", "매뉴얼",
          "사용형태"}

UNITS = OrderedDict([
    ("Plasma Chamber", r"plasma\s*(treatment\s*)?chamber|플라즈마\s*챔버"),
    ("Organic Chamber", r"organic\s*chamber"),
    ("Metal Chamber", r"metal\s*chamber"),
    ("Glove Box", r"glove\s*box|글로브\s*박스"),
    ("Wafer Chamber", r"웨이퍼\s*챔버|wafer\s*chamber"),
    ("Powder Chamber", r"분말\s*챔버|powder\s*chamber"),
    ("Load-lock", r"load\s*-?\s*lock|loadlock"),
    ("Coater Unit", r"coater|coating|스핀\s*코[터팅]"),
    ("Developer Unit", r"developer|develop\b|현상"),
    ("Hot Plate", r"hot\s*plate|핫\s*플레이트"),
    ("Cool Plate", r"cool\s*plate|쿨\s*플레이트"),
    ("Robot / Transfer", r"robot|transfer|conveyor|컨베이어|이송|shuttle"),
    ("Dispenser / Chemical", r"dispenser|nozzle|노즐|chemical\s*delivery|canister"),
    ("Spin Motor / Chuck", r"spin\s*(motor|speed|chuck)|스핀\s*(모터|척)"),
    ("EBR", r"\bEBR\b"),
    ("UV / Exposure", r"\bUV\b|exposure|노광|lamp|램프|wavelength|파장"),
    ("Sputter", r"sputter|스퍼터"),
    ("PECVD", r"pecvd"),
    ("Dry Etcher", r"dry\s*etch|건식\s*식각"),
    ("Thermal Evaporator", r"thermal\s*evaporat|열\s*증착"),
    ("RTA", r"\bRTA\b"),
    ("Gas Supply", r"gas|가스|sccm|MFC|가스\s*공급"),
    ("Align / Vision", r"align|alignment|CCD|camera|정렬"),
    ("Print Head", r"print(ing)?\s*(head|speed|table)|inkjet|잉크젯|blanket|nip"),
    ("Bath / Rinse", r"\bbath\b|rinse|shower|air\s*knife|세정"),
])

SRC_LABEL = {"zeus_read": "ZEUS 등록장비", "zeus_resv": "ZEUS 장비예약", "itube": "i-Tube"}

# 하한 집계용 단위 — 문서 안 수치 표현을 세기만 한다
DOC_UNIT = (r"(?:℃|°C|rpm|RPM|sccm|slm|Torr|mTorr|mbar|Pa\b|kPa|MPa|kgf|bar\b"
            r"|W\b|kW|mW|V\b|kV|mA|A\b|Hz|MHz|nm|µm|μm|㎛|㎜|mm|cm|inch"
            r"|s\b|sec|초|min|분|h\b|hr|%|cps|cP|mN/m|mJ|pl|dpi|ℓ/\s*min)")
DOC_NUM = re.compile(r"\d+(?:\.\d+)?\s*" + DOC_UNIT)

MIN_EQUIP = 5      # 설비 1개 AAS 기준 (확정 사양)
MIN_UNIT = 3       # 유닛 1개 AAS 기준


def seg(text, start, ends):
    i = text.find(start)
    if i < 0:
        return ""
    j = min([text.find(e, i + 1) for e in ends if text.find(e, i + 1) > 0] or [len(text)])
    return text[i + len(start):j].strip()


def split_pair(line):
    line = html.unescape(line).strip(" -+·*○◦●")
    if not line:
        return None
    m = re.match(r"^(.{1,40}?)\s*[:：]\s*(.+)$", line)
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def unit_of(name, value=""):
    s = f"{name} {value}"
    for u, pat in UNITS.items():
        if re.search(pat, s, re.I):
            return u
    return "(설비 공통)"


def from_zeus(entry, folder):
    rows = []
    for ln in seg(entry.get("zeus_본문", ""), "구성 및 성능",
                  ["사용/활용 예", "시설장비 문의번호"]).split("\n")[1:]:
        p = split_pair(ln)
        if p:
            rows.append((p[0], p[1], "zeus_read", f"{folder}/_zeus_read.html"))
    resv = os.path.join(OUT_DIR, folder, "_zeus_resv.txt")
    if os.path.exists(resv):
        for ln in seg(open(resv, encoding="utf-8").read(), "특성", ["용도설명"]).split("\n"):
            p = split_pair(ln)
            if p:
                rows.append((p[0], p[1], "zeus_resv", f"{folder}/_zeus_resv.txt"))
    return rows


def from_itube(entry, folder):
    rows = []
    for k, v in (entry.get("itube_정보") or {}).items():
        if not str(v).strip() or k in ("국문명", "영문명", "온라인예약가능여부"):
            continue
        rows.append((k, str(v).strip(), "itube", f"{folder}/_itube_view.html"))
    return rows


def doc_stats(paths):
    """문서 수와 수치 표현 수(하한)만 센다. 내용은 뽑지 않는다."""
    n_doc, n_hit = 0, 0
    for p in paths:
        try:
            t = open(p, encoding="utf-8").read()
        except Exception:
            continue
        if "=" * 60 in t:
            t = t.split("=" * 60, 1)[1]
        n_doc += 1
        n_hit += len({m.group(0) for m in DOC_NUM.finditer(t)})
    return n_doc, n_hit


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    zeus = {e["no"]: e for e in json.load(open(ZEUS_JSON, encoding="utf-8"))}
    itube = {e["no"]: e for e in json.load(open(ITUBE_JSON, encoding="utf-8"))}
    manual = json.load(open(MANUAL_JSON, encoding="utf-8")) if os.path.exists(MANUAL_JSON) else {}
    folders = {int(d[:2]): d for d in os.listdir(OUT_DIR)
               if os.path.isdir(os.path.join(OUT_DIR, d)) and d[:2].isdigit()}

    all_rows, verdicts = [], []
    for no in sorted(folders):
        d = folders[no]
        raw = []
        if zeus.get(no, {}).get("zeus_id"):
            raw += from_zeus(zeus[no], d)
        if itube.get(no, {}).get("itube_epn"):
            raw += from_itube(itube[no], d)

        merged, ledger_n = OrderedDict(), 0
        for nm, val, src, loc in raw:
            v = re.sub(r"\s+", " ", html.unescape(val)).strip()
            if nm in LEDGER:
                ledger_n += 1
                continue
            m = merged.setdefault((nm.strip(), v), {"srcs": [], "locs": []})
            lab = SRC_LABEL.get(src, src)
            if lab not in m["srcs"]:
                m["srcs"].append(lab)
            if loc not in m["locs"]:
                m["locs"].append(loc)

        # 매뉴얼은 유닛 머리글이 원문에 있어 유닛 판정에만 쓴다 (내용은 안 뽑음)
        man_units = OrderedDict()
        for g in manual.get(d, []):
            head = g["유닛"]
            u = unit_of(head)
            u = head if u == "(설비 공통)" and head != "(설비 공통)" else u
            man_units[u] = man_units.get(u, 0) + 1

        by_unit = OrderedDict()
        for (nm, v), m in merged.items():
            by_unit.setdefault(unit_of(nm, v), []).append((nm, v, m))
        for u in man_units:
            by_unit.setdefault(u, [])

        SKIP = ("(설비 공통)",)
        unit_cnt = {u: len(rs) + man_units.get(u, 0) for u, rs in by_unit.items()}
        units_ok = [u for u, c in unit_cnt.items() if u not in SKIP and c >= MIN_UNIT]
        unit_total = len([u for u in by_unit if u not in SKIP])

        declared = []
        for (nm, v) in merged:
            if re.search(r"^(구성|System Configuration|Configuration)", nm, re.I) or "unit" in v.lower():
                for u, pat in UNITS.items():
                    if re.search(pat, v, re.I) and u not in declared and u not in units_ok:
                        declared.append(u)

        man_doc = len(glob.glob(os.path.join(OUT_DIR, d, "*.pdf")))
        man_min = len(manual.get(d, []))
        pap_doc, pap_min = doc_stats(glob.glob(os.path.join(OUT_DIR, d, "논문", "*_본문.txt")))
        pat_doc, pat_min = doc_stats(glob.glob(os.path.join(OUT_DIR, d, "특허", "0*.txt")))
        sim_doc = len(glob.glob(os.path.join(OUT_DIR, d, "유사장비", "*.html")))

        spec_n = len(merged)
        v_eq = "가능" if spec_n >= MIN_EQUIP else (
            "문서로 보완" if spec_n + man_min + pap_min >= MIN_EQUIP else "부족")

        lines = [f"# {d} — 확보 파라미터 수량", "",
                 "## 확정 집계 (포털 구조화 사양)", "",
                 f"- **{spec_n}건** — 항목명과 값이 분리돼 있어 개수가 정확하다",
                 f"- 대장 정보(담당자·취득금액 등) {ledger_n}건은 뺐다", "",
                 "## 하한 집계 (문서 — 전량 추출하지 않음)", "",
                 "| 출처 | 문서 | 최소 확인 건수 | 위치 |", "|---|---|---|---|",
                 f"| 설비 매뉴얼 PDF | {man_doc}건 | 최소 {man_min}건 | `{d}` |",
                 f"| 논문 본문 | {pap_doc}편 | 최소 {pap_min}건 | `{d}/논문` |",
                 f"| 제조사 특허 | {pat_doc}건 | 최소 {pat_min}건 | `{d}/특허` |",
                 f"| 유사장비(타 기관) | {sim_doc}건 | 참고용 | `{d}/유사장비` |", "",
                 "최소 건수는 수치+단위 표현을 센 값이다. 실제로는 이보다 많다.", "",
                 "## 판정", "",
                 f"- 설비 1개 AAS: **{v_eq}** (확정 사양 {MIN_EQUIP}건 이상 기준)",
                 f"- 유닛별 AAS: **{len(units_ok)}개 가능** / 유닛 {unit_total}개 "
                 f"(유닛당 {MIN_UNIT}건 이상, 매뉴얼 포함)",
                 f"- 이름만 선언된 유닛: {', '.join(declared) or '-'}", "",
                 "## 확정 파라미터 목록", ""]

        for u, rs in by_unit.items():
            if not rs:
                continue
            mark = " ✔" if u in units_ok else ""
            extra = f" (+매뉴얼 {man_units[u]}건)" if man_units.get(u) else ""
            lines += [f"### {u} — {len(rs)}건{extra}{mark}", "",
                      "| # | 파라미터명 | 값 | 출처 | 근거 |", "|---|---|---|---|---|"]
            for i, (nm, v, m) in enumerate(rs, 1):
                lines.append(f"| {i} | {nm.replace('|','/')[:38]} | {v.replace('|','/')[:100]} "
                             f"| {' / '.join(m['srcs'])} | {' '.join('`' + x + '`' for x in m['locs'])} |")
                all_rows.append({"설비": d, "유닛": u, "파라미터명": nm, "값": v,
                                 "출처": " / ".join(m["srcs"]), "근거위치": " | ".join(m["locs"])})
            lines.append("")

        with open(os.path.join(OUT_DIR, d, "파라미터표.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        verdicts.append({"설비": d, "확정사양": spec_n,
                         "매뉴얼_문서": man_doc, "매뉴얼_최소": man_min,
                         "논문_문서": pap_doc, "논문_최소": pap_min,
                         "특허_문서": pat_doc, "특허_최소": pat_min,
                         "유사장비": sim_doc, "유닛수": unit_total,
                         "유닛가능": len(units_ok), "유닛목록": units_ok,
                         "선언유닛": declared, "설비AAS": v_eq})
        print(f"{d:34} 확정 {spec_n:>3} / 매뉴얼 {man_doc}·{man_min:>3} / "
              f"논문 {pap_doc}·{pap_min:>3} / 특허 {pat_doc}·{pat_min:>3} / 유닛 {len(units_ok)}")

    verdicts.sort(key=lambda x: (-x["확정사양"], -x["논문_최소"]))
    head = ["# KETI FAB — 설비별 확보 파라미터 수량", "",
            "**확정 집계**는 ZEUS·i-Tube 의 '항목 : 값' 사양이라 개수가 정확하다.",
            "**하한 집계**는 매뉴얼·논문·특허 PDF 로, 전량 추출하지 않고 문서 수와 최소 건수만 적었다.",
            "최소 건수는 수치+단위 표현을 센 값이라 실제로는 이보다 많다.", "",
            f"판정 기준: 설비 1개 AAS = 확정 사양 {MIN_EQUIP}건 이상, "
            f"유닛 1개 AAS = 그 유닛 {MIN_UNIT}건 이상(매뉴얼 포함).", "",
            "| 설비 | 확정 사양 | 매뉴얼 | 논문 | 특허 | 유사장비 | 설비 AAS | 유닛 AAS |",
            "|---|---|---|---|---|---|---|---|"]
    for v in verdicts:
        man = f"{v['매뉴얼_문서']}건·최소{v['매뉴얼_최소']}" if v["매뉴얼_문서"] else "-"
        pap = f"{v['논문_문서']}편·최소{v['논문_최소']}" if v["논문_문서"] else "-"
        pat = f"{v['특허_문서']}건·최소{v['특허_최소']}" if v["특허_문서"] else "-"
        head.append(f"| {v['설비']} | **{v['확정사양']}** | {man} | {pap} | {pat} "
                    f"| {v['유사장비'] or '-'} | {v['설비AAS']} "
                    f"| {v['유닛가능']}/{v['유닛수']} {', '.join(v['유닛목록'][:3])} |")
    ok = sum(1 for v in verdicts if v["설비AAS"] == "가능")
    head += ["", f"- 설비 1개 AAS 가능: **{ok}/{len(verdicts)}개**",
             f"- 유닛 단위로 쪼갤 수 있는 AAS: **{sum(v['유닛가능'] for v in verdicts)}개**",
             f"- 확정 사양 합계 **{sum(v['확정사양'] for v in verdicts)}건** / "
             f"논문 최소 {sum(v['논문_최소'] for v in verdicts)}건 / "
             f"특허 최소 {sum(v['특허_최소'] for v in verdicts)}건"]
    with open(MASTER_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n")

    with open(MASTER_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["설비", "유닛", "파라미터명", "값", "출처", "근거위치"])
        w.writeheader()
        w.writerows(all_rows)
    with open(MASTER_JSON, "w", encoding="utf-8") as f:
        json.dump({"판정": verdicts, "확정파라미터": all_rows}, f, ensure_ascii=False, indent=2)
    print(f"\n설비 AAS 가능 {ok}/{len(verdicts)} → {MASTER_MD}")


if __name__ == "__main__":
    main()
