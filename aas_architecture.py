# -*- coding: utf-8 -*-
"""AAS 메타모델 — 시뮬레이션이 AAS 데이터를 받는 유일한 창구.

지금 단계: 각 SME / 데이터형식이 갖는 **속성만** 선언. 접근 규칙·로직은 추후 부착.

자식 접근 통일 규칙 (TBD)
    container.idShort        # 자식 idShort 가 고정 — idShort 그대로 속성명
    container[idShort]       # 자식 idShort 가 다양 (SMC)
    container[i]             # 정수 인덱스 (SML, 순서 의미)
    container[...]           # 모든 자식
    container[predicate]     # callable 필터

SME 자체 필드
    .idShort  .semanticId  .Qualifier  .value  ...

Qualifier
    sme.Qualifier              → {type: value} dict
    sme.Qualifier['SMT_Side']  → value 직접

경로 deref (TBD)
    refElem.target
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


__all__ = ['ProvisionofSimulationModelsAAS', 'load']


# region
# ====================================================================
# 열거형
# ====================================================================
class EntityType(str, Enum):
    SelfManagedEntity = 'SelfManagedEntity'
    CoManagedEntity = 'CoManagedEntity'
# endregion


# region
# ====================================================================
# 참조 / 경로 / Qualifier (데이터 형식)
# ====================================================================
class semanticId(str):
    """ConceptDescription 참조 — 인스턴스 자체가 CD URL 문자열.

    >>> s = semanticId('https://.../ids/cd/Process/1/0')
    >>> s == 'https://.../ids/cd/Process/1/0'   # True (str 그 자체)
    """


class SMEPath(list):
    """SME 경로 — 식별자(URL/IRDI)와 idShort 들의 sequence (list 의 일종).

    `List[semanticId]` 와의 차이:
        - SMEPath: 키들이 chain 으로 연결돼 단일 대상 SME 를 가리킴 (target = 경로 끝)
        - List[semanticId]: 각 키가 독립된 대상을 가리킴 (target = 대상들의 list)
    """
    @classmethod
    def _parse(cls, raw_reference: dict | None) -> 'SMEPath':
        """raw reference dict → SMEPath 인스턴스 (체인 경로용). 내부 전용."""
        if not raw_reference:
            return cls()
        return cls(semanticId(key.get('value', '')) for key in raw_reference.get('keys', []))

    @staticmethod
    def _parse_as_list(raw_reference: dict | None) -> List[semanticId]:
        """raw reference dict → List[semanticId] (각 키가 독립 대상인 ref 용).
        SMEPath 가 아닌 일반 reference 들의 공통 파서 — SMEPath 안에 모아둠. 내부 전용."""
        if not raw_reference:
            return []
        return [semanticId(key.get('value', '')) for key in raw_reference.get('keys', [])]


class Qualifier(dict):
    """`{type: value}` dict 자체. 이름 Qualifier 로 식별, 추후 메서드 부착 위치."""
# endregion


# region
# ====================================================================
# SubmodelElement 베이스 — 모든 SME 공통 필드
# ====================================================================
@dataclass(kw_only=True)
class SubmodelElement:
    # region [구조]
    idShort: str = ''
    semanticId: semanticId                                       # 필수
    Qualifier: Qualifier = field(default_factory=Qualifier)      # {type: value}
    value: (Dict[str, SubmodelElement]                           # Submodel, SMC 자식
            | List[SubmodelElement]                              # SML 자식
            | List[semanticId] | SMEPath                         # ReferenceElement 경로
            | str | int | float | bool                           # Property scalar
            | None) = None
    # endregion

    # region [로직]
    def __getattr__(self, name: str):
        """`.idShort` 자식 접근: `value` dict 에서 lookup. (Submodel/SMC 가 해당)
        `value` 가 dict 가 아닌 SME (Property scalar, SML list 등) 는 자연스럽게 TypeError."""
        return self.__dict__.get('value')[name]
    # endregion
# endregion


# region
# ====================================================================
# 구체 SME 타입 — 자체 필드만
# ====================================================================
@dataclass(kw_only=True)
class Submodel(SubmodelElement):
    """자식 idShort 로 키된 dict."""
    id: str = ''                                                 # AAS V3 unique identifier (URL)
    value: Dict[str, SubmodelElement] = field(default_factory=dict)


@dataclass(kw_only=True)
class SubmodelElementCollection(SubmodelElement):
    """자식 idShort 로 키된 dict."""
    value: Dict[str, SubmodelElement] = field(default_factory=dict)


@dataclass(kw_only=True)
class SubmodelElementList(SubmodelElement):
    """순서 의미 — index 로 접근하는 list."""
    value: List[SubmodelElement] = field(default_factory=list)


@dataclass(kw_only=True)
class Property(SubmodelElement):
    value: Any = None


@dataclass(kw_only=True)
class Range(SubmodelElement):
    min: Any = None
    max: Any = None


@dataclass(kw_only=True)
class Entity(SubmodelElement):
    # region [구조]
    entityType: EntityType                                       # 필수 (default 없음)
    statements: Dict[str, SubmodelElement] = field(default_factory=dict)
    # endregion

    # region [로직]
    def __getattr__(self, name: str):
        """Entity 의 자식은 `value` 가 아니라 `statements` dict 에서 lookup."""
        statements = self.__dict__.get('statements')
        if isinstance(statements, dict) and name in statements:
            return statements[name]
        raise AttributeError(name)
    # endregion


@dataclass(kw_only=True)
class RelationshipElement(SubmodelElement):
    first: List[semanticId] | SMEPath                            # 필수
    second: List[semanticId] | SMEPath                           # 필수


@dataclass(kw_only=True)
class ReferenceElement(SubmodelElement):
    # region [구조]
    value: List[semanticId] | SMEPath                            # 필수 — 가리키는 경로
    # endregion

    # region [로직]
    @property
    def target(self):
        """value 의 키들로 대상 SME 를 찾는다. 각 키는 외부 식별자(URL/IRDI) 또는 idShort.
            - 식별자: 모든 AAS walk 해서 Submodel.id 또는 SME.semanticId 와 직접 일치 비교
            - idShort: 현재 노드의 자식 dict lookup
            - 첫 키 resolve 후 나머지를 path 로 시도 → path 깨지면 keys 전체를 list 로 간주
        """
        keys = self.value
        if not keys:
            return None
        first = _resolve_identifier(keys[0])
        if first is None:                                          # 대상 AAS 미로드 등 → 조기 None
            return None
        if len(keys) == 1:
            return first
        # keys[1:] 가 모두 식별자 — path 안에서 찾을 수 있으면 path, 아니면 list
        if all(_is_identifier(key) for key in keys[1:]):
            node = first
            for key in keys[1:]:
                found = _walk_for_match(node, key)
                if found is None:
                    return [_resolve_identifier(key) for key in keys]
                node = found
            return node
        # 첫 식별자 + idShort 들 (단일 path)
        node = first
        for key in keys[1:]:
            node = node.value[key]
        return node
    # endregion
# endregion


# region
# ====================================================================
# 내부 — 외부 식별자 (URL/IRDI) → SME 매칭
# Submodel.id 또는 SME.semanticId 와 문자열 직접 비교.
# ====================================================================
def _is_identifier(key: str) -> bool:
    """key 가 외부 식별자(IRI URL 또는 IRDI) 인지. idShort 와 구분.
    - IRI: '://' 포함 (URL)
    - IRDI: '#' 포함 (ECLASS '0173-1#XX-NNNNNN#VVV', CDD 등)"""
    return '://' in key or '#' in key


def _resolve_identifier(identifier: str):
    """모든 AAS 의 submodel walk 해서 Submodel.id 또는 SME.semanticId 가
    identifier 와 정확히 일치하는 SME 반환. 못 찾으면 None."""
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                if submodel.id == identifier:
                    return submodel
                found = _walk_for_match(submodel, identifier)
                if found is not None:
                    return found
    return None


def _walk_for_match(node, target_identifier: str):
    """node subtree 에서 semanticId == target_identifier 인 SME 찾기 (자기 자신 포함).
    `value` (Submodel/SMC/SML) 와 `statements` (Entity) 만 자식 컨테이너로 인정.
    ReferenceElement.value (List[semanticId] str 들) 같은 비-SME 리스트는 자식 아님."""
    if node.semanticId == target_identifier:
        return node
    for children_attr in ('value', 'statements'):
        children = node.__dict__.get(children_attr)
        if isinstance(children, dict):
            for child in children.values():
                found = _walk_for_match(child, target_identifier)
                if found is not None:
                    return found
        elif isinstance(children, list):
            for child in children:
                if isinstance(child, SubmodelElement):
                    found = _walk_for_match(child, target_identifier)
                    if found is not None:
                        return found
    return None
# endregion


# region
# ====================================================================
# AAS 컨테이너 + 외부 노출 인스턴스
# 시뮬 코드는 모듈 레벨 인스턴스 `ProvisionofSimulationModelsAAS` 만 다룸.
# ====================================================================
@dataclass(kw_only=True)
class AssetAdministrationShell:
    """AAS 컨테이너 클래스. 범용 타입."""
    # region [구조]
    idShort: str = ''
    submodels: Dict[str, Submodel] = field(default_factory=dict)
    # endregion

    # region [로직]
    def __getattr__(self, name: str) -> Submodel:
        """submodel idShort 로 attribute 접근. `aas.SimulationModels` 등.
        누락 시 KeyError 자연 발생 (hasattr/getattr default 호환 X — 호출부에서 처리)."""
        return self.__dict__.get('submodels')[name]
    # endregion


# AAS 인스턴스 (모듈 레벨). 외부 노출은 `ProvisionofSimulationModelsAAS` 뿐.
ProvisionofSimulationModelsAAS = AssetAdministrationShell()
WorkstationWorkerMatchingDataAAS = AssetAdministrationShell()    # TODO: 풀네임 확인
ProductAAS: List[AssetAdministrationShell] = []                  # MODEL_N 들 (load 호출 시 채워짐)


# 모든 로드된 AAS 인스턴스 보관 (내부). cross-AAS deref 시 lookup 용.
_aas_registry: Dict[str, AssetAdministrationShell | List[AssetAdministrationShell]] = {
    'ProvisionofSimulationModelsAAS': ProvisionofSimulationModelsAAS,
    'WorkstationWorkerMatchingDataAAS': WorkstationWorkerMatchingDataAAS,
    'ProductAAS': ProductAAS,
}


def load(json_path: str) -> None:
    """JSON 파일 하나 로드. 여러 번 호출해 여러 AAS 를 합쳐 사용.

    AAS idShort 로 라우팅:
      - 'ProvisionofSimulationModelsAAS' → 모듈 레벨 PSM 인스턴스 채움
      - 'WorkstationWorkerMatchingDataAAS' → 모듈 레벨 WWM 인스턴스 채움
      - 그 외 (MODEL_N 등) → 새 AssetAdministrationShell 만들어 ProductAAS 리스트에 append

    ReferenceElement 들은 lazy — target 접근 시점에 _aas_registry 통해 cross-AAS deref (TBD).
    """
    with open(json_path, encoding='utf-8') as file:
        raw_data = json.load(file)

    aas_idShort = raw_data['assetAdministrationShells'][0]['idShort']

    if aas_idShort == 'ProvisionofSimulationModelsAAS':
        target_aas = ProvisionofSimulationModelsAAS
    elif aas_idShort == 'WorkstationWorkerMatchingDataAAS':
        target_aas = WorkstationWorkerMatchingDataAAS
    else:
        target_aas = AssetAdministrationShell()
        ProductAAS.append(target_aas)

    target_aas.idShort = aas_idShort
    target_aas.submodels = {
        raw_submodel['idShort']: _build_sme(raw_submodel)
        for raw_submodel in raw_data.get('submodels', [])
    }
# endregion


# region
# ====================================================================
# 내부 — JSON dict → SME 인스턴스 빌더 (재귀)
# ====================================================================
def _build_sme(raw_sme: dict) -> SubmodelElement:
    """raw JSON dict → SubmodelElement 인스턴스 (재귀)."""

    # 공통 필드
    semantic_keys = (raw_sme.get('semanticId') or {}).get('keys') or []
    semantic_value = semantic_keys[0].get('value', '') if semantic_keys else ''
    base_fields = {
        'idShort': raw_sme.get('idShort', ''),
        'semanticId': semanticId(semantic_value),
        'Qualifier': Qualifier(
            (qualifier['type'], _cast_value(qualifier.get('value'), qualifier.get('valueType')))
            for qualifier in raw_sme.get('qualifiers', [])
        ),
    }

    modelType = raw_sme['modelType']
    if modelType == 'Property':
        return Property(**base_fields,
                        value=_cast_value(raw_sme.get('value'), raw_sme.get('valueType')))
    if modelType == 'Range':
        valueType = raw_sme.get('valueType')
        return Range(**base_fields,
                     min=_cast_value(raw_sme.get('min'), valueType),
                     max=_cast_value(raw_sme.get('max'), valueType))
    if modelType == 'SubmodelElementCollection':
        children = {child['idShort']: _build_sme(child)
                    for child in raw_sme.get('value', [])}
        return SubmodelElementCollection(**base_fields, value=children)
    if modelType == 'SubmodelElementList':
        return SubmodelElementList(
            **base_fields,
            value=[_build_sme(child) for child in raw_sme.get('value', [])],
        )
    if modelType == 'Submodel':
        children = {child['idShort']: _build_sme(child)
                    for child in raw_sme.get('submodelElements', [])}
        return Submodel(**base_fields, id=raw_sme.get('id', ''), value=children)
    if modelType == 'Entity':
        return Entity(
            **base_fields,
            entityType=EntityType(raw_sme['entityType']),
            statements={child['idShort']: _build_sme(child)
                      for child in raw_sme.get('statements', [])},
        )
    if modelType == 'ReferenceElement':
        return ReferenceElement(
            **base_fields,
            value=_parse_ref_keys(raw_sme.get('value')),
        )
    if modelType == 'RelationshipElement':
        return RelationshipElement(
            **base_fields,
            first=_parse_ref_keys(raw_sme.get('first')),
            second=_parse_ref_keys(raw_sme.get('second')),
        )
    # 모르는 modelType — base 로 (시뮬에서 안 쓰는 종류)
    return SubmodelElement(**base_fields)


def _parse_ref_keys(raw_reference: dict | None) -> List[semanticId]:
    """raw reference dict → List[semanticId]. (List[semanticId] vs SMEPath 분기는 TBD)"""
    if not raw_reference:
        return []
    return [semanticId(key.get('value', '')) for key in raw_reference.get('keys', [])]


def _cast_value(raw_value, valueType: str | None):
    """raw value 를 AAS valueType (xs:int, xs:double 등) 에 맞춰 캐스트.
    valueType 없거나 알려지지 않은 타입이면 raw 그대로 반환."""
    if raw_value is None or not valueType:
        return raw_value
    type_name = valueType.split(':')[-1]
    if type_name in ('int', 'integer', 'long', 'short', 'byte'):
        return int(raw_value)
    if type_name in ('float', 'double', 'decimal'):
        return float(raw_value)
    if type_name == 'boolean':
        return raw_value in (True, 'true', 'True', 'TRUE', 1, '1')
    return raw_value
# endregion
