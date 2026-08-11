# GNN 노드 피처를 동적·정규화로 바꿨을 때 선택이 달라지는가 (학습 없음, 평가만)
#   현행 3피처: CycleTimeSec(raw 10~10800) / DefectRate(전 노드 0) / RatedPowerKw
#     → 셋 다 정적이라 GNN 임베딩이 에피소드 내내 불변 = 후보 순위가 공정코드에만 의존
#   시험 3피처(개수 동일 → NodeFeatureDim 불변, build_agent 수정 불필요):
#     ① log1p(CycleTimeSec) 정규화   ② log1p(DepWaitSec) 정규화   ③ 소속 라인 현재 혼잡도(동적)
#   학습(learn)은 호출하지 않는다 — 임베딩을 재계산하는 구조라 동적 피처는 rollout/update 불일치를
#   일으킨다. 그 수정은 코드 변경이 필요하므로 여기서는 "선택이 달라지는가"만 본다.
import sys, os, json, time, math, argparse

PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE)
sys.dont_write_bytecode = True

from fifo_sweep_comp2base import tou, worktime, batch_log, FILES  # noqa: E402

QTY = {"MODEL_A": 180, "MODEL_B": 180, "MODEL_C": 180}
DUE, MAXS, END = 3, 2592000, 20.0
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0

_CUR = {'env': None}          # obs_node_features 가 kg 만 받으므로 현재 env 를 여기로 전달


def install_dynamic_features(simulation):
    """simulation.obs_node_features 를 동적·정규화 버전으로 교체 (파일 수정 없음)."""
    import torch
    orig = simulation.obs_node_features
    cache = {}

    def dyn(kg):
        env = _CUR['env']
        if env is None:
            return orig(kg)
        key = id(kg)
        if key not in cache:                       # 정적 항목·정규화 상수는 1회 계산
            ct   = {c: float(n.CycleTimeSec) for c, n in kg.nodes.items()}
            dw   = {c: float(n.DepWaitSec or 0.0) for c, n in kg.nodes.items()}
            ctm  = math.log1p(max(ct.values())) or 1.0
            dwm  = math.log1p(max(dw.values())) or 1.0
            ws_of = {c: env._workstation_of(c) for c in kg.nodes}
            cache[key] = ({c: math.log1p(v) / ctm for c, v in ct.items()},
                          {c: math.log1p(v) / dwm for c, v in dw.items()},
                          ws_of)
        ctn, dwn, ws_of = cache[key]
        rows = []
        for c in kg.nodes:
            ws = ws_of[c]
            info = env.workers.get(ws)
            busy = (env.in_progress.get(ws, 0) / info['worker_count']) if info else 0.0
            rows.append([ctn[c], dwn[c], busy])
        return torch.tensor(rows, dtype=torch.float)

    simulation.obs_node_features = dyn
    return orig


def run_one(build, base_cls, policy_seed, dynamic):
    import torch, random
    t0 = time.time()
    random.seed(1)
    torch.manual_seed(policy_seed)
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = END * 3600.0, MAXS, False
    env.reset()
    _CUR['env'] = env if dynamic else None
    agent = build.build_agent(env, checkpoint=None)
    if hasattr(agent, 'reset_buffer'):
        agent.reset_buffer()
    env.run(agent=agent, max_sec=MAXS)
    ms = env.env.now
    b, _ = tou(env, ms)
    w = b['normal'] + b['peak'] * (PEAK / NORMAL) + b['night'] * (OFF / NORMAL)
    return {'policy_seed': policy_seed, 'dynamic': dynamic, 'wall': round(time.time() - t0, 1),
            'makespan_days': ms / 86400.0, 'work_time_h': worktime(env, ms) / 3600.0,
            'weighted_kwh': w, 'peak_kwh': b['peak'], 'total_kwh': env.total_energy_kwh(),
            'met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='exp_overtime/dynfeat_probe.json')
    ap.add_argument('--seeds', type=int, default=12)
    args = ap.parse_args()

    import path_extractor, build, run_trained, simulation
    for f in FILES:
        path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
    base_cls = run_trained._schedule_env_cls()
    install_dynamic_features(simulation)

    out = []
    for dynamic in (False, True):
        tag = 'DYN ' if dynamic else 'STAT'
        for s in range(1, args.seeds + 1):
            r = run_one(build, base_cls, s, dynamic)
            out.append(r)
            print(f"[{tag}] seed={s:2d} makespan={r['makespan_days']:.4f}d "
                  f"work={r['work_time_h']:.2f}h wkwh={r['weighted_kwh']:.1f} met={r['met']}",
                  flush=True)
            json.dump(out, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    import statistics as stx
    print()
    for dynamic in (False, True):
        g = [r for r in out if r['dynamic'] is dynamic]
        for k in ('makespan_days', 'work_time_h', 'weighted_kwh'):
            v = [r[k] for r in g]
            print(f"{'동적' if dynamic else '정적'} {k:14s} min={min(v):9.4f} "
                  f"med={stx.median(v):9.4f} max={max(v):9.4f}")
    print(f"saved -> {args.out}")


if __name__ == '__main__':
    main()
