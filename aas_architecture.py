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


@dataclass(kw_only=True)
class SMEPath:
    """SME 경로 — TBD (만들면서 구조 확정)."""
    ...


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
        """`value` 의 실제 타입을 보고 분기해 대상의 특정 속성값 반환."""
        if isinstance(self.value, SMEPath):
            return ...
        if isinstance(self.value, list):
            return ...

    # endregion
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

    동작 (구현 TBD):
      1. JSON 읽고 AAS idShort 식별
      2. idShort 가 'ProvisionofSimulationModelsAAS' / 'WorkstationWorkerMatchingDataAAS'
         이면 해당 모듈 레벨 인스턴스에 채움. MODEL_N 패턴이면 새 AAS 만들어 ProductAAS 리스트에 append.
      3. submodels 빌드 (재귀)
      4. ReferenceElement 들은 lazy — target 접근 시점에 _aas_registry 통해 cross-AAS deref
    """
    ...
# endregion
