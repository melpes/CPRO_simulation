# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


_CD_URL_RE = re.compile(r'/ids/cd/(?P<idShort>[^/]+)/[^/]+/[^/]+/?$')  # 확정

@dataclass
class GlobalReference:
    value: str

    @property
    def Process(self) -> str:
        m = _CD_URL_RE.search(self.value)
        return m.group('idShort')

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
    idShort: str = ''
    AssignedProcessGroups: List[AssignedProcessGroupRef] = field(default_factory=list)
    WorkstationConfigurationRecords: Dict[str, int] = field(default_factory=dict)


@dataclass
class GeneralWorkstationData:
    WorkstationInformation: Dict[str, WorkstationInformation] = field(default_factory=dict)


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

def load_workstation_worker_matching_data(json_path: str) -> WorkstationWorkerMatchingData:
    """WWM AAS JSON → WorkstationWorkerMatchingData."""
    sm = AasView(_find_submodel(_read_json(json_path), 'WorkstationWorkerMatchingData'))

    skill = SkillLevelType(levels=[
        SkillLevelProperty(idShort=p.idShort, value=int(p.value))
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
            idShort=wsi.idShort,
            AssignedProcessGroups=apgs,
            WorkstationConfigurationRecords=wcr,
        ))

    return WorkstationWorkerMatchingData(
        SkillLevelType=skill,
        GeneralWorkstationData=GeneralWorkstationData(
            WorkstationInformation={ws.idShort: ws for ws in infos}),
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
    sm = AasView(_find_submodel(_read_json(json_path), 'ManufacturingProcess'))
    groups: Dict[str, ProcessGroup] = {}
    for elem in sm:
        if elem.modelType != 'SubmodelElementCollection':
            continue
        children = list(elem)
        if children and all(c.modelType == 'SubmodelElementCollection' for c in children):
            groups[elem.idShort] = _parse_process_group(elem)
    return ManufacturingProcess(groups=groups)


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
            pn.CycleTimeSec = Property(value=int(elem.value))
        elif idsh == 'DefectRate':
            pn.DefectRate = Property(value=float(elem.value))
        elif idsh == 'InputBOM':
            pn.InputBOM = _parse_input_bom(elem)
    return pn


def _parse_input_bom(view: 'AasView') -> BomRef:
    bom = BomRef()
    for ref in view:
        # Quantity 는 BomQualifier(Quantity: float) 라 명시 float() 으로 cast.
        # JSON 에 valueType=xs:int 이지만 value="1.1" 같은 데이터 결함이 있어
        # AasView 의 valueType 기반 자동 cast 를 거치지 않고 raw 에서 직접.
        qty = float(ref.qualifier.get('Quantity', '0') or 0)
        keys = ref.value
        if len(keys) > 0:
            bom.add(keys[0].value, BomQualifier(Quantity=qty))
    return bom


class AasView:
    __slots__ = ('_raw',)

    def __init__(self, raw):
        self._raw = raw  # dict (단일 노드) 또는 list (자식 collection)

    def __repr__(self):
        if isinstance(self._raw, list):
            return f'<AasView list[{len(self._raw)}]>'
        return (f'<AasView idShort={self._raw.get("idShort")!r} '
                f'mt={self._raw.get("modelType")!r}>')

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
    mt = raw.get('modelType')
    v = raw.get('value')
    if mt == 'ReferenceElement':
        return AasView((v or {}).get('keys') or [])  # keys list 로 평탄화
    if isinstance(v, list):
        return AasView(v)  # Collection / List
    return v  # Property→raw string, ReferenceKey→URL string

class _QualifierAccess:

    __slots__ = ('_q',)

    def __init__(self, qualifiers: list):
        self._q = qualifiers

    def __getitem__(self, qtype: str):
        for q in self._q:
            if q.get('type') == qtype:
                return q.get('value')
        raise KeyError(qtype)

    def __contains__(self, qtype: str) -> bool:
        return any(q.get('type') == qtype for q in self._q)

    def get(self, qtype: str, default: Any = None) -> Any:
        try:
            return self[qtype]
        except KeyError:
            return default

def _read_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _find_submodel(doc: dict, idShort: str) -> dict:
    for sm in (doc.get('submodels') or []):
        if sm.get('idShort') == idShort:
            return sm


