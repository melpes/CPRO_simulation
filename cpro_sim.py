# -*- coding: utf-8 -*-
"""ver1 simpy 이산사건 시뮬레이션 환경 (③ 분할). CproSimEnv + train."""
from __future__ import annotations

import random
import simpy
import torch

from cpro_domain import Warehouse, _StockRouter


# ============================================================
# 1 epoch = 3일 (259200s). 학습 horizon 기본값.
# 1일(86400)로는 BT5_42 24h 본드(DepWaitSec)가 에피소드 전체를 먹어 MODEL_B 완성 불가 +
# A/C 가 capacity-bound → 스케줄링 학습 leverage 거의 0 (2026-06-01 60ep 실측: 전 지표 flat).
# 3일이면 B 의 24h 본드가 들어가 B 생산 가능 + throughput 이 정책 민감 → 학습 leverage 확보.
# qty 고정(100)에선 horizon 을 늘려도 보상항 비율 보존(throughput·energy·위반카운터 모두 시간 비례).
# 평가는 전량완료 기준(CproSimEnv.run(max_sec=큰 cap) 으로 target 도달까지).
EPISODE_DURATION_SEC = 3 * 86400
# ============================================================

#========시뮬레이션 환경========-
class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold, RuntimeVariables,
                 IdleProcessRatedPowerKw, IdlePowerRatio=0.10, SelfManagedBOM=None,
                 SMTLines=None, SmtArrayPcb=6, SmtBatchArrays=40):
        self.KnowledgeGraph       = KnowledgeGraph
        self.warehouse            = warehouse
        self.workers              = workers
        self.IndependentSequence  = IndependentSequence
        self.DependentSequence    = DependentSequence
        self.DependentJoin        = DependentJoin
        self.RewardWeights        = RewardWeights
        self.ReplenishLeadDay     = ReplenishLeadDay
        self.target_qty           = target_qty
        self.MaxEpisodes          = MaxEpisodes
        self.WarehouseManagedBOM  = WarehouseManagedBOM   # CoManaged (PCB 제외)
        self.SelfManagedBOM       = SelfManagedBOM         # PCB 등 — 별도 창고. None 이면 PCB 분리 안 함
        self.BOMCategory          = BOMCategory
        self.WorkStartTime        = WorkStartTime
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec  # int(min.split(':')[0]) * 3600 + int(min.split(':')[1]) * 60
        self.break_end_sec        = break_end_sec    # int(max.split(':')[0]) * 3600 + int(max.split(':')[1]) * 60
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.IdleProcessRatedPowerKw = IdleProcessRatedPowerKw  #← DefaultParameters.IdleProcessRatedPowerKw
        self.IdlePowerRatio       = IdlePowerRatio    # AAS 미반영 정책상수(=0.10) — 호출부 주입
        self.RuntimeVariables     = RuntimeVariables  #← path_extractor RuntimeVariables (AAS 명시 연산)
        self.SMTLines             = SMTLines          # {line_id: [(idShort, CycleTimeSec, RatedPowerKw)...]} ← SMTProcess. None=구 stub
        self.SmtArrayPcb          = SmtArrayPcb        # 1 어레이 = N PCB (§7-4 어레이=6 PCB) — 정책상수 주입
        self.SmtBatchArrays       = SmtBatchArrays     # 1 배치 = N 어레이 (§7-3-A 매거진=40 어레이) — 정책상수 주입

    def reset(self):
        self.env                  = simpy.Environment()
        #========RuntimeVariables (← SimulationModel.RuntimeVariables)========
        # AAS 에 value=None 으로 정의만 있는 동적 상태. 연산은 self.RuntimeVariables
        # (path_extractor) 가 단일 구현. 여기선 에피소드 초기값만 둔다.
        self.CycleCompleted       = False   #← .CycleCompleted
        self.Throughput           = {model_id: 0 for model_id in self.target_qty}  #← .Throughput (모델별)
        self.EpisodeEnergyKwh     = 0.0     #← .EpisodeEnergyKwh
        self.SMTEnergyKwh         = 0.0     # SMT 라인 활성에너지 — 별도 누적(보상 비결합). total_energy_kwh 에만 합산
        self.StockShortageCount   = 0       #← .StockShortageCount
        self.StockOverflowCount   = 0       #← .StockOverflowCount
        self.IdleViolationCount   = 0       #← .IdleViolationCount
        #----generic 헬퍼 (AAS 외 — 순수 코드용)----
        self.completed            = set()
        self.in_progress          = {}
        self.idle_time            = {}
        self.last_active          = {ws: 0.0 for ws in self.workers}   # ws 가 fully idle 진입한 시각 (state_vec idle 항 산출용)
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        if self.SelfManagedBOM:                          # PCB(SelfManaged) 별도 창고
            self._pcb_warehouse   = Warehouse.build(self.SelfManagedBOM, self.BOMCategory)
            self.warehouse        = _StockRouter(self.warehouse, self._pcb_warehouse)
            pcb_codes = [code for items in self._pcb_warehouse.inventory.values() for code in items]
            if self.SMTLines:                            # AAS SMTProcess 설비 라인 — 실제 SMT 생산(GoodPCB → pcb 창고)
                n_lines = len(self.SMTLines)
                for line_index, (line_id, equipment) in enumerate(self.SMTLines.items()):
                    line_codes = pcb_codes[line_index::n_lines]   # PCB 코드 라인 분배(2라인 = 두개씩 라운드로빈)
                    self.env.process(self.smt_line(line_id, equipment, line_codes))
            else:                                        # SMTLines 미주입 → 구 stub 일정증가(fallback)
                import cpro_smt
                self.env.process(cpro_smt.pcb_supply(self.env, self._pcb_warehouse))
        self.worker_resources     = {                       # 라인별 동시 작업 한도 = 워커수 × 1워커당 동시 처리수
            WorkstationId: simpy.Resource(self.env,          # AGING 은 UnitsPerWorker=10 → 6×10=60 동시. 그 외 라인은 ×1.
                                          capacity=info['worker_count'] * info['UnitsPerWorker'])
            for WorkstationId, info in self.workers.items()
        }
        # [B2 중앙 디스패처] ws별 대기 job 큐 + 깨우기 이벤트. 워커 빌 때 디스패처가
        # 큐에서 다음 job 선택 — 후보 ≥2 면 agent.choose(cross-unit/model), 아니면 FIFO.
        self._pending   = {ws: [] for ws in self.workers}
        self._disp_wake = {ws: self.env.event() for ws in self.workers}
        # 재고 입고 broadcast 이벤트 — BOM 대기로 잠든 produce_unit 들을 한 번에 깨움(Track F).
        # replenish(notify=self._wake_stock) 가 입고 직후 트리거. 폴링(timeout 60s) 대체.
        self._stock_wake = self.env.event()
        # 위반 카운터(W3/W4/W6) 정규화 상수 — 1일 근무틱(30s 샘플) × 대상 수 = 매 틱 전부 위반 시 최대치.
        # 고정값이라 potential() telescoping 안전(시간가변 분모 X). 1일 학습 스케일 기준 → 항 ~[0,1].
        work_day_sec              = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        nominal_work_ticks        = work_day_sec / 30.0                          # _watch 샘플 주기 30s
        self._stock_violation_norm = max(1.0, sum(len(items) for items in self.warehouse.inventory.values())
                                               * nominal_work_ticks)
        self._idle_violation_norm  = max(1.0, sum(info['worker_count'] for info in self.workers.values())
                                               * nominal_work_ticks)
        # W2_Energy 정규화 분모 = 전 unit 완성 시 active 프리미엄 (target_qty·KG 만 의존 → 에피소드 내 고정).
        self._max_episode_premium = self.RuntimeVariables.MaxEpisodeEnergyKwh(
            self.KnowledgeGraph, self.target_qty,
            self.IdleProcessRatedPowerKw, self.IdlePowerRatio)
    
    def _is_work_time(self) -> bool:                    # ver0 원본 그대로 (무변경)
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def _off_hours_delta(self) -> float:
        # 다음 근무 재개까지 남은 초 — process_job / _dispatcher 비근무 점프 공통.
        sid = self.env.now % 86400
        if sid < self.WorkStartTime:
            return self.WorkStartTime - sid
        if self.break_start_sec <= sid < self.break_end_sec:
            return self.break_end_sec - sid
        return 86400 - sid + self.WorkStartTime

    def process_job(self, ProcessCode, WorkstationId, done_set):
        # ver0 process_job 원본 본문 유지. 최소 수정만:
        #   (1) 파라미터 done_set 추가  (2) 근무시간 대기  (3) 워커 Resource 점유
        #   (4) self.completed → done_set, 전역 clear() 제거
        self.in_progress[WorkstationId] = self.in_progress.get(WorkstationId, 0) + 1
        node = self.KnowledgeGraph.nodes[ProcessCode]
        while not self._is_work_time():                              # (2) 비근무면 재개까지 정확 점프
            yield self.env.timeout(self._off_hours_delta())
        with self.worker_resources[WorkstationId].request() as req:  # (3) 워커 capacity
            yield req
            yield self.env.timeout(node.CycleTimeSec)
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh, self.IdleProcessRatedPowerKw, self.IdlePowerRatio)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM)
            if ordered:
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered))
        if node.OutputBOM:                                           # A안: 완료 시 산출물 창고 적재
            self.warehouse.produce(node.OutputBOM)
        done_set.add(ProcessCode)                                    # (4) self.completed → done_set
        self.in_progress[WorkstationId] -= 1
        if self.in_progress[WorkstationId] == 0:                     # ws fully idle 진입 — duration 기준점
            self.last_active[WorkstationId] = self.env.now
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(ProcessCode, self.KnowledgeGraph)
        # (4) terminal 시 self.completed.clear() 제거 — 유닛-local done_set 이라 불필요/유해

    def _ready_for(self, model_id, done_set):
        # model_id 일치 OR 공용 노드(model_id='ALL', 예: OQC/RMA) 둘 다 포함.
        return [pc for pc in self.KnowledgeGraph.ready_queue(        # ver0 ready_queue 원본
                    self.IndependentSequence, self.DependentSequence,
                    self.DependentJoin, done_set, self.warehouse)    # completed ← done_set
                if self.KnowledgeGraph.nodes[pc].model_id in (model_id, 'ALL')]

    def _workstation_of(self, ProcessCode):
        return next((ws for ws in self.workers
                     if ProcessCode in self.workers[ws]['ProcessCode']), None)

    # ============================================================
    # [B2 중앙 디스패처 재설계]  per-unit 단일선택 폐기 → 전 유닛이 ready job 을
    # ws별 큐에 제출(fan-out 병렬 유지). 워커 슬롯이 빌 때 디스패처가 그 ws 큐에서
    # 다음 job 선택: 후보 ≥2 면 agent.choose(=cross-unit/model 우선순위, PPO 결정점),
    # 후보 1개거나 agent=None 이면 FIFO(=기존 greedy/simpy 의미 보존).
    # choose()/learn() 는 불변 — candidate 출처만 'cross-unit pending' 로 바뀜.
    # ============================================================
    def _wake_dispatcher(self, ws):
        ev = self._disp_wake[ws]
        if not ev.triggered:
            ev.succeed()

    def _wake_stock(self):
        # 재고 입고 시 호출(replenish notify). 현재 _stock_wake 를 succeed → BOM 대기 unit 전부 깨움.
        # 즉시 새 이벤트로 교체해 다음 대기자가 fresh 이벤트를 받게 함(broadcast-recreate).
        # simpy 협조적 스케줄 → unit 의 'ready 확인 후 yield' 사이 끼어듦 없어 lost-wakeup 無.
        ev = self._stock_wake
        self._stock_wake = self.env.event()
        if not ev.triggered:
            ev.succeed()

    def _dispatcher(self, ws, agent):
        res = self.worker_resources[ws]
        while True:
            if not self._pending[ws]:                       # 큐 빌 때 잠듦(simpy 협조적 → lost-wakeup 無)
                self._disp_wake[ws] = self.env.event()
                yield self._disp_wake[ws]
                continue
            if not self._is_work_time():                    # 근무시간 게이트(시작 시점만 — ver0 의미)
                yield self.env.timeout(self._off_hours_delta())
                continue
            req = res.request()                             # 워커 슬롯 대기(빌 때까지)
            yield req
            pend = self._pending[ws]
            if not pend:                                    # 단일 디스패처라 보통 발생X — 안전망
                res.release(req)
                continue
            distinct_pcs = list(dict.fromkeys(j['pc'] for j in pend))   # 순서보존 distinct (동일 공정 중복 unit job 압축)
            if agent is not None and len(distinct_pcs) >= 2:            # ★contention 결정점★ (PPO) — 공정 타입 ≥2 경합 시만
                chosen_pc = agent.choose(distinct_pcs, self)            #   choose 후보 = distinct 공정 (큐 깊이 무관, buf·연산 폭증 방지)
                job = next(j for j in pend if j['pc'] == chosen_pc)     #   고른 공정의 첫 job (같은 공정 unit 은 교환가능)
            else:
                job = pend[0]                                           # FIFO (greedy / 단일 공정 / 후보1개)
            pend.remove(job)
            self.env.process(self._run_job(ws, job, req))

    def _run_job(self, ws, job, req):
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        self.in_progress[ws] = self.in_progress.get(ws, 0) + 1
        yield self.env.timeout(node.CycleTimeSec)           # 점유한 채 작업(시작 후 근무외 넘어가도 ver0 동일)
        self.worker_resources[ws].release(req)
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh, self.IdleProcessRatedPowerKw, self.IdlePowerRatio)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM)
            if ordered:
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered, self._wake_stock))   # 입고 시 BOM 대기 unit 깨움
        if node.OutputBOM:                                  # A안: 완료 시 산출물 창고 적재 (SMT PCB 등). 일반 조립노드는 None → no-op
            self.warehouse.produce(node.OutputBOM)
        self.in_progress[ws] -= 1                           # ★ 워커 즉시 자유 — DepWait 중 다른 job 가능
        if self.in_progress[ws] == 0:                       # ws fully idle 진입 — duration 기준점 갱신
            self.last_active[ws] = self.env.now
        self._wake_dispatcher(ws)                           # 슬롯 비었음 → 디스패처 재가동

        if node.DepWaitSec:                                 # ★ AAS DepWaitSec — 본드 경화·AGING 등 후처리 대기
            yield self.env.timeout(node.DepWaitSec)         #   워커 비점유. 이 코루틴만 잠듦 — env.now 는 다른 이벤트로 진행.

        job['done_set'].add(pc)                             # DepWait 완료 후 done 인정 — 후속이 비로소 ready
        job['in_flight'].discard(pc)
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(pc, self.KnowledgeGraph)
        self.Throughput = self.RuntimeVariables.Throughput(pc, self.KnowledgeGraph, self.Throughput)
        if not job['ev'].triggered:
            job['ev'].succeed()                             # produce_unit outstanding 깨움 → 새 ready job fan-out

    def produce_unit(self, model_id, agent=None):
        # 주문 1개 = 코루틴 1개. ready job 을 ws 큐에 제출(fan-out)하고 완료를 대기.
        # 선택(어느 job 먼저)은 디스패처가 cross-unit 으로 — 여기선 제출/대기만.
        done_set = set()
        kg = self.KnowledgeGraph
        terminal_pcs = {pc for pc, n in kg.nodes.items()
                        if n.model_id == model_id and pc not in kg.edges}
        in_flight: set = set()
        outstanding: list = []
        while not terminal_pcs.issubset(done_set):
            ready = self._ready_for(model_id, done_set)
            for pc in ready:
                if pc in in_flight or pc in done_set:
                    continue
                node = kg.nodes[pc]
                # ★ SamplingRate 확률적 분기: ready 됐어도 random >= rate 면 즉시 done 마킹·skip.
                #   OQC 같은 확률 게이트 노드 — 5% 만 실제 워커 소비, 95% 는 bypass.
                if node.SamplingRate is not None and random.random() >= node.SamplingRate:
                    done_set.add(pc)
                    continue
                ws = self._workstation_of(pc)
                if ws is None:
                    done_set.add(pc)
                    continue
                in_flight.add(pc)
                ev = self.env.event()
                self._pending[ws].append({'pc': pc, 'done_set': done_set,
                                          'in_flight': in_flight, 'ev': ev})
                outstanding.append(ev)
                self._wake_dispatcher(ws)
            outstanding = [e for e in outstanding if not e.triggered]
            if not outstanding:
                yield self._stock_wake                               # BOM 부족으로 제출불가 → 재고 입고 시까지 대기(Track F: 폴링 제거)
                continue                                             #   유일한 unblock 이벤트가 replenish 임을 분석으로 확인
            yield simpy.AnyOf(self.env, outstanding)                  # 하나라도 끝나면 재평가
            outstanding = [e for e in outstanding if not e.triggered]

    def smt_line(self, line_id, equipment, pcb_codes):
        # AAS SMTProcess 설비 라인 1줄(env.process 로 등록). 배정 PCB 코드를 라운드로빈으로 배치 생산.
        # equipment: [(idShort, CycleTimeSec, RatedPowerKw), ...] 라인 설비 순서(SMTEquipmentProcess → factory 주입).
        # 1 array = SmtArrayPcb(6) PCB, 라인 통과시간 = Σ설비 cycle (직렬 — §7-4 "어레이 1장 처리시간 ≈620s").
        # 1 batch = SmtBatchArrays(40) array(=240 PCB 매거진). PCB 전환 = 현 배치 전량 완료 후(라인 클리어).
        # ★ open-loop 라운드로빈 — 수요 무관이라 특정 코드 starvation 가능(측정·보고 대상). 수요기반은 후속.
        if not pcb_codes or not equipment:
            return
        array_cycle  = sum(cycle for _, cycle, _ in equipment)        # 어레이 1장 라인 통과시간(s)
        array_energy = sum(power * cycle for _, cycle, power in equipment) / 3600   # 어레이 1장 SMT 활성에너지(kWh)
        while True:
            for code in pcb_codes:                                    # 라운드로빈 PCB 전환(라인 클리어 후)
                for _ in range(self.SmtBatchArrays):                  # 1 배치
                    while not self._is_work_time():                   # 비근무면 재개까지 점프(조립과 동일 게이트)
                        yield self.env.timeout(self._off_hours_delta())
                    yield self.env.timeout(array_cycle)
                    self.SMTEnergyKwh += array_energy
                    self.warehouse.produce({code: self.SmtArrayPcb})  # GoodPCB 어레이(6) → pcb 창고
                    self._wake_stock()                                # PCB 입고 → BOM 대기 produce_unit 깨움

    def run(self, agent=None, max_sec: float = 60 * 86400):
        # 주문수량만큼 produce_unit 을 동시에 띄우고 한 번 진행. agent=None → greedy.
        self.reset()
        stop = self.env.event()
        for ws in self.workers:                              # [B2] ws별 중앙 디스패처
            self.env.process(self._dispatcher(ws, agent))
        for model_id, qty in self.target_qty.items():
            for _ in range(qty):
                self.env.process(self.produce_unit(model_id, agent))

        def _watch():
            while not stop.triggered:
                yield self.env.timeout(30)
                if self._is_work_time():                         # 근무시간 틱마다 위반 카운터 누적 (W3/W4/W6)
                    self.StockShortageCount = self.RuntimeVariables.StockShortageCount(
                        self.warehouse, self.StockShortageCount)
                    self.StockOverflowCount = self.RuntimeVariables.StockOverflowCount(
                        self.warehouse, self.StockOverflowCount)
                    self.IdleViolationCount = self.RuntimeVariables.IdleViolationCount(
                        self.workers, self.in_progress, self.idle_time, self.env.now,
                        self.IdleWorkerThreshold, self.IdleViolationCount)
                if (all(self.Throughput[m] >= self.target_qty[m] for m in self.target_qty)
                        or self.env.now >= max_sec):
                    if not stop.triggered:
                        stop.succeed()
                    return
        self.env.process(_watch())
        self.env.run(until=stop)
        return {
            'Throughput'      : dict(self.Throughput),
            'makespan_sec'    : float(self.env.now),
            'EpisodeEnergyKwh': float(self.total_energy_kwh()),     # idle+프리미엄 총량(버그수정: idle 포함)
            'ActivePremiumKwh': float(self.EpisodeEnergyKwh),       # 참고: active 초과분만(기존 값)
        }

    def total_energy_kwh(self) -> float:
        # 진짜 총 에너지 = idle baseline(now 의존, 전 공정이 now 내내 idle) + active 프리미엄.
        # 기존 버그: 보상/로그가 프리미엄(상수)만 써서 makespan 무관 → idle 누락.
        idle_base = self.RuntimeVariables.IdleBaselineKwh(
            self.KnowledgeGraph, self.env.now,
            self.IdleProcessRatedPowerKw, self.IdlePowerRatio)
        return idle_base + self.EpisodeEnergyKwh + self.SMTEnergyKwh   # SMT 라인 활성에너지 합산(보상엔 비결합)

    @property
    def state_dim(self) -> int:
        # PPOAgent 인스턴스화 시점에 미리 알아야 — env.reset() 호출 불필요(설정만으로 산출).
        # 구성: [throughput per model] + [time] + [energy]
        #     + [worker_util per ws] + [stock_short, stock_over] + [idle_avg]
        return len(self.target_qty) + 2 + len(self.workers) + 3

    def state_vec(self) -> torch.Tensor:
        # 결정점마다 호출. 활성 보상항(W1/W2/W5) + 미활성 채널(W3/W4/W6) 까지 전부 동적 관측.
        # 보상에 없어도 critic V(s) 추정에 도움 — 관측은 풀로, 보상은 별도 결정.
        # 모든 값 0~1 근방으로 정규화 — GNN 임베딩과 concat 시 한 항이 압살하지 않도록.
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        feats = []
        for model_id in self.target_qty:                                # ① 모델별 throughput 진척 (W5 대응)
            feats.append(self.Throughput[model_id] / self.target_qty[model_id])
        feats.append(self.env.now / max(work_day * total_target, 1.0))   # ② 시간 진척 (W1 대응)
        feats.append(self.EpisodeEnergyKwh / self._max_episode_premium)  # ③ 에너지 진척 (W2 대응) — active 프리미엄 / 전량 [0,1] (potential 과 동일 분모)
        for ws, info in self.workers.items():                            # ④ ws별 워커 점유율
            feats.append(self.in_progress.get(ws, 0) / info['worker_count'])
        # ⑤ 재고 항 (W3/W4 대응) — 전 품목 정규화 합 (MinStock 부족 / MaxStock 과잉)
        stock_short = 0.0
        stock_over  = 0.0
        for cat in self.warehouse.inventory.values():
            for s in cat.values():
                if s.MinStock > 0:
                    stock_short += max(0, s.MinStock - s.present_stock) / s.MinStock
                if s.MaxStock > 0:
                    stock_over  += max(0, s.present_stock - s.MaxStock) / s.MaxStock
        feats.append(stock_short)
        feats.append(stock_over)
        # ⑥ 유휴 항 (W6 대응) — fully idle ws 의 평균 지속시간 / IdleWorkerThreshold
        # last_active[ws] = ws 가 fully idle 로 진입한 시각 (_run_job/process_job 에서 갱신)
        idle_norm_sum = 0.0
        for ws in self.workers:
            if self.in_progress.get(ws, 0) == 0:
                idle_norm_sum += (self.env.now - self.last_active[ws]) / max(self.IdleWorkerThreshold, 1.0)
        feats.append(idle_norm_sum / len(self.workers))
        return torch.tensor(feats, dtype=torch.float32)

    def potential(self) -> float:
        # 현재 상태의 목적함수 값 Φ(s). 임의 시점(결정점/종료)에서 호출 가능.
        # per-step 보상 r_t = Φ(s_{t+1})−Φ(s_t) 의 telescoping → 종료 시 episode_reward 와 일치.
        # W3/W4/W6(재고과잉·재고부족·유휴)은 _watch 30s 틱이 누적한 단조 카운터로 반영 —
        # 순간값이 아닌 누적이라야 중간 위반이 telescoping 에서 상쇄되지 않음. 고정 분모로 ~[0,1].
        # ★스케일 균형은 1일 학습 qty≈100(모델당) 기준 — 6항 모두 throughput 의 1.0~1.7× (검증).
        #   W5/W2 는 total_target·전량프리미엄(∝qty)으로 정규화돼 ∝1/qty 줄지만 W4/W6 은 qty 무관
        #   → qty 를 크게(≥500) 키우면 재고·유휴가 지배 + throughput 자체도 0 붕괴. qty~100 유지할 것.
        w = self.RewardWeights
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        return (                                                     # W2 분모 _max_episode_premium = reset 캐싱(전량 프리미엄)
            + (sum(self.Throughput.values()) / total_target)        * w['W5_Throughput']
            - (self.env.now / (work_day * total_target))            * w['W1_TimeElapsed']
            - (self.EpisodeEnergyKwh / self._max_episode_premium)    * w['W2_Energy']   # active 프리미엄만 / 전량 프리미엄 ∈ [0,1] (idle 제외)
            - (self.StockOverflowCount / self._stock_violation_norm) * w['W3_StockOverflow']
            - (self.StockShortageCount / self._stock_violation_norm) * w['W4_StockShortage']
            - (self.IdleViolationCount / self._idle_violation_norm)  * w['W6_IdleWorker']
        )

    def episode_reward(self) -> float:
        # 종료 시 스칼라 보상 = Φ(terminal). learn() 의 마지막 결정 보상 기준값.
        return self.potential()

def train(env, agent, MaxEpisodes, run_name=None, episode_max_sec=EPISODE_DURATION_SEC):
    # 에피소드 = produce_unit 구조 1회(env.run(agent, max_sec=episode_max_sec)). 결정점마다 agent.choose 가
    # rollout 기록 → 종료 후 episode_reward 로 1회 PPO learn. (직렬 step/skip 없음)
    # 매 ep rl_logger_spec 항목 JSONL 기록 + best R 갱신 시에만 agent_mod.pt 저장.
    # episode_max_sec: 1 epoch 길이 (기본 86400s = 1일). target_qty 도달 또는 이 시간 도달 시 종료.
    # 출력 → mod_run/result/runs/<run_name>/  (None 이면 timestamp 자동 생성)
    import os, sys, time
    _ROOT    = os.path.dirname(os.path.abspath(__file__))           # 패키지 루트 (이 파일 위치)
    _MOD_RUN = os.path.join(_ROOT, 'mod_run')                        # 결과·rl_logger 거주지
    if _MOD_RUN not in sys.path:
        sys.path.insert(0, _MOD_RUN)
    from rl_logger import RLLogger

    if run_name is None:
        run_name = 'run_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    _OUT = os.path.join(_MOD_RUN, 'result', 'runs', run_name)
    os.makedirs(_OUT, exist_ok=True)
    print(f'[train] outputs → mod_run/result/runs/{run_name}/', flush=True)
    logger = RLLogger(os.path.join(_OUT, 'rl_log.jsonl'))
    ckpt   = os.path.join(_OUT, 'agent_mod.pt')

    for episode in range(MaxEpisodes):
        if os.path.exists(os.path.join(_OUT, 'STOP')):                 # 협조적 중단(외부 신호)
            print(f'[ep {episode}] STOP sentinel — graceful exit', flush=True)
            break
        agent.reset_buffer()
        summary = env.run(agent=agent, max_sec=episode_max_sec)        # 1 epoch = episode_max_sec (기본 1일)
        R = env.episode_reward()
        decisions = len(agent.buf)
        metrics = agent.learn(R, env.KnowledgeGraph)                   # 진단 dict (B/C/D)
        is_best = logger.log_episode(
            episode, R=R, makespan=summary['makespan_sec'],
            energy=summary['EpisodeEnergyKwh'],
            throughput=dict(env.Throughput), target_qty=dict(env.target_qty),
            decisions=decisions, metrics=metrics,
            violations={'stock_shortage': env.StockShortageCount,     # W4/W3/W6 추세 추적
                        'stock_overflow': env.StockOverflowCount,
                        'idle_violation': env.IdleViolationCount})
        if is_best:
            torch.save(agent.state_dict(), ckpt)                       # best 갱신 시에만, 덮어쓰기
        thru = ' '.join(f'{m}:{env.Throughput[m]}/{env.target_qty[m]}' for m in env.target_qty)
        ev = (metrics or {}).get('critic/explained_variance')
        print(f'[ep {episode:>4}] R={R:+.4f} decisions={decisions} '
              f'makespan={summary["makespan_sec"]:.0f} E={summary["EpisodeEnergyKwh"]:.2f} '
              f'thru=[{thru}] ev={ev} {"BEST↑" if is_best else ""}')
