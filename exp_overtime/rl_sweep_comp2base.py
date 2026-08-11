# 컴프레서 기저이관 AAS 기준 학습정책 종료시각 스윕 — fifo_sweep_comp2base.py 와 동일 조건.
# 체크포인트는 인자로 받는다. 요금 관측 3피처 이전에 학습된 정책은 --no-tariff-obs 로 StateDim 19 유지.
import sys, os, json, time, argparse

PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE)
sys.dont_write_bytecode = True

from fifo_sweep_comp2base import (ENDS, QTY, DUE, MAXS, FILES, tou, worktime, batch_log)  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', default='none')   # 'none' = 미학습(랜덤 초기화)
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='rl')
    ap.add_argument('--sampling', action='store_true',
                    help='배포를 argmax 가 아니라 확률 샘플링으로 (학습과 동일 방식)')
    ap.add_argument('--sseed', type=int, default=1)
    ap.add_argument('--events-dir', default=None, help='events.jsonl 저장 경로')
    ap.add_argument('--no-tariff-obs', action='store_true',
                    help='요금 관측 3피처 제외 — StateDim 19 레거시 체크포인트 호환')
    args = ap.parse_args()

    import path_extractor, build, run_trained, torch, random
    for f in FILES:
        path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
    base_cls = run_trained._schedule_env_cls()

    results = []
    for end_h in ENDS:
        t0 = time.time()
        random.seed(1)
        torch.manual_seed(1)
        env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                     env_cls=batch_log(base_cls))
        env.WorkEndTime   = end_h * 3600.0
        env.MaxEpisodeSec = MAXS
        if args.no_tariff_obs:
            env.TariffObs = False
        env.reset()
        agent = build.build_agent(env, checkpoint=(None if args.ckpt=='none' else args.ckpt))
        if hasattr(agent, 'reset_buffer'): agent.reset_buffer()
        agent.train(args.sampling)
        if args.sampling: torch.manual_seed(9000 + args.sseed)
        env.run(agent=agent, max_sec=MAXS)
        makespan = env.env.now
        bands, cost = tou(env, makespan)
        r = {
            'policy': args.label, 'end_hour': end_h, 'wall_sec': round(time.time() - t0, 1),
            'makespan_days': makespan / 86400.0,
            'work_time_h': worktime(env, makespan) / 3600.0,
            'completion_days': {m: (v / 86400.0 if v is not None else None)
                                for m, v in env.CompletionSec.items()},
            'completion_work_h': {m: (worktime(env, v) / 3600.0 if v is not None else None)
                                  for m, v in env.CompletionSec.items()},
            'target_met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty),
            'throughput': dict(env.Throughput),
            'total_kwh': env.total_energy_kwh(),
            'assembly_kwh': env.EpisodeEnergyKwh,
            'baseline_kwh': env.baseline_energy_kwh(),
            'smt_kwh': env.SMTEnergyKwh,
            'tou_kwh': {k: round(v, 2) for k, v in bands.items()},
            'cost_vnd': cost,
        }
        if args.events_dir:
            os.makedirs(args.events_dir, exist_ok=True)
            ep = os.path.join(args.events_dir, f'events_end{end_h:g}.jsonl')
            with open(ep, 'w', encoding='utf-8') as fp:
                for ev in env.events:
                    fp.write(json.dumps(ev, ensure_ascii=False) + os.linesep)
            r['events_file'] = ep
            r['smt_batches'] = getattr(env, 'smt_batches', [])
            r['workers'] = {w: i['worker_count'] for w, i in env.workers.items()}
        results.append(r)
        print(f"[{args.label}] end={end_h} wall={r['wall_sec']}s makespan={r['makespan_days']:.3f}d "
              f"work={r['work_time_h']:.2f}h kwh={r['total_kwh']:.1f} peak={bands['peak']:.1f} "
              f"met={r['target_met']}", flush=True)
        json.dump(results, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"saved -> {args.out}")


if __name__ == '__main__':
    main()
