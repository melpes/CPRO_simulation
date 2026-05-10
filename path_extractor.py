# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


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
    WorkstationConfigurationRecords: List[Dict[str, int]] = field(default_factory=list)


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
    def __init__(self, value: str = '', qualifier: BomQualifier = None):
        super().__init__()
        self.value = value
        self.qualifier = qualifier if qualifier is not None else BomQualifier()
        m = _CD_URL_RE.search(self.value)
        if m:
            self[m.group('idShort')] = float(self.qualifier.Quantity)


@dataclass
class ProcessNode:
    """ManufacturingProcess 의 한 process step (예: VD7_10)."""
    DepType: Property = field(default_factory=Property)
    DepPrev: Property = field(default_factory=Property)
    CycleTimeSec: Property = field(default_factory=Property)
    DefectRate: Property = field(default_factory=Property)
    InputBOM: List[BomRef] = field(default_factory=list)


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


