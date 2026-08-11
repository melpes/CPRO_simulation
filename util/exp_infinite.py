# -*- coding: utf-8 -*-
"""무한생산(배치 반복) + 양방향 동적 재배분(이동+복귀) 래퍼.
   - 배치 반복: 한 배치(target_qty) 완주 시 바로 다음 배치 투입 (max_batches까지). run 종료조건을 완주→(전배치완주 or max_sec)로 교체.
   - 이동: SEMI가 idle_trigger 연속 유휴면 sw_moves 대로 타겟 라인으로 이동.
   - 복귀: 이동분이 타겟 라인에서 idle_trigger 연속 유휴면 SEMI로 복귀 (return=True).
   simulation.py 불가침 → CproSimEnv 상속으로만 확장."""
import simulation as sim


def make_infinite_env_cls(cfg):
    sw = cfg.get('sw_realloc') or {}
    sw_on = bool(sw.get('enabled'))
    sw_src = sw.get('src', 'WWM_SemiAssemblyLine')
    sw_moves = dict(sw.get('moves', {}))
    sw_trigger = float(sw.get('idle_trigger_sec', 600))
    sw_tick = float(sw.get('tick_sec', 30))
    sw_return = bool(sw.get('return', False))
    br = cfg.get('batch_repeat') or {}
    br_on = bool(br.get('enabled'))
    br_max = int(br.get('max_batches', 3))
    br_trigger = br.get('trigger', 'complete')   # 'complete'=완주 후 / 'inject'=마지막투입(첫공정완료) 후=파이프라이닝

    class InfEnv(sim.CproSimEnv):
        def reset(self):
            if not hasattr(self, '_workers0'):
                self._workers0 = {ws: i['worker_count'] for ws, i in self.workers.items()}
            for ws, wc in self._workers0.items():
                self.workers[ws]['worker_count'] = wc
            super().reset()
            self.events = []
            self.sw_log = []
            self._sw_moved = {ws: 0 for ws in sw_moves}
            self._batch = 0
            self._batch_done_h = []
            self._injected = 0                       # 누적 투입 유닛(전 모델 합)
            self._wip_log = []                       # (작업h, 재공품 유닛=투입-완성)
            self._bs = list(self.target_qty.values())[0]
            if sw_on:
                self.env.process(self._sw_monitor())

        # ---- 배치 반복용 run 오버라이드 ----
        def run(self, agent=None, max_sec=None):
            self._agent = agent
            if not br_on:
                return super().run(agent, max_sec)
            self.reset()
            if max_sec is None:
                max_sec = float(self.MaxEpisodeSec)
            self._stop = self.env.event()
            for ws in self.workers:
                self.env.process(self._dispatcher(ws, agent))
            self._inject_batch()                                   # 배치0
            self.env.process(self._watch(max_sec))
            self.env.run(until=self._stop)
            for ws in self.workers:
                self._flush_idle(ws, self.env.now)
            return {'Throughput': dict(self.Throughput), 'makespan_sec': float(self.env.now),
                    'EpisodeEnergyKwh': float(self.total_energy_kwh())}

        def _inject_batch(self):
            for m in self.target_qty:
                for _ in range(self._bs):
                    self.env.process(self.produce_unit(m, self._agent))
            self._injected += self._bs * len(self.target_qty)

        def _watch(self, max_sec):
            while not self._stop.triggered:
                yield self.env.timeout(30)
                if self._is_work_time():                           # 라인별 유휴 worker-초 적산
                    for ws in self.workers:
                        idle = self.workers[ws]['worker_count'] - self.in_progress.get(ws, 0)
                        if idle > 0:
                            self.line_idle_time[ws] = self.line_idle_time.get(ws, 0.0) + idle * 30
                    self._wip_log.append((self._work_elapsed(self.env.now) / 3600,
                                          self._injected - sum(self.Throughput.values())))
                if min(self.Throughput.values()) >= br_max * self._bs or self.env.now >= max_sec:
                    if not self._stop.triggered:
                        self._stop.succeed()
                    return

        def _run_job(self, ws, job, req):
            t0 = self.env.now
            node = self.KnowledgeGraph.nodes[job['pc']]
            yield from super()._run_job(ws, job, req)
            self.events.append({'type': 'job', 'model': node.model_id, 'pc': job['pc'],
                                'line': ws, 't0': float(t0),
                                't_cycle': float(t0 + node.CycleTimeSec),
                                't_total': float(self.env.now)})
            if br_on and self._batch < br_max - 1:
                if br_trigger == 'inject':                        # 파이프라이닝: 유닛 첫 공정 완료 카운트
                    if len(job.get('done_set', ())) == 1:
                        self._inj = getattr(self, '_inj', 0) + 1
                        if self._inj >= (self._batch + 1) * self._bs * len(self.target_qty):
                            self._batch += 1
                            self._batch_done_h.append(self._work_elapsed(self.env.now) / 3600)
                            self._inject_batch()
                else:                                             # 완주 후
                    done = min(self.Throughput.values()) // self._bs
                    if done > self._batch:
                        self._batch = done
                        self._batch_done_h.append(self._work_elapsed(self.env.now) / 3600)
                        self._inject_batch()

        # ---- 양방향 재배분 ----
        def _sw_monitor(self):
            idle_acc = 0.0
            tgt_idle = {ws: 0.0 for ws in sw_moves}
            while True:
                yield self.env.timeout(sw_tick)
                if not self._is_work_time():
                    continue
                semi_idle = (self.in_progress.get(sw_src, 0) == 0 and not self._pending[sw_src])
                tgt_busy = any(self._pending[ws] for ws in sw_moves)          # 받을 라인에 일 밀림
                semi_busy = bool(self._pending[sw_src]) or self.in_progress.get(sw_src, 0) > 0
                if all(self._sw_moved[ws] == 0 for ws in sw_moves):
                    # SEMI 유휴 + 타겟 밀림일 때만 이동(둘 다 한산인 배치 소진 구간엔 억제)
                    idle_acc = idle_acc + sw_tick if (semi_idle and tgt_busy) else 0.0
                    if idle_acc >= sw_trigger:
                        self._do_move(); idle_acc = 0.0
                        tgt_idle = {ws: 0.0 for ws in sw_moves}
                elif sw_return:
                    for ws in sw_moves:
                        if self._sw_moved[ws] > 0:
                            t_idle = (self.in_progress.get(ws, 0) == 0 and not self._pending[ws])
                            # 타겟 유휴 + SEMI 밀림일 때만 복귀
                            tgt_idle[ws] = tgt_idle[ws] + sw_tick if (t_idle and semi_busy) else 0.0
                            if tgt_idle[ws] >= sw_trigger:
                                self._do_return(ws); tgt_idle[ws] = 0.0

        def _do_move(self):
            now = self.env.now
            for ws in [sw_src, *sw_moves]:
                self._flush_idle(ws, now)
            for ws, n in sw_moves.items():
                self.workers[ws]['worker_count'] += n
                r = self.worker_resources[ws]
                r._capacity += n * self.workers[ws].get('UnitsPerWorker', 1)
                r._trigger_put(None); self._wake_dispatcher(ws)
                self._sw_moved[ws] += n
            moved = sum(sw_moves.values())
            self.workers[sw_src]['worker_count'] -= moved
            self.worker_resources[sw_src]._capacity -= moved * self.workers[sw_src].get('UnitsPerWorker', 1)
            self.sw_log.append(('move', round(now / 3600, 2), dict(sw_moves)))

        def _do_return(self, ws):
            now = self.env.now
            self._flush_idle(ws, now); self._flush_idle(sw_src, now)
            n = self._sw_moved[ws]
            self.workers[ws]['worker_count'] -= n
            self.worker_resources[ws]._capacity -= n * self.workers[ws].get('UnitsPerWorker', 1)
            self.workers[sw_src]['worker_count'] += n
            r = self.worker_resources[sw_src]
            r._capacity += n * self.workers[sw_src].get('UnitsPerWorker', 1)
            r._trigger_put(None); self._wake_dispatcher(sw_src)
            self._sw_moved[ws] -= n
            self.sw_log.append(('return', round(now / 3600, 2), {ws: n}))

    return InfEnv
