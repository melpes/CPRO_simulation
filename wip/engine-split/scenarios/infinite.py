# -*- coding: utf-8 -*-
# 시나리오 ① 무한생산 — 한 번에 생산할 수량 최적화.
#   입력  : 생산 수량 1개 (→ AAS SimulationModel.PurchaseOrder)
#   최적해: 전력 원단위(총전력 ÷ 생산량) 최소  ← 여러 수량은 여러 번 호출해 비교
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

NAME = 'infinite'
OBJECTIVE = '전력 원단위(총전력 ÷ 생산량) 최소 — 수량별로 호출해 비교'


class PoItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qty: Optional[int] = Field(None, ge=0, description='생산 수량')
    due_day: Optional[int] = Field(None, ge=1, description='납기일 (일)')


class Request(BaseModel):
    """한 번의 실행 = 한 생산 수량. AAS 의 PurchaseOrder 에 반영된다."""
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['infinite'] = 'infinite'
    po: Optional[Dict[str, PoItem]] = Field(None, description='이번에 생산할 수량')
    overrides: Optional[dict] = None


def run(model: engine.TrainedModel, request: dict, seed: int):
    env_overrides = model.prepare(request)
    env, summary = model.simulate(seed, env_overrides)

    candidate = engine.make_candidate(env, summary, 0, {'order_quantity': model.purchase_order()})
    candidate['flags']['is_optimum'] = True
    metric = candidate['metric']
    total_qty = metric['total_qty']
    power = metric['power_kwh']['total']
    metric['energy_per_unit'] = power / max(1, total_qty)   # 전력 원단위

    result = {'scenario': NAME, 'seed': seed, 'objective': OBJECTIVE,
              'candidates': [candidate]}
    line = (f"[infinite] 생산량={total_qty} 총전력={power:.0f}kWh "
            f"전력원단위={metric['energy_per_unit']:.3f}kWh/개 완주={metric['target_met']}")
    return result, line


if __name__ == '__main__':
    engine.cli(sys.modules[__name__])
