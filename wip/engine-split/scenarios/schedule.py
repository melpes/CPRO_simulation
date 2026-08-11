# -*- coding: utf-8 -*-
# 시나리오 ② 생산계획 — 정해진 주문수량(PO)의 생산계획 최적화.
#   입력  : 모델별 주문수량·납기 (→ AAS SimulationModel.PurchaseOrder)
#   최적해: 납기 대비 개선율 최대
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

NAME = 'schedule'
OBJECTIVE = '입력 납기 대비 개선율(due_improvement) 최대'


class PoItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qty: Optional[int] = Field(None, ge=0, description='주문 수량')
    due_day: Optional[int] = Field(None, ge=1, description='납기일 (일)')


class Request(BaseModel):
    """AAS 의 PurchaseOrder 에 반영된다. 생략한 모델은 AAS 기본값 유지."""
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['schedule'] = 'schedule'
    po: Optional[Dict[str, PoItem]] = Field(None, description='모델별 주문수량·납기')
    overrides: Optional[dict] = None


def run(model: engine.TrainedModel, request: dict, seed: int):
    env_overrides = model.prepare(request)                 # AAS 반영
    env, summary = model.simulate(seed, env_overrides)

    candidate = engine.make_candidate(env, summary, 0, {'order_quantity': model.purchase_order()})
    candidate['flags']['is_optimum'] = True

    result = {'scenario': NAME, 'seed': seed, 'objective': OBJECTIVE,
              'candidates': [candidate]}
    metric = candidate['metric']
    line = (f"[schedule] 총생산시간={metric['makespan_days']:.2f}일 "
            f"납기개선={engine.percent(metric['due_improvement']['overall'])} "
            f"완주={metric['target_met']} 전력={metric['power_kwh']['total']:.0f}kWh")
    return result, line


if __name__ == '__main__':
    engine.cli(sys.modules[__name__])
