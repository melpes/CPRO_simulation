# 초과근무 길이 스윕 — 완료시간·TOU 가중 전기비용 트레이드오프 드라이버
# 시뮬 이벤트(조립·SMT)와 기저전력을 시간대(피크/보통/심야)별로 적분해 VND 비용 산출.
import sys, os, json, time, argparse

PACKAGE = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package"
sys.path.insert(0, PACKAGE)
sys.dont_write_bytecode = True

# 요율 (결정 1279/QĐ-BCT, 6~22kV 미만, VAT 제외, VND/kWh) — ledger L-tariff-1279-current
TARIFF = {'normal': 1899.0, 'peak': 3508.0, 'night': 1234.0}
# 시간대 (결정 963/QĐ-BCT): 심야 00~06, 피크 17:30~22:30 (월~토; 시뮬은 요일 미구분 → 전일 평일 가정)
NIGHT_END, PEAK_START, PEAK_END = 6 * 3600.0, 17.5 * 3600.0, 22.5 * 3600.0
DAY = 86400.0

CKPT = os.path.join(PACKAGE, 'result', 'runs', 'q180s__q540val-300ep', 'agent_mod.pt')
PO = None          # main()에서 --qty/--due로 구성
EXTRA_OVERRIDES = {}  # main()에서 --maxsec로 구성


def band_energy(a, b, power_kw):
    """[a,b)초 동안 power_kw 정출력의 시간대별 kWh."""
    out = {'normal': 0.0, 'peak': 0.0, 'night': 0.0}
    t = a
    while t < b - 1e-9:
        d = t % DAY
        if d < NIGHT_END:
            band, nxt = 'night', t + (NIGHT_END - d)
        elif d < PEAK_START:
            band, nxt = 'normal', t + (PEAK_START - d)
        elif d < PEAK_END:
            band, nxt = 'peak', t + (PEAK_END - d)
        else:
            band, nxt = 'normal', t + (DAY - d)
        seg_end = min(b, nxt)
        out[band] += power_kw * (seg_end - t) / 3600.0
        t = seg_end
    return out


def add(acc, part):
    for k, v in part.items():
        acc[k] = acc.get(k, 0.0) + v
    return acc


def tou_breakdown(env, summary):
    """기저 + 조립 이벤트 + SMT 이벤트를 시간대별로 적분."""
    tou = {'normal': 0.0, 'peak': 0.0, 'night': 0.0}
    makespan = summary['makespan_sec']
    # 기저전력: 근무창(시작~점심, 점심끝~종업) × 일수, makespan에서 절단
    base_kw = env.DefaultProcessConsumedPowerKw
    day0 = 0
    while day0 < makespan:
        for w0, w1 in ((env.WorkStartTime, env.break_start_sec),
                       (env.break_end_sec, env.WorkEndTime)):
            a, b = day0 + w0, min(day0 + w1, makespan)
            if b > a:
                add(tou, band_energy(a, b, base_kw))
        day0 += DAY
    baseline_kwh = sum(tou.values())
    # 조립 이벤트: 공정 정격전력을 [start,end]에 균등 부과 (시뮬 계식과 동일 총량)
    assembly = {'normal': 0.0, 'peak': 0.0, 'night': 0.0}
    for ev in env.events:
        node = env.KnowledgeGraph.nodes[ev['process_code']]
        if node.RatedPowerKw:
            add(assembly, band_energy(ev['start_sec'], ev['end_sec'], node.RatedPowerKw))
    # SMT: smt_events는 시각화용(파이프라인 중첩 무시)이라 에너지 총량이 과대 —
    # 배치당 실제 적립 kWh(smt_batches)를 배치 시간창에 균등 부과
    smt = {'normal': 0.0, 'peak': 0.0, 'night': 0.0}
    for b in getattr(env, 'smt_batches', []):
        dur = b['end_sec'] - b['start_sec']
        if dur > 0 and b['kwh'] > 0:
            add(smt, band_energy(b['start_sec'], b['end_sec'], b['kwh'] / (dur / 3600.0)))
    add(tou, assembly)
    add(tou, smt)
    checks = {'baseline_kwh': (baseline_kwh, summary['IdleEnergyKwh']),
              'assembly_kwh': (sum(assembly.values()), summary['ActivePremiumKwh']),
              'smt_kwh':      (sum(smt.values()), summary['SMTEnergyKwh'])}
    cost = sum(tou[b] * TARIFF[b] for b in tou)
    return tou, cost, checks


def _batch_log_wrap(cls):
    class _BatchLogEnv(cls):
        def reset(self):
            super().reset()
            self.smt_batches = []

        def smt_record(self, line_id, equipment, code, t_end, array_cycle, array_energy):
            super().smt_record(line_id, equipment, code, t_end, array_cycle, array_energy)
            self.smt_batches.append({'start_sec': float(t_end) - float(array_cycle),
                                     'end_sec': float(t_end), 'kwh': float(array_energy)})
    return _BatchLogEnv


def run_one(model, end_hour, seed):
    overrides = dict(EXTRA_OVERRIDES)
    if end_hour != 18.0:
        overrides['WorkEndTime'] = end_hour
    t0 = time.time()
    env, summary = model.simulate(target_qty=model._resolve_po(PO)[0],
                                  due_day=model._resolve_po(PO)[1],
                                  overrides=overrides, seed=seed,
                                  env_wrap=_batch_log_wrap)
    wall = time.time() - t0
    tou, cost_vnd, checks = tou_breakdown(env, summary)
    tard = 0.0
    completion = {}
    for m, due in env.DueDay.items():
        done = summary['CompletionSec'].get(m)
        completion[m] = done
        tard += max(0.0, ((done if done is not None else summary['makespan_sec']) - due)) / DAY
    return {
        'end_hour': end_hour, 'seed': seed, 'wall_sec': round(wall, 1),
        'makespan_days': summary['makespan_sec'] / DAY,
        'completion_days': {m: (v / DAY if v is not None else None) for m, v in completion.items()},
        'tardiness_days_sum': tard,
        'target_met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty),
        'total_kwh': summary['EpisodeEnergyKwh'],
        'tou_kwh': {k: round(v, 2) for k, v in tou.items()},
        'cost_vnd': cost_vnd,
        'energy_check': {k: (round(a, 2), round(b, 2)) for k, (a, b) in checks.items()},
    }


def main():
    global PO, EXTRA_OVERRIDES
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--ends', default='18.0,19.0,20.0,21.0,22.5')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--qty', type=int, default=60)
    ap.add_argument('--due', type=int, default=3)
    ap.add_argument('--maxsec', type=int, default=None)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    PO = {m: {"qty": args.qty, "due_day": args.due}
          for m in ("MODEL_A", "MODEL_B", "MODEL_C")}
    if args.maxsec:
        EXTRA_OVERRIDES = {'MaxEpisodeSec': args.maxsec}

    from run_trained import TrainedModel
    model = TrainedModel(checkpoint=CKPT)

    # 오버라이드 배선 확인 (실행 전 플럼빙 검증)
    probe = model._build.build_simulation(MaxEpisodes=1)
    model._apply_overrides(probe, {'WorkEndTime': 22.5})
    assert probe.WorkEndTime == 22.5 * 3600, "WorkEndTime override not applied"
    print(f"[plumbing] WorkEndTime override OK; MaxEpisodeSec={probe.MaxEpisodeSec}")

    if args.smoke:
        combos = [(18.0, 0)]
    else:
        ends = [float(x) for x in args.ends.split(',')]
        seeds = [int(x) for x in args.seeds.split(',')]
        combos = [(e, s) for e in ends for s in seeds]

    results = []
    for end_hour, seed in combos:
        r = run_one(model, end_hour, seed)
        results.append(r)
        print(f"[run] end={end_hour} seed={seed} wall={r['wall_sec']}s "
              f"makespan={r['makespan_days']:.3f}d tard={r['tardiness_days_sum']:.3f}d "
              f"kwh={r['total_kwh']:.1f} cost={r['cost_vnd']:,.0f}VND met={r['target_met']} "
              f"check={r['energy_check']}")
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"saved -> {args.out}")


if __name__ == '__main__':
    main()
