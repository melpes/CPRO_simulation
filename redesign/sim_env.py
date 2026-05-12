# -*- coding: utf-8 -*-
"""SimPy 기반 시뮬레이션 환경.

설계 원칙
---------

1. **한 (model_id, process_code) 노드에 시뮬 중 여러 unit 이 동시에 ready
   상태가 될 수 있다.** ``ready_units[(m, pc)]`` 가 deque (FIFO) 로
   ready unit_id 들을 보유. agent 가 (m, pc) action 을 선택하면 그 deque
   의 head unit 을 dispatch.

2. **모든 동적 feat 갱신과 모든 event hook 은 ``Dispatcher`` 한 곳에 집중**:

   - 동적 feat 갱신 (is_ready, worker_util, bom_satisfied, time_since_eligible)
   - 동시 idle 라인의 sequential act 순서 (line_id 사전순)
   - trigger skip (ready 없으면 act 호출 안 함)

   event hook (process 종료, BOM 입고) 은 모두 ``Dispatcher.tick()`` 한 곳을
   호출. dispatcher 외부에 동적 갱신 / agent 호출 로직 둘 다 흩어지지 않음.

3. AAS 데이터는 ``Factory`` 객체로만 접근. JSON / dict 직접 X.

경로 패턴(참고)::

    cycle_time = factory.models[m].cycle_time_of[pc]                     # SIM 추출
    bom_items  = factory.models[m].MP.groups[g].processes[pc].InputBOM   # dict
    worker_grp = factory.worker_of(m, pc)
    rated_kw   = factory.rated_kw_of(m, pc)
"""
from __future__ import annotations

from collections import defaultdict, deque  # defaultdict: WIPTracker/IdleTracker 만 사용
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import simpy

import cpro_config as C
from factory import Factory
from kg import KnowledgeGraph, NodeKey


# ── 보조 컴포넌트 ─────────────────────────────────────────────────────────


class Warehouse:
    """재고 dict + 재고 부족 violations 누적.

    stock 은 명시적 dict — 호출자가 ``initial_stock`` 으로 universe 와 초기값을
    함께 정한다. 모르는 item_code 로 consume/restore 시 KeyError (조용한
    universe 확장 금지).
    """

    def __init__(self,
                 factory: Factory,
                 initial_stock: Dict[str, int],
                 on_restore: Optional[Callable[[], None]] = None):
        self.factory = factory
        self.stock: Dict[str, int] = dict(initial_stock)
        self.violations_count = 0
        self._on_restore = on_restore

    def consume(self, item_code: str, qty: int) -> bool:
        if self.stock[item_code] < qty:
            self.violations_count += 1
            return False
        self.stock[item_code] -= qty
        if self.stock[item_code] < C.CRITICAL_STOCK:
            self.violations_count += 1
        return True

    def restore(self, item_code: str, qty: int) -> None:
        self.stock[item_code] += qty
        if self._on_restore is not None:
            self._on_restore()


class Replenisher:
    """주기적으로 stock < MinStock 인 항목을 MaxStock 까지 채워 발주.

    SimPy process. ``ManufacturingEnv.reset()`` 가 ``simpy_env.process(run())`` 으로
    spawn. lead_time 마다 한 번 검사 → 부족분만 restore (warehouse.on_restore →
    dispatcher.tick() 까지 연결됨).
    """

    def __init__(self,
                 env: 'ManufacturingEnv',
                 warehouse: Warehouse,
                 min_stock: Dict[str, int],
                 max_stock: Dict[str, int],
                 lead_time_sec: float):
        self.env_obj = env
        self.warehouse = warehouse
        self.min_stock = min_stock
        self.max_stock = max_stock
        self.lead_time = lead_time_sec

    def run(self):
        env = self.env_obj.simpy_env
        while True:
            yield env.timeout(self.lead_time)
            for item, threshold in self.min_stock.items():
                if self.warehouse.stock[item] < threshold:
                    refill = self.max_stock[item] - self.warehouse.stock[item]
                    if refill > 0:
                        self.warehouse.restore(item, refill)


class WIPTracker:
    """재공품 한도 초과 violations 누적."""

    def __init__(self):
        self.count: Dict[str, int] = defaultdict(int)
        self.violations_count = 0

    def enter(self, worker_group: str) -> None:
        self.count[worker_group] += 1
        if self.count[worker_group] > C.WIP_LIMIT_PER_GROUP:
            self.violations_count += 1

    def leave(self, worker_group: str) -> None:
        if self.count[worker_group] > 0:
            self.count[worker_group] -= 1


class IdleTracker:
    """워커 idle 시간 누적 — 워커 단위로 계산.

    한 그룹에 워커 N 명이 있고 X 명이 idle 이면 dt 동안 X·dt 만큼 누적.
    """

    def __init__(self, worker_capacity: Dict[str, int]):
        self.capacity = dict(worker_capacity)
        self.active: Dict[str, int] = defaultdict(int)   # busy 워커 수
        self.idle_seconds = 0.0
        self._last_t: float = 0.0

    def flush(self, now: float) -> None:
        dt = now - self._last_t
        if dt <= 0:
            self._last_t = now
            return
        for grp, cap in self.capacity.items():
            idle_workers = cap - self.active[grp]
            self.idle_seconds += idle_workers * dt
        self._last_t = now

    def acquire(self, now: float, worker_group: str) -> None:
        self.flush(now)
        self.active[worker_group] += 1

    def release(self, now: float, worker_group: str) -> None:
        self.flush(now)
        if self.active[worker_group] > 0:
            self.active[worker_group] -= 1


class EnergyLogger:
    """총 kWh 누적."""

    def __init__(self):
        self.total_kwh = 0.0

    def record(self, rated_kw: float, cycle_time_sec: float) -> None:
        self.total_kwh += rated_kw * cycle_time_sec / 3600.0


# ── unit dispatch 상태 ────────────────────────────────────────────────────


@dataclass
class UnitState:
    """unit 1개의 KG 진행 상태.

    한 (m, pc) 가 ready 가 되려면:
      - 그 unit 의 모든 선행 pc 가 done
      - JOIN 이면 all, non-JOIN 이면 any
      - BOM 충족은 dispatcher 가 별도로 확인
    """
    model_id: str
    unit_id: int
    done: set = field(default_factory=set)
    in_progress: set = field(default_factory=set)


# ── Dispatcher: 동적 feat 갱신 + event hook + agent act 의 단일 집중점 ───


class Dispatcher:
    """모든 event hook 과 동적 feat 갱신 / agent.act 호출이 모이는 한 곳.

    호출 경로::

        SimPy event (process 종료 / BOM 입고) → ManufacturingEnv 의 hook
                                            → Dispatcher.tick(env)
    """

    def __init__(self,
                 env: 'ManufacturingEnv',
                 kg: KnowledgeGraph,
                 factory: Factory):
        self.env_obj = env
        self.kg = kg
        self.factory = factory

    # ── 외부에서 부르는 단일 진입점 ─────────────────────────────────

    def tick(self) -> None:
        """이벤트 발생 시 호출되는 단일 진입점.

        흐름:
          1. 동적 feat 갱신 (한 곳)
          2. 각 라인을 line_id 사전순으로 순회 (sequential)
          3. 라인 별 ready_mask 가 비면 skip
          4. agent 가 있으면 act → dispatch, 없으면 deterministic dispatch
        """
        if not self.env_obj.simpy_env:
            return

        self._refresh_dynamic_feat()

        # line_id 사전순 sequential
        for line_id in sorted(self.factory.line_to_idx.keys()):
            self._try_dispatch_line(line_id)

    # ── (1) 동적 feat 갱신 — KG.refresh_dynamic 호출이 여기에만 존재 ──

    def _refresh_dynamic_feat(self) -> None:
        env = self.env_obj

        ready_units_count: Dict[NodeKey, int] = {
            key: len(units) for key, units in env.ready_units.items()
        }
        worker_util_by_group: Dict[str, float] = {
            grp: (res.count / max(res.capacity, 1))
            for grp, res in env.worker_resources.items()
        }
        bom_satisfied_of: Dict[NodeKey, bool] = {
            key: env.bom_satisfied(*key) for key in self.kg.node_keys
        }

        self.kg.refresh_dynamic(
            sim_now=float(env.simpy_env.now),
            ready_units_count=ready_units_count,
            worker_util_by_group=worker_util_by_group,
            bom_satisfied_of=bom_satisfied_of,
        )

    # ── (2) 라인 1개 dispatch ────────────────────────────────────────

    def _try_dispatch_line(self, line_id: str) -> None:
        env = self.env_obj

        # 워커 자원 확보 가능 여부 (라인의 워커 그룹이 가용?)
        worker_group = self.factory.line_to_worker.get(line_id, '')
        wres = env.worker_resources.get(worker_group)
        if wres is None or wres.count >= wres.capacity:
            return   # 라인 자체는 비었어도 워커 풀이 가득이면 dispatch 불가

        line_idx = self.factory.line_to_idx[line_id]

        # 후보 마스크 = ready_mask AND line_filter_mask AND bom_satisfied
        ready  = self.kg.ready_mask()
        on_ln  = self.kg.line_filter_mask(line_idx)
        bom_ok = np.asarray([self.kg.nodes[k].bom_satisfied
                             for k in self.kg.node_keys], dtype=bool)
        mask = ready & on_ln & bom_ok

        if not mask.any():
            return   # trigger skip

        # action 결정: agent 가 있으면 GNN+PPO, 없으면 첫 번째 후보
        chosen_idx = env.choose_action(mask, caller_line_id=line_id)
        if chosen_idx is None:
            return
        chosen_key: NodeKey = self.kg.node_keys[chosen_idx]

        # (m, pc) 의 FIFO queue 에서 unit 1개 pop
        unit_id = env.ready_units[chosen_key].popleft()
        env.start_process(chosen_key, unit_id)


# ── 시뮬 본체 ────────────────────────────────────────────────────────────


class ManufacturingEnv:
    """SimPy 기반 공장 시뮬.

    한 노드 (m, pc) 에 시뮬 중 여러 unit 이 동시에 ready 가능 → ``ready_units``
    가 (m, pc) 별 FIFO queue. agent 가 (m, pc) action 만 결정하면 unit 은
    가장 오래 ready 한 것을 dispatch.

    동적 feat 갱신과 모든 event hook 은 ``Dispatcher.tick()`` 한 곳에 집중.
    이 클래스의 ``_on_process_end`` / ``_on_bom_restore`` 는 dispatcher.tick()
    을 호출하는 얇은 wrapper.
    """

    def __init__(self,
                 factory: Factory,
                 kg: KnowledgeGraph,
                 agent=None):
        self.factory = factory
        self.kg = kg
        self.agent = agent

        self.simpy_env: Optional[simpy.Environment] = None
        self.worker_resources: Dict[str, simpy.Resource] = {}

        # (m, pc) -> deque(unit_id), 한 노드의 ready unit FIFO
        self.ready_units: Dict[NodeKey, deque] = defaultdict(deque)
        # unit_id 별 진행 상태
        self.units: Dict[Tuple[str, int], UnitState] = {}

        # 보조 컴포넌트
        self.warehouse: Optional[Warehouse] = None
        self.wip: Optional[WIPTracker] = None
        self.idle: Optional[IdleTracker] = None
        self.energy: Optional[EnergyLogger] = None

        # dispatcher — 단일 진입점
        self.dispatcher: Optional[Dispatcher] = None

        # 보상 prev 값 (delta 계산용)
        self._prev = {'stock': 0, 'wip': 0, 'done': 0, 'idle': 0.0}

    # ── 시뮬 초기화 ──────────────────────────────────────────────────

    def reset(self) -> None:
        self.simpy_env = simpy.Environment()
        self.worker_resources = {
            grp: simpy.Resource(self.simpy_env, capacity=cap)
            for grp, cap in self.factory.worker_capacity.items()
        }
        self.ready_units = defaultdict(deque)
        self.units = {}

        self.warehouse = Warehouse(
            self.factory,
            initial_stock = dict(self.factory.bom_min_stock),
            on_restore    = self._on_bom_restore,
        )
        self.wip       = WIPTracker()
        self.idle      = IdleTracker(self.factory.worker_capacity)
        self.energy    = EnergyLogger()

        self.dispatcher  = Dispatcher(self, self.kg, self.factory)
        self.replenisher = Replenisher(
            env           = self,
            warehouse     = self.warehouse,
            min_stock     = self.factory.bom_min_stock,
            max_stock     = self.factory.bom_max_stock,
            lead_time_sec = C.REPLENISH_LEAD_TIME_SEC,
        )
        self.simpy_env.process(self.replenisher.run())

        # 모든 unit 생성 + KG 의 source 노드 (선행 없음) 즉시 ready 큐 등록
        for model_id, qty in self.factory.order.items():
            for unit_id in range(qty):
                self.units[(model_id, unit_id)] = UnitState(model_id, unit_id)
                for pc in self.factory.models[model_id].process_codes():
                    if not self.factory.models[model_id].dep_prev_of[pc]:
                        self.ready_units[(model_id, pc)].append(unit_id)

        self._prev = {'stock': 0, 'wip': 0, 'done': 0, 'idle': 0.0}

    # ── BOM 충족 판단 (KG 가 동적 갱신 시 사용) ────────────────────

    def bom_satisfied(self, model_id: str, process_code: str) -> bool:
        """그 노드의 InputBOM 부품들이 현재 재고로 모두 충족 가능?"""
        group_name = self.factory.models[model_id].process_group_of[process_code]
        bom: Dict[str, float] = self.factory.models[model_id].MP.groups[group_name].processes[process_code].InputBOM
        for item_code, qty in bom.items():
            if self.warehouse.stock[item_code] < qty:
                return False
        return True

    # ── action 선택 (agent 또는 deterministic) ───────────────────────

    def choose_action(self, mask: np.ndarray, caller_line_id: str) -> Optional[int]:
        """mask 에서 가용한 노드 중 1개 idx 선택.

        agent 가 있으면 GNN+PPO 의 ``act()`` 호출, 없으면 mask 의 첫 True 위치.
        """
        if not mask.any():
            return None
        if self.agent is None:
            return int(np.argmax(mask))   # mask True 의 첫 위치
        return self.agent.act(self, mask, caller_line_id)

    # ── process 실행 (SimPy process) ─────────────────────────────────

    def start_process(self, node_key: NodeKey, unit_id: int) -> None:
        self.simpy_env.process(self._run_process(node_key, unit_id))

    def _run_process(self, node_key: NodeKey, unit_id: int):
        model_id, process_code = node_key
        factory = self.factory
        node = self.kg.nodes[node_key]
        worker_group = factory.worker_of(model_id, process_code)
        group_name = factory.models[model_id].process_group_of[process_code]
        process_node = factory.models[model_id].MP.groups[group_name].processes[process_code]

        # BOM 소비
        for item_code, qty in process_node.InputBOM.items():
            self.warehouse.consume(item_code, int(qty))

        # 워커 자원 점유
        wres = self.worker_resources[worker_group]
        req = wres.request()
        yield req
        self.idle.acquire(float(self.simpy_env.now), worker_group)
        self.wip.enter(worker_group)

        # 작업 진행
        cycle_time_sec = node.cycle_time_sec
        yield self.simpy_env.timeout(cycle_time_sec)

        # 에너지 + 자원 해제
        self.energy.record(node.rated_kw, cycle_time_sec)
        self.wip.leave(worker_group)
        self.idle.release(float(self.simpy_env.now), worker_group)
        wres.release(req)

        # unit 상태 갱신
        unit_state = self.units[(model_id, unit_id)]
        unit_state.done.add(process_code)

        # 후행 pc 중 이 unit 이 ready 가 되는 것들을 queue 에 추가
        self._enqueue_newly_ready(model_id, unit_id, process_code)

        # event hook → dispatcher
        self._on_process_end()

    def _enqueue_newly_ready(self, model_id: str, unit_id: int, done_pc: str) -> None:
        """방금 끝난 pc 의 후행 중, 이 unit 이 새로 ready 가 되는 (m, pc) 를
        ready_units queue 에 추가.
        """
        aas = self.factory.models[model_id]
        unit_state = self.units[(model_id, unit_id)]
        for pc, prevs in aas.dep_prev_of.items():
            if done_pc not in prevs:
                continue
            if pc in unit_state.done or pc in unit_state.in_progress:
                continue
            # JOIN: 모든 prev done. non-JOIN: 1개라도 done.
            if aas.is_join[pc]:
                if not all(p in unit_state.done for p in prevs):
                    continue
            self.ready_units[(model_id, pc)].append(unit_id)

    # ── event hook (얇은 wrapper, 동적 갱신 코드 X — dispatcher 가 담당) ──

    def _on_process_end(self) -> None:
        self.dispatcher.tick()

    def _on_bom_restore(self) -> None:
        self.dispatcher.tick()

    # ── 보상 계산 (한 곳) ────────────────────────────────────────────

    def reward(self, done: bool) -> float:
        """dense 4 + terminal 3 의 가중합. delta 기반.

        식은 cpro_config.py 의 REWARD_W_* 와 정규화 분모 (factory.T_REF 등)
        한 곳에서만 참조.
        """
        factory = self.factory
        self.idle.flush(float(self.simpy_env.now))

        # 현재 누적값
        stock_now = self.warehouse.violations_count
        wip_now   = self.wip.violations_count
        idle_now  = self.idle.idle_seconds
        done_now  = sum(1 for s in self.units.values()
                        if len(s.done) == len(factory.models[s.model_id].process_codes()))

        # delta
        d_stock = stock_now - self._prev['stock']
        d_wip   = wip_now   - self._prev['wip']
        d_done  = done_now  - self._prev['done']
        d_idle  = idle_now  - self._prev['idle']
        self._prev = {'stock': stock_now, 'wip': wip_now,
                      'done': done_now, 'idle': idle_now}

        total_order = max(factory.total_order, 1)
        idle_denom  = max(factory.total_worker_capacity * factory.T_REF, 1.0)

        r_stock_short = -d_stock / total_order
        r_stock_over  = -d_wip   / total_order
        r_done        =  d_done  / total_order
        r_idle        = -d_idle  / idle_denom

        r = (C.REWARD_W_STOCK_SHORT * r_stock_short
             + C.REWARD_W_STOCK_OVER  * r_stock_over
             + C.REWARD_W_DONE        * r_done
             + C.REWARD_W_IDLE        * r_idle)

        # terminal
        if done:
            makespan = float(self.simpy_env.now)
            r_make    = -makespan / max(factory.T_REF, 1.0)
            r_energy  = -self.energy.total_kwh / max(factory.E_REF, 1.0)
            r_success = 1.0 if done_now >= total_order else 0.0
            r += (C.REWARD_W_MAKESPAN * r_make
                  + C.REWARD_W_KWH     * r_energy
                  + C.REWARD_W_SUCCESS * r_success)
        return r

    # ── 실행 entry ───────────────────────────────────────────────────

    def run(self, until_sec: Optional[float] = None) -> None:
        if self.simpy_env is None:
            self.reset()
        # 초기 ready unit 들로 dispatcher 한 번 trigger
        self.dispatcher.tick()
        self.simpy_env.run(until=until_sec)
