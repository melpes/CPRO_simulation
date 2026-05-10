# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_CD_URL_RE = re.compile(r'/ids/cd/(?P<idShort>[^/]+)/[^/]+/[^/]+/?$')  # 확정


# 확정
@dataclass
class GlobalReference:
    value: str

    @property
    def Process(self) -> str:
        m = _CD_URL_RE.search(self.value)
        return m.group('idShort')


# 확정
@dataclass
class AssignedProcessGroupRef:
    value: List[GlobalReference] = field(default_factory=list)


@dataclass
class SkillLevelProperty:
    idShort: str
    value: int


@dataclass
class SkillLevelType:
    levels: List[SkillLevelProperty] = field(default_factory=list)

    def __getitem__(self, idShort: str) -> int:
        for p in self.levels:
            if p.idShort == idShort:
                return p.value


@dataclass
class WorkstationInformation:
    AssignedProcessGroups: List[AssignedProcessGroupRef] = field(default_factory=list)
    WorkstationConfigurationRecords: Dict[str, int] = field(default_factory=dict)


@dataclass
class GeneralWorkstationData:
    WorkstationInformation: List[WorkstationInformation] = field(default_factory=list)


@dataclass
class WorkstationWorkerMatchingData:
    SkillLevelType: SkillLevelType = field(default_factory=SkillLevelType)
    GeneralWorkstationData: GeneralWorkstationData = field(default_factory=GeneralWorkstationData)

@dataclass
class EntityQualifier:
    SMT_Side: str = ''   # 'single' | 'double'
    SMT_THT: str = ''    # 'TRUE' | 'FALSE'

    def __getitem__(self, key: str) -> str:
        return getattr(self, key)


@dataclass
class Entity:
    idShort: str
    entityType: str  # 'SelfManagedEntity' | 'CoManagedEntity'
    qualifier: EntityQualifier = field(default_factory=EntityQualifier)
    statements: Dict[str, 'Entity'] = field(default_factory=dict)


@dataclass
class HierarchicalStructures:
    ArcheType: str = ''
    entities: Dict[str, Entity] = field(default_factory=dict)  # 최상위 entity idShort → Entity

    def entityType(self, category: str) -> Dict[str, Entity]:

        out: Dict[str, Entity] = {}
        for top in self.entities.values():
            self._walk(top, category, out)
        return out

    @staticmethod
    def _walk(ent: Entity, target: str, out: Dict[str, Entity]) -> None:
        if ent.entityType == target:
            out[ent.idShort] = ent
        for child in ent.statements.values():
            HierarchicalStructures._walk(child, target, out)

@dataclass
class Property:
    """AAS Property — 단일 .value 노출 (DepType, CycleTimeSec, ...)."""
    value: Any = None


@dataclass
class BomQualifier:
    """InputBOM ref 의 qualifier — Quantity 만 모델링."""
    Quantity: float = 0.0


class BomRef(dict):
    """InputBOM — multi-key dict ``{process_idShort: quantity, ...}``.

    JSON 의 InputBOM SubmodelElementList 안 ReferenceElement 들을 한 dict 으로
    평탄화. 각 (key, value) 의 출처::

        key   ← _CD_URL_RE.search(ref.value).group('idShort')   # ref 의 URL
        value ← ref.qualifier.Quantity (float)                  # ref 의 qualifier

    원본 ``(URL, BomQualifier)`` 쌍은 ``self.refs`` 로 보존(추적/디버깅).
    빈 BomRef 부터 ``add()`` 로 채우거나, ``refs=`` 에 list 를 한 번에 전달.
    """

    def __init__(self, refs: List = None):
        super().__init__()
        self.refs: List = []
        if refs:
            for url, qual in refs:
                self.add(url, qual)

    def add(self, value: str, qualifier: BomQualifier) -> None:
        m = _CD_URL_RE.search(value)
        if m:
            self[m.group('idShort')] = float(qualifier.Quantity)
            self.refs.append((value, qualifier))


@dataclass
class ProcessNode:
    """ManufacturingProcess 의 한 process step (예: VD7_10)."""
    DepType: Property = field(default_factory=Property)
    DepPrev: Property = field(default_factory=Property)
    CycleTimeSec: Property = field(default_factory=Property)
    DefectRate: Property = field(default_factory=Property)
    InputBOM: BomRef = field(default_factory=BomRef)


@dataclass
class ProcessGroup:
    """ProcessGroup (예: VD7FwInput) — process 들의 dict."""
    processes: Dict[str, ProcessNode] = field(default_factory=dict)

    def __getitem__(self, key: str) -> ProcessNode:
        return self.processes[key]


@dataclass
class ManufacturingProcess:
    """ManufacturingProcess Submodel — group 들의 dict."""
    groups: Dict[str, ProcessGroup] = field(default_factory=dict)

    def __getitem__(self, key: str) -> ProcessGroup:
        return self.groups[key]


# ── JSON 로더 ─────────────────────────────────────────────────────────────
#
# 진입점::
#
#     wwm = load_workstation_worker_matching_data('WorkstationWorkerMatchingDataAAS.json')
#     hs  = load_hierarchical_structures('MODEL_A.json')
#     mp  = load_manufacturing_process('MODEL_A.json')
#
# 위 dataclass 와 동일한 path-style (``view.<idShort>``, ``view[i]``,
# ``view.value``, ``view.qualifier['type']`` 등) 로 raw JSON 을 navigate
# 하기 위해 ``AasView`` wrapper 를 사용한다. 정의되지 않은 필드(description,
# semanticId, displayName 등) 는 무시. 누락/불일치는 RuntimeError 로 raise.
#


def load_workstation_worker_matching_data(json_path: str) -> WorkstationWorkerMatchingData:
    """WWM AAS JSON → WorkstationWorkerMatchingData."""
    sm = AasView(_find_submodel(_read_json(json_path), 'WorkstationWorkerMatchingData'))

    skill = SkillLevelType(levels=[
        SkillLevelProperty(idShort=p.idShort, value=p.value)
        for p in sm.SkillLevelType
    ])

    infos: List[WorkstationInformation] = []
    for wsi in sm.GeneralWorkstationData.WorkstationInformation:
        apgs = [
            AssignedProcessGroupRef(
                value=[GlobalReference(value=k.value) for k in ref.value]
            )
            for ref in wsi.AssignedProcessGroups
        ]
        wcr = {
            rec.WorkerId.value: skill[rec.SkillLevel.value]
            for rec in wsi.WorkstationConfigurationRecords
        }
        infos.append(WorkstationInformation(
            AssignedProcessGroups=apgs,
            WorkstationConfigurationRecords=wcr,
        ))

    return WorkstationWorkerMatchingData(
        SkillLevelType=skill,
        GeneralWorkstationData=GeneralWorkstationData(WorkstationInformation=infos),
    )


def load_hierarchical_structures(json_path: str) -> HierarchicalStructures:
    """MODEL_N AAS JSON → HierarchicalStructures."""
    sm = AasView(_find_submodel(_read_json(json_path), 'HierarchicalStructures'))
    arche = sm.ArcheType.value if 'ArcheType' in sm else ''
    entities = {
        elem.idShort: _parse_entity(elem)
        for elem in sm if elem.modelType == 'Entity'
    }
    return HierarchicalStructures(ArcheType=arche, entities=entities)


def load_manufacturing_process(json_path: str) -> ManufacturingProcess:
    """MODEL_N AAS JSON → ManufacturingProcess.

    ProcessGroup 은 자식이 모두 SubmodelElementCollection (ProcessNode) 인 것만
    인식. ProcessType (자식이 Property 인 enum 류) 같은 메타 collection 은 제외 —
    토폴로지 기반 식별이라 idShort 의존 없음.
    """
    sm = AasView(_find_submodel(_read_json(json_path), 'ManufacturingProcess'))
    groups: Dict[str, ProcessGroup] = {}
    for elem in sm:
        if elem.modelType != 'SubmodelElementCollection':
            continue
        children = list(elem)
        if children and all(c.modelType == 'SubmodelElementCollection' for c in children):
            groups[elem.idShort] = _parse_process_group(elem)
    return ManufacturingProcess(groups=groups)


# ── 내부 파서 (AasView 만 받음) ─────────────────────────────────────────────

def _parse_entity(view: 'AasView') -> Entity:
    return Entity(
        idShort=view.idShort,
        entityType=view.entityType,
        qualifier=EntityQualifier(
            SMT_Side=view.qualifier.get('SMT_Side', ''),
            SMT_THT=view.qualifier.get('SMT_THT', ''),
        ),
        statements={
            ce.idShort: _parse_entity(ce)
            for ce in view.statements if ce.modelType == 'Entity'
        },
    )


def _parse_process_group(view: 'AasView') -> ProcessGroup:
    return ProcessGroup(processes={
        proc.idShort: _parse_process_node(proc) for proc in view
    })


def _parse_process_node(view: 'AasView') -> ProcessNode:
    pn = ProcessNode()
    for elem in view:
        idsh = elem.idShort
        if idsh == 'DepType':
            pn.DepType = Property(value=elem.value)
        elif idsh == 'DepPrev':
            pn.DepPrev = Property(value=elem.value)
        elif idsh == 'CycleTimeSec':
            pn.CycleTimeSec = Property(value=elem.value)
        elif idsh == 'DefectRate':
            pn.DefectRate = Property(value=elem.value)
        elif idsh == 'InputBOM':
            pn.InputBOM = _parse_input_bom(elem)
    return pn


def _parse_input_bom(view: 'AasView') -> BomRef:
    bom = BomRef()
    for ref in view:
        qual = BomQualifier(Quantity=ref.qualifier.get('Quantity', 0.0))
        keys = ref.value
        if len(keys) > 0:
            bom.add(keys[0].value, qual)
    return bom


# ── AasView: raw JSON 을 dataclass 와 동일한 path-style 로 navigate ──────────

class AasView:
    """Raw AAS JSON 노드를 dot/index/qualifier 로 navigate 하기 위한 얇은 wrapper.

    지원 패턴 (dataclass 측 path 와 동일한 모양)::

        view.<idShort>          # 자식 SubmodelElement (idShort 매칭)
        view[idShort]           # 위와 동일 (대괄호 형태)
        view[i]                 # SubmodelElementList/Collection 의 i 번째 자식
        view.value              # Property→casted, ReferenceElement→keys list view,
                                # Collection/List→자식 list view, key→URL string
        view.idShort            # 자기 자신의 idShort
        view.entityType         # Entity.entityType
        view.modelType          # 자기 자신의 modelType
        view.qualifier['type']  # qualifier 의 type 매칭 → casted value (없으면 KeyError)
        view.qualifier.get(t, d)# default 지원
        view.statements         # Entity 자식들 list view
        for child in view: ...  # collection/list 자식 iterate
        len(view)               # 자식 수
        'idShort' in view       # 자식 존재 여부

    누락/불일치는 AttributeError/KeyError 로 즉시 raise (CLAUDE.md fallback 금지).
    """

    __slots__ = ('_raw',)

    def __init__(self, raw):
        self._raw = raw  # dict (단일 노드) 또는 list (자식 collection)

    def __repr__(self):
        if isinstance(self._raw, list):
            return f'<AasView list[{len(self._raw)}]>'
        return (f'<AasView idShort={self._raw.get("idShort")!r} '
                f'mt={self._raw.get("modelType")!r}>')

    # 자기 메타 / value / 자식-by-idShort
    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(name)
        raw = self._raw

        if isinstance(raw, dict):
            if name in ('idShort', 'entityType', 'modelType', 'valueType', 'category'):
                return raw.get(name)
            if name == 'qualifier':
                return _QualifierAccess(raw.get('qualifiers') or [])
            if name == 'statements':
                return AasView(raw.get('statements') or [])
            if name == 'value':
                return _value_of(raw)
        return self._child(name)

    def _children(self):
        raw = self._raw
        if isinstance(raw, list):
            return raw
        v = raw.get('value')
        if isinstance(v, list):
            return v
        return raw.get('submodelElements') or raw.get('statements') or []

    def _child(self, idShort: str) -> 'AasView':
        for c in self._children():
            if isinstance(c, dict) and c.get('idShort') == idShort:
                return AasView(c)
        raise AttributeError(f"No child idShort={idShort!r}")

    def __getitem__(self, key):
        if isinstance(key, int):
            c = self._children()[key]
            return AasView(c) if isinstance(c, dict) else c
        return self._child(key)

    def __contains__(self, idShort: str) -> bool:
        return any(isinstance(c, dict) and c.get('idShort') == idShort
                   for c in self._children())

    def __iter__(self):
        for c in self._children():
            yield AasView(c) if isinstance(c, dict) else c

    def __len__(self):
        return len(self._children())


def _value_of(raw: dict):
    """SubmodelElement 의 의미적 .value 반환 — modelType 별로 분기."""
    mt = raw.get('modelType')
    v = raw.get('value')
    if mt == 'Property':
        return _cast_value(raw.get('valueType', ''), v)
    if mt == 'ReferenceElement':
        return AasView((v or {}).get('keys') or [])  # keys list 로 평탄화
    if isinstance(v, list):
        return AasView(v)  # Collection / List
    return v  # ReferenceKey 등 (raw URL 문자열)


def _cast_value(value_type: str, raw):
    """xs: 타입에 따라 문자열 raw 를 파이썬 값으로 변환."""
    if raw is None or raw == '':
        return raw
    if value_type in ('xs:integer', 'xs:int', 'xs:long', 'xs:short'):
        return int(raw)
    if value_type in ('xs:float', 'xs:double', 'xs:decimal'):
        return float(raw)
    if value_type == 'xs:boolean':
        return str(raw).strip().upper() == 'TRUE'
    return raw


class _QualifierAccess:
    """qualifier['type'] 으로 type 매칭 → value (casted) lookup."""

    __slots__ = ('_q',)

    def __init__(self, qualifiers: list):
        self._q = qualifiers

    def __getitem__(self, qtype: str):
        for q in self._q:
            if q.get('type') == qtype:
                return _cast_value(q.get('valueType', ''), q.get('value'))
        raise KeyError(qtype)

    def __contains__(self, qtype: str) -> bool:
        return any(q.get('type') == qtype for q in self._q)

    def get(self, qtype: str, default: Any = None) -> Any:
        try:
            return self[qtype]
        except KeyError:
            return default


# ── 최저 수준 헬퍼 ────────────────────────────────────────────────────────

def _read_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _find_submodel(doc: dict, idShort: str) -> dict:
    for sm in (doc.get('submodels') or []):
        if sm.get('idShort') == idShort:
            return sm
    raise RuntimeError(f"Submodel idShort={idShort!r} not found")


