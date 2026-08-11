# -*- coding: utf-8 -*-
# 요청 스키마 — run_trained 가 던지던 ValueError(미지 모델·미허용 override·points/moves 누락)를
# POST 시점 422 로 선반영한다. 단위 혼재(일/초/시/분)가 실수 유발점이라 description 에 명시.
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class PoItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qty: Optional[int] = Field(None, ge=0, description='생산 수량')
    due_day: Optional[int] = Field(None, ge=1, description='납기일 (일)')
    registered_day: Optional[int] = Field(None, ge=0, description='등록일 (일, 선택)')


class InitialState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    initial_stock: Optional[Dict[str, float]] = Field(None, description='{카테고리: 초기 재고}')


class Overrides(BaseModel):
    """허용 키만. 그 외는 422 (extra='forbid')."""
    model_config = ConfigDict(extra='forbid')
    seed: Optional[int] = Field(None, description='난수 시드. 같은 시드 = 바이트 동일 결과')
    ReplenishLeadDay: Optional[int] = Field(None, ge=0, description='자재 발주 리드타임 (일)')
    IdleWorkerThreshold: Optional[int] = Field(None, ge=0, description='작업자 유휴 위반 임계 (초)')
    WorkStartTime: Optional[float] = Field(None, ge=0, le=24, description='근무 시작 (시)')
    WorkEndTime: Optional[float] = Field(None, ge=0, le=24, description='근무 종료 (시)')
    BreakStart: Optional[float] = Field(None, ge=0, le=24, description='휴게 시작 (시)')
    BreakDuration: Optional[float] = Field(None, ge=0, description='휴게 길이 (분)')
    DefaultProcessConsumedPowerKw: Optional[float] = Field(None, ge=0, description='공장 기저전력 (kW)')
    initial_state: Optional[InitialState] = None
    ScenarioMode: Optional[Literal['FINITE', 'STEADY']] = None
    MaxEpisodeSec: Optional[int] = Field(None, ge=1, description='에피소드 상한 (초)')
    InfiniteStock: Optional[bool] = None


Po = Dict[str, PoItem]


class _Base(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overrides: Optional[Overrides] = None


class ScheduleRequest(_Base):
    """② 생산계획 — 고정 수량 생산계획 최적화. 최적해 = 납기 대비 개선율 최대."""
    scenario: Literal['schedule']
    po: Po = Field(..., description='모델별 주문수량·납기')


class InfiniteRequest(_Base):
    """① 무한생산 — 한 번에 생산할 수량 최적화. 최적해 = 전력 원단위 최소."""
    scenario: Literal['infinite']
    points: List[Po] = Field(..., min_length=1, description='생산 수량 후보 리스트 (case 가 됨)')


class ReallocSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    src: Optional[str] = Field(None, description='차출 라인 (기본 WWM_SemiAssemblyLine)')
    moves: Dict[str, int] = Field(..., min_length=1, description='{타겟 라인: 이동 인원}')
    idle_trigger_sec: Optional[float] = Field(None, ge=0, description='연속 유휴 발동 임계 (초)')
    tick_sec: Optional[float] = Field(None, gt=0, description='감시 주기 (초)')


class ReallocRequest(_Base):
    """②-1 유휴 작업자 재배치 — 최적해 = 납기 개선율 + 재배치 개선율."""
    scenario: Literal['realloc']
    po: Po
    realloc: ReallocSpec


class AgingPoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    switch_count: int = Field(..., ge=0, description='사용 스위치 수 (PoE 스위치 대수)')
    port_count: int = Field(..., ge=0, description='스위치 1대당 Port 수')
    units_per_worker: int = Field(..., ge=0, description='작업자 1인 동시 담당 수량')
    worker_count: Optional[int] = Field(None, ge=1, description='에이징 작업자 수 (기본 AAS 값)')


class AgingRequest(_Base):
    """③ 핵심공정 설비수량 — 최적해 = 생산시간–전력 파레토."""
    scenario: Literal['aging']
    po: Po
    points: List[AgingPoint] = Field(..., min_length=1, description='설비구성 후보 리스트 (case 가 됨)')


RunRequest = Annotated[
    Union[ScheduleRequest, InfiniteRequest, ReallocRequest, AgingRequest],
    Field(discriminator='scenario'),
]
