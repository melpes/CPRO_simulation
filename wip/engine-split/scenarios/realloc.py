# -*- coding: utf-8 -*-
# 시나리오 ②-1 유휴 작업자 재배치 — 시나리오 ②와 동일 세팅 + 재배치.
#   입력  : 이동안 1개 (소스 라인 · 타겟별 이동 인원 · 유휴 발동 임계)
#           → AAS SimulationModel > KnowledgeGraph > Action > WorkerReallocation 에 반영
#   최적해: ⑴ 납기 대비 개선율  ⑵ 재배치 개선율(고정배치 총생산시간 대비)
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

NAME = 'realloc'
OBJECTIVE = '⑴ 입력 납기 대비 개선율 + ⑵ 재배치 개선율(고정배치 총생산시간 대비)'

MONITOR_TICK_SEC = 30.0


class PoItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qty: Optional[int] = Field(None, ge=0, description='주문 수량')
    due_day: Optional[int] = Field(None, ge=1, description='납기일 (일)')


class ReallocSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    src: str = Field(engine.SEMI_WORKSTATION, description='유휴 작업자를 차출할 소스 라인')
    moves: Dict[str, int] = Field(..., min_length=1, description='{타겟 라인: 이동 인원}')
    idle_trigger_sec: Optional[float] = Field(None, ge=0, description='연속 유휴 발동 임계 (초)')


class Request(BaseModel):
    """한 번의 실행 = 한 이동안. AAS 의 WorkerReallocation 에 반영된다.
    타겟은 AAS ReallocationScope 가 허용한 라인만 가능."""
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['realloc'] = 'realloc'
    po: Optional[Dict[str, PoItem]] = Field(None, description='모델별 주문수량·납기')
    realloc: ReallocSpec
    overrides: Optional[dict] = None


def _realloc_env_wrap(plan: dict):
    """소스 라인이 임계시간 연속 완전유휴이면 이동안을 1회 적용한다."""
    source    = plan['src']
    moves     = dict(plan['moves'])
    threshold = float(plan['idle_trigger_sec'])

    def wrap(base_cls):
        class _ReallocEnv(base_cls):
            def reset(self):
                super().reset()
                self.realloc_fired_sec = None
                self._realloc_done     = False
                self._realloc_src_jobs = 0
                self.env.process(self._realloc_monitor())

            def _run_job(self, ws, job, req):
                yield from super()._run_job(ws, job, req)
                if ws == source:
                    self._realloc_src_jobs += 1

            def _realloc_monitor(self):
                idle_accumulated = 0.0
                while not self._realloc_done:
                    yield self.env.timeout(MONITOR_TICK_SEC)
                    if not self._is_work_time():
                        continue
                    fully_idle = (self._realloc_src_jobs > 0
                                  and self.in_progress.get(source, 0) == 0
                                  and not self._pending[source])
                    idle_accumulated = (idle_accumulated + MONITOR_TICK_SEC) if fully_idle else 0.0
                    if idle_accumulated >= threshold:
                        self._apply_realloc()

            def _apply_realloc(self):
                now = self.env.now
                for ws in [source, *moves]:
                    self._flush_idle(ws, now)
                for ws, count in moves.items():
                    self.workers[ws]['worker_count'] += count
                    resource = self.worker_resources[ws]
                    resource._capacity += count * self.workers[ws].get('UnitsPerWorker', 1)
                    resource._trigger_put(None)
                    self._wake_dispatcher(ws)
                moved = sum(moves.values())
                self.workers[source]['worker_count'] -= moved
                self.worker_resources[source]._capacity -= (
                    moved * self.workers[source].get('UnitsPerWorker', 1))
                self._realloc_done     = True
                self.realloc_fired_sec = now

        return _ReallocEnv

    return wrap


def run(model: engine.TrainedModel, request: dict, seed: int):
    env_overrides = model.prepare(request)
    spec = request['realloc']
    source = spec.get('src') or engine.SEMI_WORKSTATION
    model.apply_realloc(source=source, moves=spec['moves'],
                        idle_trigger_sec=spec.get('idle_trigger_sec'))
    plan = model.realloc_plan(source)                          # AAS 에서 되읽음
    order_quantity = model.purchase_order()

    # 고정배치 기준선 — 재배치 개선율의 분모
    fixed_env, fixed_summary = model.simulate(seed, env_overrides)
    fixed = engine.make_candidate(fixed_env, fixed_summary, 0,
                                  {'variant': 'fixed', 'order_quantity': order_quantity})
    fixed['history']['realloc'] = []

    # 재배치 적용
    realloc_env, realloc_summary = model.simulate(
        seed, env_overrides, env_wrap=_realloc_env_wrap(plan))
    applied = engine.make_candidate(realloc_env, realloc_summary, 1,
                                    {'variant': 'realloc', 'realloc': plan,
                                     'order_quantity': order_quantity})
    applied['flags']['is_optimum'] = True

    fired = getattr(realloc_env, 'realloc_fired_sec', None)
    applied['history']['realloc'] = ([{
        'fired_sec'    : fired,
        'src'          : plan['src'],
        'moves'        : plan['moves'],
        'workers_final': {ws: info['worker_count'] for ws, info in realloc_env.workers.items()},
    }] if fired is not None else [])

    fixed_makespan   = fixed['metric']['makespan_sec']
    realloc_makespan = applied['metric']['makespan_sec']
    improvement = ((fixed_makespan - realloc_makespan) / fixed_makespan) if fixed_makespan else None
    applied['metric']['realloc_improvement'] = improvement

    result = {'scenario': NAME, 'seed': seed, 'objective': OBJECTIVE,
              'candidates': [fixed, applied]}
    line = (f"[realloc] 납기개선={engine.percent(applied['metric']['due_improvement']['overall'])} "
            f"재배치개선={engine.percent(improvement)} 발동={fired}")
    return result, line


if __name__ == '__main__':
    engine.cli(sys.modules[__name__])
