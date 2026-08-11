# 컴프레서 기저이관 AAS 기준 FIFO 종료시각 스윕 — RL 학습 결과와 비교할 기준선
# 각 종료시각에서 q540(모델당 540) 완주. 작업시간·완성시각·전력(TOU 대역별)을 산출.
import sys, os, json, time

PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE)
sys.dont_write_bytecode = True

ENDS  = [18.0, 18.5, 19.0, 19.5, 20.0, 21.0, 22.5]
QTY   = {"MODEL_A": 540, "MODEL_B": 540, "MODEL_C": 540}
DUE   = 5
MAXS  = 2592000
FILES = ('ProvisionOfSimulationModel.json', 'AssemblyByWorker.json',
         'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json', 'SMTEquipmentCatalog.json')

# 요율 (결정 1279/QĐ-BCT, 6~22kV, VND/kWh) · 시간대 (결정 963/QĐ-BCT)
TARIFF = {'normal': 1899.0, 'peak': 3508.0, 'night': 1234.0}
NIGHT_END, PEAK_START, PEAK_END = 6 * 3600.0, 17.5 * 3600.0, 22.5 * 3600.0
DAY = 86400.0


def band_energy(a, b, kw):
    out = {'normal': 0.0, 'peak': 0.0, 'night': 0.0}
    t = a
    while t < b - 1e-9:
        d = t % DAY
        if   d < NIGHT_END:  band, nxt = 'night',  t + (NIGHT_END - d)
        elif d < PEAK_START: band, nxt = 'normal', t + (PEAK_START - d)
        elif d < PEAK_END:   band, nxt = 'peak',   t + (PEAK_END - d)
        else:                band, nxt = 'normal', t + (DAY - d)
        seg = min(b, nxt)
        out[band] += kw * (seg - t) / 3600.0
        t = seg
    return out


def add(acc, part):
    for k, v in part.items():
        acc[k] = acc.get(k, 0.0) + v
    return acc


def tou(env, makespan):
    acc = {'normal': 0.0, 'peak': 0.0, 'night': 0.0}
    day0 = 0
    while day0 < makespan:                                   # 기저: 근무창 × 일수
        for w0, w1 in ((env.WorkStartTime, env.break_start_sec),
                       (env.break_end_sec, env.WorkEndTime)):
            a, b = day0 + w0, min(day0 + w1, makespan)
            if b > a:
                add(acc, band_energy(a, b, env.DefaultProcessConsumedPowerKw))
        day0 += DAY
    for ev in env.events:                                    # 조립: 정격을 이벤트 구간에 균등
        node = env.KnowledgeGraph.nodes[ev['process_code']]
        if node.RatedPowerKw:
            add(acc, band_energy(ev['start_sec'], ev['end_sec'], node.RatedPowerKw))
    for b in getattr(env, 'smt_batches', []):                # SMT: 배치 실적립 kWh를 시간창에 균등
        dur = b['end_sec'] - b['start_sec']
        if dur > 0 and b['kwh'] > 0:
            add(acc, band_energy(b['start_sec'], b['end_sec'], b['kwh'] / (dur / 3600.0)))
    return acc, sum(acc[k] * TARIFF[k] for k in acc)


def worktime(env, t):
    """절대 시각 t 를 순수 작업시간(야간·점심 제외) 좌표로 환산."""
    per_day = (env.WorkEndTime - env.WorkStartTime) - (env.break_end_sec - env.break_start_sec)
    d, s = int(t // DAY), t - int(t // DAY) * DAY
    if   s < env.WorkStartTime:   x = 0.0
    elif s < env.break_start_sec: x = s - env.WorkStartTime
    elif s < env.break_end_sec:   x = float(env.break_start_sec - env.WorkStartTime)
    elif s < env.WorkEndTime:     x = (s - env.break_end_sec) + (env.break_start_sec - env.WorkStartTime)
    else:                         x = float(per_day)
    return d * per_day + x


def batch_log(cls):
    class _E(cls):
        def reset(self):
            super().reset()
            self.smt_batches = []

        def smt_record(self, line_id, equipment, code, t_end, array_cycle, array_energy):
            super().smt_record(line_id, equipment, code, t_end, array_cycle, array_energy)
            self.smt_batches.append({'start_sec': float(t_end) - float(array_cycle),
                                     'end_sec': float(t_end), 'kwh': float(array_energy)})
    return _E


def main():
    import path_extractor, build, run_trained
    for f in FILES:
        path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
    base_cls = run_trained._schedule_env_cls()                # events / smt_events 기록

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifo_sweep_comp2base.json')
    results = []
    for end_h in ENDS:
        t0 = time.time()
        env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                     env_cls=batch_log(base_cls))
        env.WorkEndTime  = end_h * 3600.0
        env.MaxEpisodeSec = MAXS
        env.reset()
        env.run(agent=None, max_sec=MAXS)                     # agent=None → FIFO
        makespan = env.env.now
        bands, cost = tou(env, makespan)
        r = {
            'end_hour': end_h, 'wall_sec': round(time.time() - t0, 1),
            'makespan_days': makespan / DAY,
            'work_time_h': worktime(env, makespan) / 3600.0,
            'completion_days': {m: (v / DAY if v is not None else None)
                                for m, v in env.CompletionSec.items()},
            'completion_work_h': {m: (worktime(env, v) / 3600.0 if v is not None else None)
                                  for m, v in env.CompletionSec.items()},
            'target_met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty),
            'total_kwh': env.total_energy_kwh(),
            'assembly_kwh': env.EpisodeEnergyKwh,
            'baseline_kwh': env.baseline_energy_kwh(),
            'smt_kwh': env.SMTEnergyKwh,
            'tou_kwh': {k: round(v, 2) for k, v in bands.items()},
            'cost_vnd': cost,
        }
        results.append(r)
        print(f"[fifo] end={end_h} wall={r['wall_sec']}s makespan={r['makespan_days']:.3f}d "
              f"kwh={r['total_kwh']:.1f} peak={bands['peak']:.1f} cost={cost:,.0f} met={r['target_met']}",
              flush=True)
        json.dump(results, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"saved -> {out_path}")


if __name__ == '__main__':
    main()
