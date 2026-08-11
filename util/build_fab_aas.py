"""KETI FAB runsheet → CPRO 구조 AAS (MODEL_PI · MODEL_GLASS) 생성.

지금 확보된 데이터만 채우고 없는 값은 빈 문자열로 둔다.
"""
import json, re, os
import openpyxl

# ── 하드코딩 ────────────────────────────────────────────────────────────
RUNSHEET = r"C:/Users/KangTaehui/KG/keti/keti-fab/[KETI]전북본부 FAB 장비 및 공정 정보/3. TFT backplane runsheet_스마트.xlsx"
OUT_DIR = r"C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/fab"
NS = "https://www.smart-factory.kr/ids"
HS_SM_ID = "https://admin-shell.io/idta/SubmodelTemplate/HierarchicalStructuresBoM/1/1"

# 시트별 열 위치 (그룹, 사용장비, 파라미터명, 값)
SHEETS = {
    "MODEL_PI":    ("PI Run sheet",        0, 1, 2, 3),
    "MODEL_GLASS": ("Run sheet(유리) 1매",  0, None, 1, 2),
}

# Dry etcher 실측 오버헤드(초) — 레시피 공정시간과 실제 런 차이가 91~93 으로 일정
DRY_ETCHER_OVERHEAD_SEC = 92

# 공정그룹 idShort 변환
GROUP_ID = {
    "PI Barrier Dep.": "PIBarrierDep",
    "Gate Dep. & Patterning": "GateDepPatterning",
    "G.I Dep.": "GIDep",
    "G.I Patterning": "GIPatterning",
    "Semiconductor Dep. & Patterning": "SemiconductorDepPatterning",
    "S/D Dep. & Patterning": "SDDepPatterning",
    "Passivation Dep./ Patterning": "PassivationDepPatterning",
    "Anode patterning": "AnodePatterning",
    "PDL patterning": "PDLPatterning",
}

# 소모재 마스터 — idShort: (표시명, BOMCategory)
MATERIALS = {
    "PI":                      ("Polyimide substrate", "SUBSTRATE"),
    "GLASS":                   ("Glass substrate", "SUBSTRATE"),
    "MO":                      ("Molybdenum sputtering target", "TARGET"),
    "ITO":                     ("ITO sputtering target", "TARGET"),
    "IGZO":                    ("IGZO sputtering target", "TARGET"),
    "SIH4":                    ("Silane gas", "GAS"),
    "N2O":                     ("Nitrous oxide gas", "GAS"),
    "NH3":                     ("Ammonia gas", "GAS"),
    "AR":                      ("Argon gas", "GAS"),
    "N2":                      ("Nitrogen gas", "GAS"),
    "CF4":                     ("Carbon tetrafluoride gas", "GAS"),
    "CL2":                     ("Chlorine gas", "GAS"),
    "O2":                      ("Oxygen gas", "GAS"),
    "ZPP1700PG30":             ("Photoresist ZPP1700PG-30", "PHOTORESIST"),
    "ZPP1700G":                ("Photoresist ZPP-1700G", "PHOTORESIST"),
    "TMAH238":                 ("TMAH 2.38% developer", "CHEMICAL"),
    "ITO_ETCHANT":             ("ITO etchant", "CHEMICAL"),
    "ORGANIC_STRIP_CHEMICAL":  ("Organic strip chemical", "CHEMICAL"),
    "NMP":                     ("NMP stripper", "CHEMICAL"),
}
BOM_CATEGORIES = ["SUBSTRATE", "TARGET", "GAS", "PHOTORESIST", "CHEMICAL", "MASK"]

# runsheet Material 문자열 → 소모재 idShort
MATERIAL_ID = {
    "Molybdenum(Mo)": "MO", "ITO": "ITO", "IGZO": "IGZO",
    "ZPP1700PG-30": "ZPP1700PG30", "ZPP-1700G": "ZPP1700G",
    "ITO etchant": "ITO_ETCHANT", "Organic strip chemical": "ORGANIC_STRIP_CHEMICAL",
    "NMP": "NMP",
}
# runsheet 가스 파라미터명 → 소모재 idShort (복합 표기는 앞뒤로 나눠 매칭)
GAS_ID = {"Ar": "AR", "N₂": "N2", "N2": "N2", "SiH4": "SIH4", "N2O": "N2O",
          "NH₃": "NH3", "O₂": "O2", "O2": "O2", "CF4": "CF4", "Cl2": "CL2"}


# ── 헬퍼 ────────────────────────────────────────────────────────────────
def mref(kind, value):
    return {"type": "ModelReference", "keys": [{"type": kind, "value": value}]}


def xref(value):
    return {"type": "ExternalReference", "keys": [{"type": "GlobalReference", "value": value}]}


def prop(ids, value, vtype="xs:string"):
    """값이 비면 value 키를 아예 넣지 않는다 — xs:int 에 빈 문자열은 파싱 오류."""
    p = {"category": "PARAMETER", "idShort": ids,
         "semanticId": mref("ConceptDescription", f"{NS}/cd/{ids}/1/0"),
         "valueType": vtype, "modelType": "Property"}
    if value != "":
        p["value"] = value
    return p


def qual(qtype, value, kind="ValueQualifier", vtype="xs:string"):
    q = {"kind": kind, "type": qtype, "valueType": vtype}
    if value != "":
        q["value"] = value
    return q


NUM = r"\d+(?:\.\d+)?"


def to_sec(key, raw):
    """파라미터명과 값에서 초를 뽑는다. 값에 붙은 단위 > 슬래시 뒷토막 > 헤더 단위 순."""
    if raw is None:
        return None
    s = str(raw)
    if "?" in s:
        return None

    # ① 값에 단위가 붙어 있으면 그게 우선 ('380℃ 3hrs', '100 sec', '10 min')
    for pat, mul in ((r"(%s)\s*(?:hrs?|hours?)" % NUM, 3600),
                     (r"(%s)\s*min" % NUM, 60),
                     (r"(%s)\s*(?:sec|Sec)" % NUM, 1)):
        m = re.search(pat, s)
        if m:
            return int(float(m.group(1)) * mul)

    nums = re.findall(NUM, s)
    if not nums:
        return None

    # ② PI Barrier 의 '63/105' 는 2층 연속 증착이라 합
    if "Deposition time" in key and "/" in s:
        return int(sum(float(x) for x in nums))

    # ③ 'Temp/Time' · 'RPM/Time' 형식은 슬래시 뒷토막의 첫 수가 시간
    if "/" in s:
        tail = re.findall(NUM, s.split("/", 1)[1])
        if not tail:
            return None
        n = float(tail[0])
    else:
        n = float(nums[0])

    return int(n * 60) if "(min)" in key else int(n)


# ── runsheet 파싱 ───────────────────────────────────────────────────────
def read_steps(sheet, gcol, ecol, pcol, vcol):
    ws = wb[sheet]
    rows = [r + (None,) * 6 for r in ws.iter_rows(values_only=True)]
    group = equip = step = None
    steps, cur = [], None
    for r in rows:
        if r[gcol]:
            group = str(r[gcol]).replace("\n", " ").strip()
        if ecol is not None and r[ecol]:
            equip = str(r[ecol]).replace("\n", " ").strip()
        p, v = r[pcol], r[vcol]
        if p and v is None:
            step = str(p).replace("\n", " ").strip()
            continue
        if p == "Process parameter":
            cur = {"group": group, "line_equip": equip, "step": step,
                   "eq": None, "mats": [], "gases": [], "times": {}}
            steps.append(cur)
            continue
        if cur is None or not p:
            continue
        key = str(p).strip()
        if key == "Equipment":
            cur["eq"] = str(v).strip()
        elif key in ("Material", "Strip chemical"):
            cur["mats"].append(str(v).strip())
        elif "gas" in key.lower() or "sccm" in key.lower():
            cur["gases"].append((key, v))
        elif re.search(r"time|Time|Annealing|Treatment|^DI ", key):
            cur["times"][key] = v
    return steps


def cycle_time(st):
    """확보된 데이터로 계산되는 것만 채운다. 안 되면 None."""
    eq = st["eq"] or ""
    t = st["times"]

    def get(*keys):
        for k in t:
            if any(x in k for x in keys):
                s = to_sec(k, t[k])
                if s is not None:
                    return s
        return None

    if eq == "Dry etcher":                                   # 실측 오버헤드 반영
        base = get("Etching time")
        return base + DRY_ETCHER_OVERHEAD_SEC if base else None
    if eq == "PECVD":                                        # 오버헤드 미상 — 공정시간만
        return get("Deposition time")
    if eq == "Sputter":                                      # 시간 파라미터 자체가 없음
        return None
    if eq and "Coater" in eq:
        parts = [get("Coating RPM"), get("Prebake"), get("Develop RPM"),
                 get("Post bake"), get("Hard bake")]
        vals = [p for p in parts if p]
        return sum(vals) if vals else None
    if eq in ("Wet etcher",):
        parts = [get("Chemical Temp"), get("Etching time"), get("DI cleaning")]
        vals = [p for p in parts if p]
        return sum(vals) if vals else None
    if eq in ("Wet stripper", "Manual stripper"):
        parts = [get("Stip time", "Strip time"), get("DI washing")]
        vals = [p for p in parts if p]
        return sum(vals) if vals else None
    if st["step"] == "Annealing":                            # UV 처리 + 열처리
        vals = [to_sec(k, v) for k, v in t.items() if to_sec(k, v)]
        return sum(vals) if vals else None
    return None


def input_bom(st):
    """재료·가스를 소모재 참조로. 가스는 sccm×시간으로 수량이 나온다."""
    items = []
    for m in st["mats"]:
        mid = MATERIAL_ID.get(m)
        if mid:
            items.append((mid, None))
    dur = None
    for k, v in st["times"].items():
        if "Deposition time" in k or "Etching time" in k:
            dur = to_sec(k, v)
            break
    for key, val in st["gases"]:
        if val is None:
            continue
        names = re.findall(r"[A-Za-z][A-Za-z0-9₂₃₄]*", key.split("(")[0])
        nums = re.findall(r"\d+(?:\.\d+)?", str(val))
        for i, nm in enumerate(names):
            gid = GAS_ID.get(nm)
            if not gid:
                continue
            sccm = float(nums[i]) if i < len(nums) else (float(nums[0]) if nums else None)
            qty = int(sccm * dur / 60) if (sccm and dur) else None
            items.append((gid, qty))
    seen, out = set(), []
    for mid, qty in items:
        if mid in seen:
            continue
        seen.add(mid)
        out.append((mid, qty))
    return out


# ── AAS 조립 ────────────────────────────────────────────────────────────
def build(model_id, steps, substrate):
    prefix = model_id.split("_")[1]

    # 공정그룹 → 공정코드
    groups, order = {}, []
    for i, st in enumerate(steps, 1):
        gid = GROUP_ID.get(st["group"], re.sub(r"\W", "", st["group"] or "Unknown"))
        if gid not in groups:
            groups[gid] = []
            order.append(gid)
        code = f"{prefix}_{i * 10}"
        prev = f"{prefix}_{(i - 1) * 10}" if i > 1 else ""
        ct = cycle_time(st)

        node = {"category": "PARAMETER", "idShort": code,
                "displayName": [{"language": "en", "text": st["step"] or ""}],
                "semanticId": mref("ConceptDescription", f"{NS}/cd/{code}/1/0"),
                "qualifiers": [qual("RefNo", str(i * 10)),
                               qual("Equipment", st["eq"] or "")],
                "value": [
                    prop("DepType", "SEQUENCE"),
                    prop("DepPrev", prev),
                    prop("CycleTimeSec", str(ct) if ct else "", "xs:int"),
                    prop("DefectRate", "", "xs:double"),
                    prop("RatedPowerKw", "", "xs:double"),
                ],
                "modelType": "SubmodelElementCollection"}

        items = input_bom(st)
        node["value"].append({
            "category": "PARAMETER", "idShort": "InputBOM",
            "semanticId": mref("ConceptDescription", f"{NS}/cd/InputBOM/1/0"),
            "typeValueListElement": "ReferenceElement",
            # SML 자식은 idShort 를 갖지 않는다 (빈 문자열도 규격 위반)
            "value": [{"category": "PARAMETER",
                       "displayName": [{"language": "en", "text": mid}],
                       "semanticId": mref("ConceptDescription", f"{NS}/cd/InputBomItem/1/0"),
                       "qualifiers": ([qual("Quantity", str(qty), vtype="xs:int"),
                                       qual("Unit", "scc")] if qty else
                                      [qual("Quantity", "", vtype="xs:int")]),
                       "value": xref(f"{NS}/cd/{mid}/1/0"),
                       "modelType": "ReferenceElement"} for mid, qty in items],
            "modelType": "SubmodelElementList"})
        groups[gid].append(node)

    # HierarchicalStructures
    parts = []
    for mid, (disp, cat) in MATERIALS.items():
        if cat == "SUBSTRATE" and mid != substrate:
            continue
        parts.append({"category": "PARAMETER", "idShort": mid,
                      "displayName": [{"language": "en", "text": disp}],
                      "semanticId": mref("ConceptDescription", f"{NS}/cd/{mid}/1/0"),
                      "qualifiers": [qual("Ent/Cardinality", "One", "TemplateQualifier"),
                                     qual("Quantity", ""), qual("Category", cat)],
                      # SelfManagedEntity 는 globalAssetId 가 있어야 한다 (AASd-014)
                      "entityType": "SelfManagedEntity",
                      "globalAssetId": f"{NS}/asset/{mid}/1/0", "modelType": "Entity"})

    bom_cat = {"category": "PARAMETER", "idShort": "BOMCategory",
               "semanticId": mref("ConceptDescription", f"{NS}/cd/BOMCategory/1/0"),
               "value": [{"category": "PARAMETER", "idShort": c,
                          "semanticId": mref("ConceptDescription", f"{NS}/cd/{c}/1/0"),
                          "qualifiers": [qual("Multiplicity", "One", "TemplateQualifier")],
                          "value": [prop("MinStock", "", "xs:int"),
                                    prop("MaxStock", "", "xs:int"),
                                    prop("OrderRatio", "", "xs:double")],
                          "modelType": "SubmodelElementCollection"} for c in BOM_CATEGORIES],
               "modelType": "SubmodelElementCollection"}

    hs = {"idShort": "HierarchicalStructures", "id": f"{NS}/sm/{model_id}/HierarchicalStructures/1/0",
          "kind": "Template",
          "semanticId": xref("https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel"),
          "submodelElements": [
              prop("ArcheType", "Full"),
              {"category": "PARAMETER", "idShort": f"{model_id}_TFTBackplane",
               "displayName": [{"language": "en", "text": "TFT backplane"}],
               "semanticId": mref("ConceptDescription", f"{NS}/cd/{model_id}_TFTBackplane/1/0"),
               "entityType": "SelfManagedEntity",
               "globalAssetId": f"{NS}/asset/{model_id}/TFTBackplane/1/0",
               "statements": parts, "modelType": "Entity"},
              bom_cat],
          "modelType": "Submodel"}

    mp = {"idShort": "ManufacturingProcess", "id": f"{NS}/sm/{model_id}/ManufacturingProcess/1/0",
          "kind": "Template", "submodelElements": [
              {"category": "PARAMETER", "idShort": "ProcessType",
               "semanticId": mref("ConceptDescription", f"{NS}/cd/ProcessType/1/0"),
               "value": [prop("SEQUENCE", "SEQUENCE"), prop("JOIN", "JOIN"), prop("FORK", "FORK")],
               "modelType": "SubmodelElementCollection"}] +
              [{"category": "PARAMETER", "idShort": g,
                "semanticId": mref("ConceptDescription", f"{NS}/cd/{g}/1/0"),
                "qualifiers": [qual("SMT/Cardinality", "One", "TemplateQualifier")],
                "value": groups[g], "modelType": "SubmodelElementCollection"} for g in order],
          "modelType": "Submodel"}

    shell = {"idShort": model_id, "id": f"{NS}/aas/{model_id}/1/0",
             # assetType 은 Identifier 라 빈 문자열을 넣으면 규격 위반 — 생략한다
             "assetInformation": {"assetKind": "Type",
                                  "globalAssetId": f"{NS}/asset/{model_id}/1/0"},
             "submodels": [mref("Submodel", hs["id"]), mref("Submodel", mp["id"])],
             "modelType": "AssetAdministrationShell"}

    return {"assetAdministrationShells": [shell], "submodels": [hs, mp], "conceptDescriptions": []}


# ── 실행 ────────────────────────────────────────────────────────────────
os.makedirs(OUT_DIR, exist_ok=True)
wb = openpyxl.load_workbook(RUNSHEET, data_only=True)

for model_id, (sheet, g, e, p, v) in SHEETS.items():
    steps = read_steps(sheet, g, e, p, v)
    substrate = "PI" if model_id == "MODEL_PI" else "GLASS"
    aas = build(model_id, steps, substrate)
    out = os.path.join(OUT_DIR, model_id + ".json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(aas, fh, ensure_ascii=False, indent=1)

    mp = aas["submodels"][1]
    nodes = [n for g2 in mp["submodelElements"][1:] for n in g2["value"]]
    filled = sum(1 for n in nodes
                 if [x for x in n["value"] if x["idShort"] == "CycleTimeSec"][0].get("value"))
    bom = sum(len([x for x in n["value"] if x["idShort"] == "InputBOM"][0]["value"]) for n in nodes)
    print(f"{model_id}: 공정그룹 {len(mp['submodelElements'])-1} · 공정 {len(nodes)} · "
          f"CycleTimeSec {filled}/{len(nodes)} · InputBOM 항목 {bom} → {out}")
