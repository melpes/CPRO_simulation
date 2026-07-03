# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import simpy
import torch

import carbon
from warehouse import Warehouse, _StockRouter


EPISODE_DURATION_SEC = 30 * 86400

class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold, RuntimeVariables,
                 DefaultProcessConsumedPowerKw, SelfManagedBOM=None,
                 SMTLines=None, SmtArrayPcb=6, SmtBatchArrays=40, DueDay=None,
                 InfiniteStock=False, ScenarioMode='FINITE', MaxEpisodeSec=None):
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
        self.WarehouseManagedBOM  = WarehouseManagedBOM
        self.SelfManagedBOM       = SelfManagedBOM
        self.BOMCategory          = BOMCategory
        self.WorkStartTime        = WorkStartTime
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec
        self.break_end_sec        = break_end_sec
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.DefaultProcessConsumedPowerKw = DefaultProcessConsumedPowerKw
        self.RuntimeVariables     = RuntimeVariables
        self.SMTLines             = SMTLines
        self.SmtArrayPcb          = SmtArrayPcb
        self.SmtBatchArrays       = SmtBatchArrays
        self.DueDay               = DueDay
        self.InfiniteStock        = InfiniteStock
        self.ScenarioMode         = ScenarioMode
        self.MaxEpisodeSec        = MaxEpisodeSec
        self.IdleRewardMode       = 'time'   # 'time'=event 유휴시간(임계초과)·event 로그 / 'count'=옛 30초틱 카운트
        self.DueRewardMode        = 'sparse' # 'sparse'=PO 완료시각 vs 납기(빠르면+, 늦으면−) / 'pace'=옛 페이스결손 누적

    def reset(self):
        self.env                  = simpy.Environment()
        self.CycleCompleted       = False
        self.Throughput           = {model_id: 0 for model_id in self.target_qty}
        self.EpisodeEnergyKwh     = 0.0
        self.SMTEnergyKwh         = 0.0
        self.line_energy          = {}        # 라인(워크스테이션·SMT)별 active 에너지 kWh
        self.StockShortageCount   = 0
        self.StockOverflowCount   = 0
        self.IdleViolationCount   = 0
        self.DuePaceDeficit       = 0.0
        self.DuePaceDeficitByModel = {model_id: 0.0 for model_id in self.target_qty}
        self.CompletionSec        = {model_id: None for model_id in self.target_qty}  # 모델별 PO 수량 충족 시각(초)
        self.smt_equip_energy     = {}        # SMT 세부공정(Loader~AOI)별 에너지 kWh: {line_id: {equip: kwh}}
        self.completed            = set()
        self.in_progress          = {}
        self.idle_time            = {}
        self.last_active          = {ws: 0.0 for ws in self.workers}
        self.line_idle_time       = {ws: 0.0 for ws in self.workers}   # 라인별 유휴 worker-초(작업시간 내, event 적산)
        self.line_idle_viol       = {ws: 0.0 for ws in self.workers}   # 임계(IdleWorkerThreshold) 초과 유휴 worker-초 (W6용)
        self._idle_last_t         = {ws: 0.0 for ws in self.workers}   # event 적산: 라인별 직전 flush 시각
        self._cont_idle           = {ws: 0.0 for ws in self.workers}   # 라인 연속 유휴 작업시간(초), 만가동 시 리셋
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        if self.SelfManagedBOM:
            self._pcb_warehouse   = Warehouse.build(self.SelfManagedBOM, self.BOMCategory)
            self.warehouse        = _StockRouter(self.warehouse, self._pcb_warehouse)
            import smt
            smt.start(self)
        self.worker_resources     = {
            WorkstationId: simpy.Resource(self.env,
                                          capacity=info['worker_count'] * info['UnitsPerWorker'])
            for WorkstationId, info in self.workers.items()
        }
        self._pending   = {ws: [] for ws in self.workers}
        self._disp_wake = {ws: self.env.event() for ws in self.workers}
        self._stock_wake = self.env.event()
        work_day_sec              = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        nominal_work_ticks        = work_day_sec / 30.0
        self._stock_violation_norm = max(1.0, sum(len(items) for items in self._counted_warehouse().inventory.values())
                                               * nominal_work_ticks)
        self._idle_violation_norm  = max(1.0, sum(info['worker_count'] for info in self.workers.values())
                                               * nominal_work_ticks)
        self._due_violation_norm   = max(1.0, len(self.target_qty) * nominal_work_ticks)
        smt_plan = getattr(self, 'SmtPlanEffective', None)      # smt.start(reset 상단)가 설정 — 계획생산이면 계획 dict
        smt_kw = (sum(power for eq in self.SMTLines.values() for _, _, power in eq)
                  if (self.SMTLines and self.SelfManagedBOM and not smt_plan) else 0.0)   # 연속 모델일 때만 정격×지평
        self.MaxEpisodeEnergyKwh = self.RuntimeVariables.MaxEpisodeEnergyKwh(
            self.KnowledgeGraph, self.target_qty, self.workers, work_day_sec,
            self.DefaultProcessConsumedPowerKw, smt_kw,
            HorizonMode=getattr(self, 'W2HorizonMode', 'bottleneck'))
        if smt_plan:                                            # 계획생산: SMT 항 = 계획 전량 생산 에너지(해석식)
            import smt
            self.MaxEpisodeEnergyKwh += smt.plan_energy_kwh(self, smt_plan)
    
    def _counted_warehouse(self):
        """W3/W4·재고 관측이 세는 창고 = 주창고만. SMT 자체관리 PCB(무한 공급, SMT가 계속 채움)는
        재고 위반 대상이 아니므로 제외 — 라우터(_StockRouter)면 main, 아니면 그대로."""
        return getattr(self.warehouse, 'main', self.warehouse)

    @property
    def SteadyWIP(self) -> int:
        """STEADY 정상상태 유지 WIP(모델당, 1배) = 전체 capacity ÷ 모델수. 초기 충전은 이의 2배로 넣고
        완성되며 1배(이 값)로 수렴·유지 → 초기 버퍼 여유 + 정상상태 과잉재공 방지."""
        capacity = sum(i['worker_count'] * i['UnitsPerWorker'] for i in self.workers.values())
        return max(1, capacity // len(self.target_qty))

    def _is_work_time(self) -> bool:
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def _off_hours_delta(self) -> float:
        sid = self.env.now % 86400
        if sid < self.WorkStartTime:
            return self.WorkStartTime - sid
        if self.break_start_sec <= sid < self.break_end_sec:
            return self.break_end_sec - sid
        return 86400 - sid + self.WorkStartTime

    def _work_elapsed(self, t: float) -> float:
        """0~t 누적 작업시간(초). 일 단위 modulo·휴게 제외, 주말 없음 — _is_work_time과 동일 스케줄."""
        day = 86400.0
        wd  = (self.WorkEndTime - self.WorkStartTime) - (self.break_end_sec - self.break_start_sec)
        full = int(t // day)
        sid  = t - full * day
        def seg(a, b):                                  # [0,sid] ∩ [a,b] 길이
            return max(0.0, min(sid, b) - a) if sid > a else 0.0
        partial = seg(self.WorkStartTime, self.break_start_sec) + seg(self.break_end_sec, self.WorkEndTime)
        return full * wd + partial

    def _flush_idle(self, ws, now: float):
        """직전 flush~now 구간 유휴를 작업시간 기준으로 event 적산.
        line_idle_time=총 유휴 worker-초, line_idle_viol=임계 초과분 worker-초(W6). in_progress 변경 직전에 호출."""
        if self.IdleRewardMode != 'time':                                          # count 모드: 30초 틱(_watch)이 담당
            return
        s_prev = self.workers[ws]['worker_count'] - self.in_progress.get(ws, 0)     # 구간 중 유휴 슬롯 수
        dt = self._work_elapsed(now) - self._work_elapsed(self._idle_last_t[ws])    # 구간 작업시간(초)
        if s_prev > 0 and dt > 0:
            self.line_idle_time[ws] += s_prev * dt
            thr    = max(self.IdleWorkerThreshold, 0.0)
            before = max(0.0, self._cont_idle[ws] - thr)
            self._cont_idle[ws] += dt
            after  = max(0.0, self._cont_idle[ws] - thr)
            self.line_idle_viol[ws] += s_prev * (after - before)                    # 5분 넘긴 부분만
        if s_prev == 0:
            self._cont_idle[ws] = 0.0                                               # 만가동 → 연속 유휴 리셋
        self._idle_last_t[ws] = now

    def process_job(self, ProcessCode, WorkstationId, done_set):
        self._flush_idle(WorkstationId, self.env.now)
        self.in_progress[WorkstationId] = self.in_progress.get(WorkstationId, 0) + 1
        node = self.KnowledgeGraph.nodes[ProcessCode]
        while not self._is_work_time():
            yield self.env.timeout(self._off_hours_delta())
        with self.worker_resources[WorkstationId].request() as req:
            yield req
            yield self.env.timeout(node.CycleTimeSec)
        _e0 = self.EpisodeEnergyKwh
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh)
        self.line_energy[WorkstationId] = self.line_energy.get(WorkstationId, 0.0) + (self.EpisodeEnergyKwh - _e0)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM, deduct=not self.InfiniteStock)
            if ordered:                              # 무한재고면 ordered=[] → 발주 없음, 소비는 기록됨
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered))
        if node.OutputBOM:
            self.warehouse.produce(node.OutputBOM)
        done_set.add(ProcessCode)
        self._flush_idle(WorkstationId, self.env.now)
        self.in_progress[WorkstationId] -= 1
        if self.in_progress[WorkstationId] == 0:
            self.last_active[WorkstationId] = self.env.now
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(ProcessCode, self.KnowledgeGraph)

    def _ready_for(self, model_id, done_set):
        return [pc for pc in self.KnowledgeGraph.ready_queue(
                    self.IndependentSequence, self.DependentSequence,
                    self.DependentJoin, done_set, self.warehouse, self.InfiniteStock)
                if self.KnowledgeGraph.nodes[pc].model_id in (model_id, 'ALL')]

    def _workstation_of(self, ProcessCode):
        return next((ws for ws in self.workers
                     if ProcessCode in self.workers[ws]['ProcessCode']), None)

    def _wake_dispatcher(self, ws):
        ev = self._disp_wake[ws]
        if not ev.triggered:
            ev.succeed()

    def _wake_stock(self):
        ev = self._stock_wake
        self._stock_wake = self.env.event()
        if not ev.triggered:
            ev.succeed()

    def _dispatcher(self, ws, agent):
        res = self.worker_resources[ws]
        while True:
            if not self._pending[ws]:
                self._disp_wake[ws] = self.env.event()
                yield self._disp_wake[ws]
                continue
            if not self._is_work_time():
                yield self.env.timeout(self._off_hours_delta())
                continue
            req = res.request()
            yield req
            pend = self._pending[ws]
            if not pend:
                res.release(req)
                continue
            distinct_pcs = list(dict.fromkeys(j['pc'] for j in pend))
            if agent is not None and len(distinct_pcs) >= 2:
                chosen_pc = agent.choose(distinct_pcs, self)
                job = next(j for j in pend if j['pc'] == chosen_pc)
            else:
                job = pend[0]
            pend.remove(job)
            self.env.process(self._run_job(ws, job, req))

    def _run_job(self, ws, job, req):
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        self._flush_idle(ws, self.env.now)
        self.in_progress[ws] = self.in_progress.get(ws, 0) + 1
        yield self.env.timeout(node.CycleTimeSec)
        self.worker_resources[ws].release(req)
        _e0 = self.EpisodeEnergyKwh
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh)
        self.line_energy[ws] = self.line_energy.get(ws, 0.0) + (self.EpisodeEnergyKwh - _e0)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM, deduct=not self.InfiniteStock)
            if ordered:                              # 무한재고면 ordered=[] → 발주 없음, 소비는 기록됨
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered, self._wake_stock))
        if node.OutputBOM:
            self.warehouse.produce(node.OutputBOM)
        self._flush_idle(ws, self.env.now)
        self.in_progress[ws] -= 1
        if self.in_progress[ws] == 0:
            self.last_active[ws] = self.env.now
        self._wake_dispatcher(ws)

        if node.DepWaitSec:
            yield self.env.timeout(node.DepWaitSec)

        job['done_set'].add(pc)
        job['in_flight'].discard(pc)
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(pc, self.KnowledgeGraph)
        self.Throughput = self.RuntimeVariables.Throughput(pc, self.KnowledgeGraph, self.Throughput)
        _mid = node.model_id
        if (_mid in self.CompletionSec and self.CompletionSec[_mid] is None
                and self.Throughput.get(_mid, 0) >= self.target_qty[_mid]):
            self.CompletionSec[_mid] = self.env.now
        if not job['ev'].triggered:
            job['ev'].succeed()

    def produce_unit(self, model_id, agent=None):
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
                yield self._stock_wake
                continue
            yield simpy.AnyOf(self.env, outstanding)
            outstanding = [e for e in outstanding if not e.triggered]

    def _steady_feed(self, model_id, agent, max_sec, hold):
        """무한생산(STEADY): 완성 즉시 재투입하되, 현재 WIP가 hold(1배) 초과면 재투입 없이 슬롯 종료.
        초기 2배 충전분이 완성되며 hold 로 수렴, 이후 hold 만큼 상시 재공 유지. max_sec 까지."""
        while self.env.now < max_sec:
            yield from self.produce_unit(model_id, agent)
            self._inflight[model_id] -= 1
            if self._inflight[model_id] >= hold:
                return                              # 초기 과충전분 → 재투입 없이 종료(WIP가 hold로 수렴)
            self._inflight[model_id] += 1           # hold 유지 위해 재투입

    def run(self, agent=None, max_sec: float = None):
        self.reset()
        if max_sec is None:                                # 에피소드 시간 상한 = MaxEpisodeSec (모드 무관, AAS)
            max_sec = float(self.MaxEpisodeSec)
        stop = self.env.event()
        for ws in self.workers:
            self.env.process(self._dispatcher(ws, agent))
        if self.ScenarioMode == 'STEADY':                  # 무한생산: 초기 2배 충전 → 1배(SteadyWIP)로 수렴 유지
            hold = self.SteadyWIP                           # 정상상태 유지 WIP(모델당, 1배)
            self._inflight = {m: hold * 2 for m in self.target_qty}   # 초기 충전 = 2배
            for model_id in self.target_qty:
                for _ in range(hold * 2):
                    self.env.process(self._steady_feed(model_id, agent, max_sec, hold))
        else:
            for model_id, qty in self.target_qty.items():
                for _ in range(qty):
                    self.env.process(self.produce_unit(model_id, agent))

        def _watch():
            while not stop.triggered:
                yield self.env.timeout(30)
                if self._is_work_time():
                    self.StockShortageCount = self.RuntimeVariables.StockShortageCount(
                        self._counted_warehouse(), self.StockShortageCount)
                    self.StockOverflowCount = self.RuntimeVariables.StockOverflowCount(
                        self._counted_warehouse(), self.StockOverflowCount)
                    if self.IdleRewardMode == 'count':                # 옛 방식: 30초 틱 카운트/누적
                        self.IdleViolationCount = self.RuntimeVariables.IdleViolationCount(
                            self.workers, self.in_progress, self.idle_time, self.env.now,
                            self.IdleWorkerThreshold, self.IdleViolationCount)
                        for _ws in self.workers:                      # 라인별 유휴 worker-초 (30s 틱, 작업시간만)
                            _idle = self.workers[_ws]['worker_count'] - self.in_progress.get(_ws, 0)
                            if _idle > 0:
                                self.line_idle_time[_ws] += _idle * 30
                    self.DuePaceDeficit = self.RuntimeVariables.DuePaceDeficit(
                        self.Throughput, self.target_qty, self.DueDay, self.env.now,
                        self.DuePaceDeficit)
                    self.DuePaceDeficitByModel = self.RuntimeVariables.DuePaceDeficitByModel(
                        self.Throughput, self.target_qty, self.DueDay, self.env.now,
                        self.DuePaceDeficitByModel)
                target_met = all(self.Throughput[m] >= self.target_qty[m] for m in self.target_qty)
                if ((self.ScenarioMode != 'STEADY' and target_met)
                        or self.env.now >= max_sec):
                    if not stop.triggered:
                        stop.succeed()
                    return
        self.env.process(_watch())
        self.env.run(until=stop)
        for ws in self.workers:                        # 마지막 구간 유휴 event 적산 마감
            self._flush_idle(ws, self.env.now)
        return {
            'Throughput'      : dict(self.Throughput),
            'makespan_sec'    : float(self.env.now),
            'EpisodeEnergyKwh': float(self.total_energy_kwh()),
            'ActivePremiumKwh': float(self.EpisodeEnergyKwh),
            'IdleEnergyKwh'   : float(self.baseline_energy_kwh()),
            'SMTEnergyKwh'    : float(self.SMTEnergyKwh),
            'SMTEquipEnergy'  : {line: {eq: float(v) for eq, v in eqs.items()}       # SMT 세부공정별 kWh
                                 for line, eqs in self.smt_equip_energy.items()},
            'CompletionSec'   : {m: (float(t) if t is not None else None)            # 모델별 PO 완료 시각(초)
                                 for m, t in self.CompletionSec.items()},
            'LineEnergy'      : {k: float(v) for k, v in self.line_energy.items()},
            'RewardTerms'     : {k: float(v) for k, v in self.reward_terms().items()},
            'LineIdleTime'    : {k: float(v) / self.workers[k]['worker_count']                # 라인별: 작업자당 평균 유휴(초)
                                 for k, v in self.line_idle_time.items()},
            'TotalIdleTime'   : float(sum(self.line_idle_time.values())),                     # 총: 전체 작업자 유휴 합(worker-초, 나누지 않음)
        }

    def baseline_energy_kwh(self) -> float:
        """근무시간 기저 적산(kWh) — 설비(워크스테이션)당 DefaultProcessConsumedPowerKw 상시 소모."""
        return self.RuntimeVariables.IdleBaselineKwh(
            self.workers, self._work_elapsed(self.env.now),
            self.DefaultProcessConsumedPowerKw)

    def total_energy_kwh(self) -> float:
        """실 전력 총 적산 = 기저 + 조립 가동 + SMT 가동. W2 분자·관측·summary 공통."""
        return self.baseline_energy_kwh() + self.EpisodeEnergyKwh + self.SMTEnergyKwh

    @property
    def state_dim(self) -> int:
        return len(self.target_qty) + 2 + len(self.workers) + 4

    def state_vec(self) -> torch.Tensor:
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        feats = []
        for model_id in self.target_qty:
            feats.append(self.Throughput[model_id] / self.target_qty[model_id])
        feats.append(self.env.now / max(work_day * total_target, 1.0))
        feats.append(self.total_energy_kwh() / self.MaxEpisodeEnergyKwh)
        for ws, info in self.workers.items():
            feats.append(self.in_progress.get(ws, 0) / info['worker_count'])
        stock_short = 0.0
        stock_over  = 0.0
        for cat in self._counted_warehouse().inventory.values():
            for s in cat.values():
                if s.MinStock > 0:
                    stock_short += max(0, s.MinStock - s.present_stock) / s.MinStock
                if s.MaxStock > 0:
                    stock_over  += max(0, s.present_stock - s.MaxStock) / s.MaxStock
        feats.append(stock_short)
        feats.append(stock_over)
        idle_norm_sum = 0.0
        for ws in self.workers:
            if self.in_progress.get(ws, 0) == 0:
                idle_norm_sum += (self.env.now - self.last_active[ws]) / max(self.IdleWorkerThreshold, 1.0)
        feats.append(idle_norm_sum / len(self.workers))
        due_deficit = 0.0
        for model_id in self.target_qty:
            required = min(self.env.now / self.DueDay[model_id], 1.0)
            due_deficit += max(0.0, required - self.Throughput[model_id] / self.target_qty[model_id])
        feats.append(due_deficit / len(self.target_qty))
        return torch.tensor(feats, dtype=torch.float32)

    def reward_terms(self) -> dict:
        """항별(W1~W8) 가중·정규화된 보상 기여도. 합 = potential()."""
        RW = self.RewardWeights
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        total_workers = sum(info['worker_count'] for info in self.workers.values())
        if self.IdleRewardMode == 'count':                                       # 옛 방식: 카운트/카운트norm
            w6 = - (self.IdleViolationCount / self._idle_violation_norm) * RW['W6_IdleWorker']
        else:                                                                    # 신 방식: 임계초과 유휴시간 비율
            idle_avail = max(1.0, total_workers * self._work_elapsed(self.env.now))
            w6 = - (sum(self.line_idle_viol.values()) / idle_avail) * RW['W6_IdleWorker']
        if self.DueRewardMode == 'pace':                                         # 옛 방식: 페이스결손 누적
            w7 = - (self.DuePaceDeficit / self._due_violation_norm) * RW['W7_DueDate']
        else:                                                                    # 신(sparse): 모델별 PO 완료시각 vs 납기
            margin = 0.0                                                         # (Due-완료)/Due — 빠르면 +, 늦으면 −
            for model_id in self.target_qty:
                done_t = self.CompletionSec[model_id]
                if done_t is not None:
                    margin += (self.DueDay[model_id] - done_t) / self.DueDay[model_id]
                elif self.env.now > self.DueDay[model_id]:                       # 미완료·납기 경과: 경과분 페널티(하한)
                    margin += (self.DueDay[model_id] - self.env.now) / self.DueDay[model_id]
            w7 = (margin / len(self.target_qty)) * RW['W7_DueDate']
        return {
            'W5_Throughput':    + (sum(self.Throughput.values()) / total_target)                                * RW['W5_Throughput'],
            'W1_TimeElapsed':   - (self.env.now / (work_day * total_target))                                    * RW['W1_TimeElapsed'],
            'W2_Energy':        - (carbon.total(self.total_energy_kwh()) / carbon.total(self.MaxEpisodeEnergyKwh)) * RW['W2_Energy'],
            'W3_StockOverflow': - (self.StockOverflowCount / self._stock_violation_norm)                        * RW['W3_StockOverflow'],
            'W4_StockShortage': - (self.StockShortageCount / self._stock_violation_norm)                        * RW['W4_StockShortage'],
            'W6_IdleWorker':    w6,
            'W7_DueDate':       w7,
            'W8_Imbalance':     - self._production_imbalance()                                                  * RW['W8_Imbalance'],
        }

    def potential(self) -> float:
        for ws in self.workers:                        # 유휴 event 적산 최신화(결정 시점마다)
            self._flush_idle(ws, self.env.now)
        return sum(self.reward_terms().values())

    def _production_imbalance(self) -> float:
        """무한생산(steady) 시 모델 간 완성 편차 페널티: (max-min 모델완성수)/총완성수, [0,1].
        0=완전 균등. 생산성 높은 모델만 만들고 낮은 모델을 방치하는 정책을 억제(W8_Imbalance)."""
        counts = list(self.Throughput.values())
        done   = sum(counts)
        if done < 1:
            return 0.0
        return (max(counts) - min(counts)) / done

    def episode_reward(self) -> float:
        return self.potential()


def obs_node_features(kg):
    if kg.NodeFeatureAttrs is None:
        raise RuntimeError('KnowledgeGraph.NodeFeatureAttrs 미설정 — ObservationNodeFeatures(AAS) 필요')
    sample  = next(iter(kg.nodes.values()))
    missing = [attr for attr in kg.NodeFeatureAttrs if not hasattr(sample, attr)]
    if missing:
        raise RuntimeError(f'ObservationNodeFeatures 항목이 GraphNode 속성이 아님: {missing}')
    return torch.tensor([[getattr(kg.nodes[pc], attr) for attr in kg.NodeFeatureAttrs]
                         for pc in kg.nodes], dtype=torch.float)

def obs_graph_topology(kg):
    node_index = {pc: i for i, pc in enumerate(kg.nodes)}
    src, dst = [], []
    for DepPrev, GraphEdges in kg.edges.items():
        for GraphEdge in GraphEdges:
            if DepPrev in node_index and GraphEdge.ProcessCode in node_index:
                src.append(node_index[DepPrev]); dst.append(node_index[GraphEdge.ProcessCode])
    return torch.tensor([src, dst], dtype=torch.long)

def obs_state_vector(env):
    return env.state_vec()

OBSERVATION_CATALOG = {
    'NodeFeatures':  obs_node_features,
    'GraphTopology': obs_graph_topology,
    'StateVector':   obs_state_vector,
}


class PPOAgent(torch.nn.Module):
    def __init__(self, *, encoder, actor, critic, StateDim,
                 LearningRate, ClipEpsilon, Gamma, GaeLambda,
                 EntropyCoef, ValueLossCoef, UpdateEpochs, BatchSize, RuntimeVariables):
        super().__init__()
        self.StateDim        = StateDim
        self.GNNEncoder      = encoder
        self.Actor           = actor
        self.Critic          = critic
        self.ClipEpsilon     = ClipEpsilon
        self.Gamma           = Gamma
        self.GaeLambda       = GaeLambda
        self.EntropyCoef     = EntropyCoef
        self.ValueLossCoef   = ValueLossCoef
        self.UpdateEpochs    = UpdateEpochs
        self.BatchSize       = BatchSize
        self.RuntimeVariables = RuntimeVariables
        self.optimizer       = torch.optim.Adam(self.parameters(), lr=LearningRate)

    def reset_buffer(self):
        self.buf = []

    @torch.no_grad()
    def choose(self, ready_pcs, env):
        kg               = env.KnowledgeGraph
        node_list        = list(kg.nodes.keys())
        embeddings       = self.GNNEncoder(NodeFeatures=obs_node_features(kg), GraphTopology=obs_graph_topology(kg))
        ready_emb        = torch.stack([embeddings[node_list.index(pc)] for pc in ready_pcs])
        state            = env.state_vec() if self.StateDim > 0 else None
        dist             = torch.distributions.Categorical(self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=state))
        idx              = dist.sample() if self.training else dist.probs.argmax()
        value            = self.Critic(PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True), StateVector=state).squeeze()
        self.buf.append({'ready': list(ready_pcs), 'idx': int(idx.item()),
                         'logp': dist.log_prob(idx),
                         'value': value,
                         'state': state,
                         'phi': float(env.potential())})
        return ready_pcs[idx.item()]

    def learn(self, episode_return, KnowledgeGraph):
        if not self.buf:
            return None
        n        = len(self.buf)
        values   = torch.stack([b['value'] for b in self.buf])
        old_logp = torch.stack([b['logp']  for b in self.buf])
        phi      = [b['phi'] for b in self.buf]

        rewards = torch.tensor(
            [(phi[i + 1] if i < n - 1 else float(episode_return)) - phi[i]
             for i in range(n)], dtype=torch.float32)

        advantages = torch.zeros(n)
        gae = 0.0
        for t in reversed(range(n)):
            v_next = values[t + 1] if t < n - 1 else 0.0
            delta  = rewards[t] + self.Gamma * v_next - values[t]
            gae    = delta + self.Gamma * self.GaeLambda * gae
            advantages[t] = gae
        returns = advantages + values
        adv     = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        grad_norm = 0.0
        for _ in range(self.UpdateEpochs):
            node_list      = list(KnowledgeGraph.nodes.keys())
            node_features  = obs_node_features(KnowledgeGraph)
            graph_topology = obs_graph_topology(KnowledgeGraph)
            perm = torch.randperm(n).tolist()
            for s in range(0, n, self.BatchSize):                     # 미니배치: backward 그래프를 BatchSize 로 고정(에피소드 길이 무관, OOM 방지)
                mb = perm[s:s + self.BatchSize]
                embeddings = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)  # 미니배치당 1회(전이들이 공유)
                new_logp, entropy, value_preds = [], [], []
                for i in mb:
                    b          = self.buf[i]
                    ready_emb  = torch.stack([embeddings[node_list.index(pc)] for pc in b['ready']])
                    state      = b['state']
                    dist       = torch.distributions.Categorical(self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=state))
                    new_logp.append(dist.log_prob(torch.tensor(b['idx'])))
                    entropy.append(dist.entropy())
                    value_preds.append(self.Critic(PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True), StateVector=state).squeeze())
                new_logp    = torch.stack(new_logp)
                entropy     = torch.stack(entropy)
                value_preds = torch.stack(value_preds)
                mb_adv      = adv[mb]
                mb_oldlogp  = old_logp[mb]
                mb_returns  = returns[mb]
                ratio       = torch.exp(new_logp - mb_oldlogp)
                actor_loss  = -torch.min(
                                  ratio * mb_adv,
                                  torch.clamp(ratio, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * mb_adv
                              ).mean()
                critic_loss = torch.nn.functional.mse_loss(value_preds, mb_returns)
                loss        = actor_loss + self.ValueLossCoef * critic_loss - self.EntropyCoef * entropy.mean()
                self.optimizer.zero_grad()
                loss.backward()
                grad_norm = float(torch.nn.utils.clip_grad_norm_(self.parameters(), 0.5))
                self.optimizer.step()

        with torch.no_grad():                                        # 진단은 마지막 미니배치 기준(근사)
            resid_var  = float((mb_returns - value_preds).var(unbiased=False))   # 1샘플 미니배치 dof 경고 방지
            ret_var    = float(mb_returns.var(unbiased=False))
            clip_frac  = float(((ratio - 1.0).abs() > self.ClipEpsilon).float().mean())
            approx_kl  = float((mb_oldlogp - new_logp).mean())
            return {
                'critic/explained_variance': (float('nan') if ret_var < 1e-9
                                              else 1.0 - resid_var / ret_var),
                'critic/value_loss'        : float(critic_loss),
                'critic/v_mean'            : float(value_preds.mean()),
                'critic/v_max'             : float(value_preds.max()),
                'critic/returns_var'       : ret_var,
                'stability/approx_kl'      : approx_kl,
                'stability/clip_fraction'  : clip_frac,
                'stability/grad_norm'      : grad_norm,
                'stability/learning_rate'  : float(self.optimizer.param_groups[0]['lr']),
                'exploration/entropy'      : float(entropy.mean()),
                'actor/loss'               : float(actor_loss),
            }

import importlib, inspect

def import_callable(path: str):
    module, name = path.rsplit('.', 1)
    return getattr(importlib.import_module(module), name)

def op_concat_state(x, state=None):
    if state is None:
        return x
    return torch.cat([x, state.unsqueeze(0).expand(x.size(0), -1)], dim=-1)

def op_squeeze_last(input):
    return input.squeeze(-1)


class GraphModule(torch.nn.Module):
    def __init__(self, spec, source_dims=None):
        super().__init__()
        self.spec = spec
        self.mods = torch.nn.ModuleDict()
        dim = dict(source_dims or {})
        for node in spec:
            operation = node['Operation']
            arguments = dict(node.get('Arguments', {}))
            in_dim    = {param: dim.get(src) for param, src in node['Inputs'].items()}
            callable_ = import_callable(operation)
            if isinstance(callable_, type) and issubclass(callable_, torch.nn.Module):
                params = inspect.signature(callable_).parameters
                if 'in_features' in params and 'in_features' not in arguments:
                    arguments['in_features'] = in_dim['input']
                elif 'in_channels' in params and 'in_channels' not in arguments:
                    arguments['in_channels'] = in_dim['x']
                self.mods[node['id']] = callable_(**arguments)
                out_dim = arguments.get('out_features', arguments.get('out_channels'))
            elif operation.endswith('op_concat_state'):
                out_dim = (in_dim.get('x') or 0) + (in_dim.get('state') or 0)
            else:
                out_dim = next((d for d in in_dim.values() if d is not None), None)
            dim[node['id']] = out_dim

    def forward(self, **sources):
        vals = dict(sources)
        out = None
        for node in self.spec:
            bound = {param: vals[src] for param, src in node['Inputs'].items()}
            if node['id'] in self.mods:
                out = self.mods[node['id']](**bound)
            else:
                out = import_callable(node['Operation'])(**bound, **node.get('Arguments', {}))
            vals[node['id']] = out
        return out
