# aas_loader.py — AAS JSON → 시뮬레이션 데이터 추출기
#
# 설계 원칙:
#   - JSON 경로의 각 단계(SM→SMC→P/R/SML)가 코드 구조와 1:1 대응.
#   - 중간 변수 없음. 경로 탐색 결과가 dataclass 필드에 직접 들어감.
#   - idShort = 변수명/필드명. AAS 구조 변경 시 경로만 수정.
#   - 동일 구조의 MODEL_X 는 load_aas(model_id, path) 한 줄로 동작.
#
# ── 경로 표기 기호 ─────────────────────────────────────────────────────────
#   SM   submodels[]                   idShort 로 진입
#   SMC  submodelElements[] | value[]  idShort 로 진입
#   SML  value[]                       목록 순회
#   [P]  Property                      .value 추출
#   [R]  Range                         .min / .max 추출
#   [E]  Entity                        .statements[] 순회
#   [Re] RelationshipElement           .second.keys[0].value 추출
#   [Q]  qualifier                     type 으로 value 추출
#
# ── 전체 경로 지도 ─────────────────────────────────────────────────────────
#
#   SM.ManufacturingProcess
#     SMC.{GroupIdShort}
#       [Q] ProcessGroup          → ProcessNode.ProcessGroup
#       SMC.{ProcessCode}
#         [P] DepType             → ProcessNode.DepType
#         [P] DepPrev             → ProcessNode.DepPrev  (';' 분리)
#         [P] CycleTimeSec        → ProcessNode.CycleTimeSec
#         [P] DefectRate          → ProcessNode.DefectRate
#         SML.InputBOM
#           [Re](반복)
#             [Q] Quantity        → BomItem.Quantity
#             .value.keys[0]      → BomItem.item_code  (_iri_token)
#
#   SM.WorkstationWorkerMatchingData
#     SMC.SkillLevelType
#       [P].{LOW|STANDARD|HIGH}
#         .idShort                → SkillLevel.name
#         .value                  → SkillLevel.rank
#         .description[en]        → SkillLevel.ct_factor / dr_factor
#     SMC.GeneralWorkstationData
#       SMC.WorkstationInformation
#         SMC.{WorkstationId}     idShort = WWM_*Line
#           [P] WorkStartTime     → WorkstationData.WorkStartTime
#           [P] WorkEndTime       → WorkstationData.WorkEndTime
#           [R] BreakDurationMin
#               .min              → WorkstationData.BreakDurationMin.min
#               .max              → WorkstationData.BreakDurationMin.max
#           SML.WorkstationConfigurationRecords
#             SMC(반복)
#               [P] WorkerId      → WorkstationData.WorkerIds[]
#               [P] SkillLevel    → WorkstationData.SkillLevel (최빈값)
#           SML.AssignedProcessGroups
#             [Re](반복)          → Ref 1개 = 복수 ProcessCode 
#               .value.keys[]     → _iri_token → GroupIdShort
#               → group_to_workstation[ProcessCode] = WorkstationId
#
#   SM.HierarchicalStructures
#     [E].{ModelEntity}
#       [E].{PCB_code}  [Q]Category='SMT_PCB'  → PcbEntry
#           .entityType                         → PcbEntry.entityType
#           [Q] SMT_Side                        → PcbEntry.SMT_Side
#           [Q] Quantity                        → PcbEntry.Quantity
#           [Re] HasPart_*(반복)
#               .second.keys[0]                 → SmtComponent.item_code
#               [Q] Quantity                    → SmtComponent.Quantity
#               [Q] Category                    → SmtComponent.Category
#       [E].{P_code}    [Q]Category≠'SMT_PCB'  → AssemblyPart
#           [Q] Quantity                        → AssemblyPart.Quantity
#           [Q] Category                        → AssemblyPart.Category

import json, re, os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# 경로 탐색 함수 (기존 유지)
# ══════════════════════════════════════════════════════════════════════════════

def _sm(submodels: list, idShort: str) -> Optional[dict]:
    return next((s for s in submodels if s.get('idShort') == idShort), None)

def _smc(elements: list, idShort: str) -> Optional[dict]:
    return next(
        (e for e in elements if isinstance(e, dict) and e.get('idShort') == idShort),
        None)

def _prop(elements: list, idShort: str):
    el = _smc(elements, idShort)
    return el.get('value') if el else None

def _range(elements: list, idShort: str) -> Optional[dict]:
    el = _smc(elements, idShort)
    return el if (el and el.get('modelType') == 'Range') else None

def _qualifier(obj: dict, q_type: str):
    for q in (obj.get('qualifiers') or []):
        if q.get('type') == q_type:
            return q.get('value')
    return None

def _iri_token(iri: str) -> str:
    parts = str(iri).rstrip('/').split('/')
    return next((p for p in reversed(parts) if p and p not in ('0', '1')), '')

def _hhmm(value) -> int:
    h, m = (int(x) for x in str(value).strip().split(':'))
    return h * 3600 + m * 60

def _qty(raw) -> int:
    try:
        return max(int(float(str(raw))), 1)
    except (ValueError, TypeError):
        return 1


# ══════════════════════════════════════════════════════════════════════════════
# dataclass — 필드명 = AAS idShort (기존 유지)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BomItem:
    """SML.InputBOM.[Re]"""
    item_code : str   # [Re].value.keys[0] → _iri_token
    Quantity  : int   # [Q] Quantity

@dataclass
class ProcessNode:
    """SMC.{GroupIdShort}.SMC.{ProcessCode}"""
    ProcessCode   : str
    GroupIdShort  : str
    ProcessGroup  : str
    WorkstationId : str
    DepType       : str
    DepPrev       : List[str]
    CycleTimeSec  : int
    DefectRate    : float
    InputBOM      : List[BomItem]
    SamplingRate  : Optional[float] = None

@dataclass
class BreakDurationMin:
    """[R] BreakDurationMin"""
    min : int   # Range.min → _hhmm
    max : int   # Range.max → _hhmm

@dataclass
class WorkstationData:
    """SMC.{WorkstationId}"""
    WorkstationId                   : str
    WorkStartTime                   : int
    WorkEndTime                     : int
    BreakDurationMin                : BreakDurationMin
    WorkstationConfigurationRecords : int        # len(SML)
    SkillLevel                      : int        # 최빈 rank
    WorkerIds                       : List[str]
    AssignedProcessGroups           : List[str]

@dataclass
class SkillLevel:
    """SMC.SkillLevelType.[P].{name}"""
    name      : str
    rank      : int
    ct_factor : float
    dr_factor : float

@dataclass
class SmtComponent:
    """[E].{PCB_code}.[Re].HasPart_*"""
    item_code : str
    Quantity  : int
    Category  : str

@dataclass
class PcbEntry:
    """[E].{PCB_code}  [Q]Category='SMT_PCB'"""
    idShort    : str
    entityType : str
    SMT_Side   : str
    Quantity   : int
    components : List[SmtComponent]

@dataclass
class AssemblyPart:
    """[E].{P_code}  [Q]Category≠'SMT_PCB'"""
    idShort  : str
    Quantity : int
    Category : str

@dataclass
class HierarchicalStructuresData:
    """SM.HierarchicalStructures 전체"""
    pcb_entries    : Dict[str, PcbEntry]
    assembly_parts : Dict[str, AssemblyPart]

@dataclass
class AASModel:
    """AAS JSON 한 파일의 전체 파싱 결과. 필드명 = Submodel idShort."""
    model_id                      : str
    ManufacturingProcess          : Dict[str, ProcessNode]
    WorkstationWorkerMatchingData : Dict[str, WorkstationData]
    SkillLevelType                : Dict[str, SkillLevel]
    HierarchicalStructures        : HierarchicalStructuresData
    group_to_workstation          : Dict[str, str] = field(default_factory=dict)
    schedule                      : Dict[str, int] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# SM.ManufacturingProcess 파서
# ══════════════════════════════════════════════════════════════════════════════

def _parse_ManufacturingProcess(
    submodels: list,
    group_to_workstation: Dict[str, str],
) -> Dict[str, ProcessNode]:

    ManufacturingProcess = _sm(submodels, 'ManufacturingProcess')
    if ManufacturingProcess is None:
        return {}

    result: Dict[str, ProcessNode] = {}

    for GroupIdShort_el in ManufacturingProcess.get('submodelElements', []):
        if GroupIdShort_el.get('modelType') != 'SubmodelElementCollection':
            continue
        if GroupIdShort_el.get('idShort') == 'ProcessType':
            continue

        GroupIdShort = GroupIdShort_el['idShort']

        for ProcessCode_el in (GroupIdShort_el.get('value') or []):
            if ProcessCode_el.get('modelType') != 'SubmodelElementCollection':
                continue

            elems       = ProcessCode_el.get('value') or []
            InputBOM_el = _smc(elems, 'InputBOM')

            result[ProcessCode_el['idShort']] = ProcessNode(
                ProcessCode   = ProcessCode_el['idShort'],
                GroupIdShort  = GroupIdShort,
                ProcessGroup  = _qualifier(GroupIdShort_el, 'ProcessGroup') or '',
                WorkstationId = group_to_workstation.get(ProcessCode_el['idShort'], ''),
                DepType       = str(_prop(elems, 'DepType') or 'SEQUENCE').upper(),
                DepPrev       = [p.strip()
                                 for p in str(_prop(elems, 'DepPrev') or '').split(';')
                                 if p.strip()],
                CycleTimeSec  = int(_prop(elems, 'CycleTimeSec') or 0),
                DefectRate    = float(_prop(elems, 'DefectRate') or 0.0),
                InputBOM      = [
                    BomItem(
                        item_code = _iri_token(
                            (ref.get('value', {}).get('keys') or [{}])[0].get('value', '')),
                        Quantity  = _qty(_qualifier(ref, 'Quantity')),
                    )
                    for ref in (InputBOM_el.get('value') or [] if InputBOM_el else [])
                    if ref.get('modelType') == 'ReferenceElement'
                    and _iri_token(
                        (ref.get('value', {}).get('keys') or [{}])[0].get('value', ''))
                ],
                SamplingRate  = (lambda v: float(v) if v is not None else None)(
                    _qualifier(ProcessCode_el, 'SamplingRate')),
            )

    return result


# ══════════════════════════════════════════════════════════════════════════════
# SM.WorkstationWorkerMatchingData 파서
# ══════════════════════════════════════════════════════════════════════════════

def _parse_SkillLevelType(WorkstationWorkerMatchingData: dict) -> Dict[str, SkillLevel]:
    SkillLevelType_el = _smc(
        WorkstationWorkerMatchingData.get('submodelElements', []), 'SkillLevelType')
    if SkillLevelType_el is None:
        return {}
    result: Dict[str, SkillLevel] = {}
    for prop in (SkillLevelType_el.get('value') or []):
        name = str(prop.get('idShort', '')).upper()
        try:
            rank = int(prop.get('value', 0))
        except (ValueError, TypeError):
            continue
        desc = next(
            (x.get('text', '') for x in (prop.get('description') or [])
             if x.get('language') == 'en'), '')
        ct_m = re.search(r'cycle time correction factor of ([0-9.]+)', desc)
        dr_m = re.search(r'defect rate correction factor of ([0-9.]+)', desc)
        result[name] = SkillLevel(
            name      = name,
            rank      = rank,
            ct_factor = float(ct_m.group(1)) if ct_m else 1.0,
            dr_factor = float(dr_m.group(1)) if dr_m else 1.0,
        )
    return result


def _extract_assigned_groups(apg_el: Optional[dict]) -> List[str]:
    """AssignedProcessGroups[SML] 파싱"""
    if not apg_el:
        return []
    assigned: List[str] = []
    for ref in (apg_el.get('value') or []):
        # keys[] 또는 value.keys[] 모두 대응 (새 구조)
        keys = (ref.get('value', {}) or ref).get('keys', [])
        for k in keys:
            token = _iri_token(k.get('value', ''))
            if token:
                assigned.append(token)
    return assigned


def _parse_WorkstationWorkerMatchingData(
    submodels: list,
) -> Tuple[Dict[str, WorkstationData], Dict[str, SkillLevel], Dict[str, str], Dict[str, int]]:

    WorkstationWorkerMatchingData = _sm(submodels, 'WorkstationWorkerMatchingData')
    if WorkstationWorkerMatchingData is None:
        return {}, {}, {}, {}

    SkillLevelType     = _parse_SkillLevelType(WorkstationWorkerMatchingData)
    skill_name_to_rank = {sl.name: sl.rank for sl in SkillLevelType.values()}

    # SMC.GeneralWorkstationData → SMC.WorkstationInformation
    GeneralWorkstationData = _smc(
        WorkstationWorkerMatchingData.get('submodelElements', []),
        'GeneralWorkstationData')
    WorkstationInformation = _smc(
        (GeneralWorkstationData.get('value') or []) if GeneralWorkstationData else [],
        'WorkstationInformation')
    if WorkstationInformation is None:
        return {}, SkillLevelType, {}, {}

    workstations:         Dict[str, WorkstationData] = {}
    group_to_workstation: Dict[str, str]             = {}
    schedule:             Dict[str, int]             = {}
    schedule_set = False

    for WorkstationId_el in (WorkstationInformation.get('value') or []):
        if WorkstationId_el.get('modelType') != 'SubmodelElementCollection':
            continue

        props = WorkstationId_el.get('value') or []

        # [R] BreakDurationMin
        BreakDurationMin_el = _range(props, 'BreakDurationMin')
        if BreakDurationMin_el is None:
            continue

        # SML.WorkstationConfigurationRecords
        wcr_el  = _smc(props, 'WorkstationConfigurationRecords')
        records = (wcr_el.get('value') or []) if wcr_el else []

        skill_votes = [
            skill_name_to_rank.get(str(inner.get('value', '')).upper())
            for rec in records if isinstance(rec, dict)
            for inner in (rec.get('value') or [])
            if isinstance(inner, dict) and inner.get('idShort') == 'SkillLevel'
            and str(inner.get('value', '')).upper() in skill_name_to_rank
        ]

        apg_el = _smc(props, 'AssignedProcessGroups')
        assigned = _extract_assigned_groups(apg_el)

        for token in assigned:
            group_to_workstation[token] = WorkstationId_el['idShort']

        if not schedule_set and props:
            schedule = {
                'WorkStartTime'        : _hhmm(_prop(props, 'WorkStartTime')),
                'WorkEndTime'          : _hhmm(_prop(props, 'WorkEndTime')),
                'BreakDurationMin_min' : _hhmm(BreakDurationMin_el.get('min')),
                'BreakDurationMin_max' : _hhmm(BreakDurationMin_el.get('max')),
            }
            schedule_set = True

        workstations[WorkstationId_el['idShort']] = WorkstationData(
            WorkstationId   = WorkstationId_el['idShort'],
            WorkStartTime   = _hhmm(_prop(props, 'WorkStartTime')),
            WorkEndTime     = _hhmm(_prop(props, 'WorkEndTime')),
            BreakDurationMin= BreakDurationMin(
                min = _hhmm(BreakDurationMin_el.get('min')),
                max = _hhmm(BreakDurationMin_el.get('max')),
            ),
            WorkstationConfigurationRecords = max(len(records), 1),
            SkillLevel = max(set(skill_votes), key=skill_votes.count) if skill_votes else 2,
            WorkerIds  = [
                str(inner.get('value', ''))
                for rec in records if isinstance(rec, dict)
                for inner in (rec.get('value') or [])
                if isinstance(inner, dict) and inner.get('idShort') == 'WorkerId'
                and inner.get('value')
            ],
            AssignedProcessGroups = assigned,
        )

    return workstations, SkillLevelType, group_to_workstation, schedule


# ══════════════════════════════════════════════════════════════════════════════
# SM.HierarchicalStructures 파서
# ══════════════════════════════════════════════════════════════════════════════

def _parse_HierarchicalStructures(submodels: list) -> HierarchicalStructuresData:

    HierarchicalStructures_sm = _sm(submodels, 'HierarchicalStructures')
    if HierarchicalStructures_sm is None:
        return HierarchicalStructuresData(pcb_entries={}, assembly_parts={})

    ModelEntity = next(
        (el for el in HierarchicalStructures_sm.get('submodelElements', [])
         if el.get('modelType') == 'Entity'),
        None)
    if ModelEntity is None:
        return HierarchicalStructuresData(pcb_entries={}, assembly_parts={})

    pcb_entries:    Dict[str, PcbEntry]     = {}
    assembly_parts: Dict[str, AssemblyPart] = {}

    for statement in (ModelEntity.get('statements') or []):
        if _qualifier(statement, 'Category') == 'SMT_PCB':
            pcb_entries[statement['idShort']] = PcbEntry(
                idShort    = statement['idShort'],
                entityType = statement.get('entityType', ''),
                SMT_Side   = _qualifier(statement, 'SMT_Side') or 'single',
                Quantity   = _qty(_qualifier(statement, 'Quantity')),
                components = [
                    SmtComponent(
                        item_code = (rel.get('second', {}).get('keys') or [{}])[0]
                                    .get('value', '')
                                    or rel['idShort'].replace('HasPart_', ''),
                        Quantity  = _qty(_qualifier(rel, 'Quantity')),
                        Category  = _qualifier(rel, 'Category') or '',
                    )
                    for rel in (statement.get('statements') or [])
                    if rel.get('modelType') == 'RelationshipElement'
                ],
            )
        else:
            assembly_parts[statement['idShort']] = AssemblyPart(
                idShort  = statement['idShort'],
                Quantity = _qty(_qualifier(statement, 'Quantity')),
                Category = _qualifier(statement, 'Category') or '',
            )

    return HierarchicalStructuresData(
        pcb_entries    = pcb_entries,
        assembly_parts = assembly_parts,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════════════════════════

def load_aas(model_id: str, json_path: str) -> AASModel:
    if not os.path.exists(json_path):
        raise FileNotFoundError(f'AAS JSON 없음: {json_path}')

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        submodels = data.get('submodels', [])

    ww, skill, g2w, sched = _parse_WorkstationWorkerMatchingData(submodels)

    return AASModel(
        model_id                      = model_id,
        ManufacturingProcess          = _parse_ManufacturingProcess(submodels, g2w),
        WorkstationWorkerMatchingData = ww,
        SkillLevelType                = skill,
        HierarchicalStructures        = _parse_HierarchicalStructures(submodels),
        group_to_workstation          = g2w,
        schedule                      = sched,
    )