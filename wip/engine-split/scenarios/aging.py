# -*- coding: utf-8 -*-
# 시나리오 ③ 핵심공정 설비수량 — 에이징(Aging Test) 설비 최적 사용.
#   입력  : 사용 스위치 수 · 스위치당 Port 수 · 작업자당 동시 담당 수량  (1조합)
#           → AAS AssemblyByWorker > WWM_AgingLine 에 반영
#   최적해: 생산시간·전력 최소.  여러 설비구성은 여러 번 호출해 비교(파레토).
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

import os
import sys

# 단독 실행 대비 — 이 파일의 폴더와 그 상위를 import 경로에 넣는다.
#   패키지 배포:  scenario.py 와 engine.py 가 같은 폴더
#   repo:        scenarios/<name>.py 와 engine.py 가 한 단계 떨어져 있음
_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.dirname(_HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import engine

NAME = 'aging'
OBJECTIVE = '설비구성별 생산시간·전력 — 구성별로 호출해 파레토 비교'


class PoItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qty: Optional[int] = Field(None, ge=0, description='주문 수량')
    due_day: Optional[int] = Field(None, ge=1, description='납기일 (일)')


class Request(BaseModel):
    """한 번의 실행 = 한 설비구성. AAS 의 WWM_AgingLine 에 반영된다.

    동시 가동 수량 = min(사용 스위치 수 × Port 수, 작업자 수 × 작업자당 동시 담당 수량)
    """
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['aging'] = 'aging'
    po: Optional[Dict[str, PoItem]] = Field(None, description='모델별 주문수량·납기')
    switch_count: Optional[int] = Field(None, ge=1, description='사용 PoE 스위치 수')
    port_count: Optional[int] = Field(None, ge=1, description='스위치 1대당 Port 수')
    units_per_worker: Optional[int] = Field(None, ge=1, description='작업자 1인 동시 담당 수량')
    overrides: Optional[dict] = None


def run(model: engine.TrainedModel, request: dict, seed: int):
    env_overrides = model.prepare(request)                     # AAS 반영(PO·override)
    model.apply_aging_equipment(switch_count=request.get('switch_count'),
                                port_count=request.get('port_count'),
                                units_per_worker=request.get('units_per_worker'))
    equipment = model.aging_equipment()                        # AAS 에서 되읽음

    env, summary = model.simulate(seed, env_overrides)

    condition = {'order_quantity': model.purchase_order(), **equipment}
    candidate = engine.make_candidate(env, summary, 0, condition)
    candidate['flags']['is_optimum'] = True

    result = {'scenario': NAME, 'seed': seed, 'objective': OBJECTIVE,
              'candidates': [candidate]}
    metric = candidate['metric']
    line = (f"[aging] 스위치={equipment['switch_count']}x{equipment['port_count']} "
            f"동시가동={equipment['concurrent_operation_count']} "
            f"총생산시간={metric['makespan_days']:.2f}일 "
            f"전력={metric['power_kwh']['total']:.0f}kWh 완주={metric['target_met']}")
    return result, line


if __name__ == '__main__':
    engine.cli(sys.modules[__name__])
