# 정책 파라미터 민감도 프로브 — "f 가중치를 흔들면 리턴이 유의미하게 변하는가"
# ES/ARS(파라미터 공간 탐색)로 갈 수 있는지 판정하는 사전 검증. 학습 없음, 평가만.
#   흔드는 방식: 레이어별 상대 스케일  theta' = theta + sigma * std(theta_layer) * eps
#   (레이어마다 파라미터 크기가 달라 절대 노이즈는 스케일 왜곡을 낳음)
import sys, os, json, time, argparse

PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE)
sys.dont_write_bytecode = True

from fifo_sweep_comp2base import tou, worktime, batch_log, FILES  # noqa: E402

QTY  = {"MODEL_A": 180, "MODEL_B": 180, "MODEL_C": 180}   # q180
DUE  = 3
MAXS = 2592000
END_HOUR = 20.0
ENV_SEED = 1                                              # 환경 고정 — 정책 차이만 보이게

# Normal 등가 가중치 (AAS ElectricityTariffBands)
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0


def perturb(agent, sigma, gen):
    """레이어별 std에 비례한 가우시안 노이즈를 파라미터에 더한다."""
    import torch
    if sigma <= 0:
        return
    with torch.no_grad():
        for p in agent.parameters():
            if p.numel() < 2:
                continue
            scale = float(p.std())
            if scale <= 0:
                continue
            p.add_(torch.randn(p.shape, generator=gen) * (sigma * scale))


def run_one(build, base_cls, ckpt, sigma, rep, no_tariff_obs):
    import torch, random
    t0 = time.time()
    random.seed(ENV_SEED)
    torch.manual_seed(ENV_SEED)
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime   = END_HOUR * 3600.0
    env.MaxEpisodeSec = MAXS
    if no_tariff_obs:
        env.TariffObs = False
    env.reset()
    agent = build.build_agent(env, checkpoint=ckpt)
    gen = torch.Generator().manual_seed(10_000 + int(sigma * 1000) * 100 + rep)
    perturb(agent, sigma, gen)
    env.run(agent=agent, max_sec=MAXS)
    makespan = env.env.now
    bands, _ = tou(env, makespan)
    w = bands['normal'] + bands['peak'] * (PEAK / NORMAL) + bands['night'] * (OFF / NORMAL)
    return {
        'sigma': sigma, 'rep': rep, 'wall_sec': round(time.time() - t0, 1),
        'makespan_days': makespan / 86400.0,
        'work_time_h': worktime(env, makespan) / 3600.0,
        'total_kwh': env.total_energy_kwh(),
        'weighted_kwh': w,
        'peak_kwh': bands['peak'],
        'target_met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty),
        'throughput': dict(env.Throughput),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sigmas', default='0.01,0.05,0.1')
    ap.add_argument('--reps', type=int, default=5)
    ap.add_argument('--no-tariff-obs', action='store_true')
    args = ap.parse_args()

    import path_extractor, build, run_trained
    for f in FILES:
        path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
    base_cls = run_trained._schedule_env_cls()

    combos = [(0.0, 0)] + [(float(s), r) for s in args.sigmas.split(',')
                           for r in range(args.reps)]
    results = []
    for sigma, rep in combos:
        r = run_one(build, base_cls, args.ckpt, sigma, rep, args.no_tariff_obs)
        results.append(r)
        print(f"[probe] sigma={sigma:.3f} rep={rep} wall={r['wall_sec']}s "
              f"makespan={r['makespan_days']:.4f}d work={r['work_time_h']:.2f}h "
              f"wkwh={r['weighted_kwh']:.1f} met={r['target_met']}", flush=True)
        json.dump(results, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"saved -> {args.out}")


if __name__ == '__main__':
    main()
