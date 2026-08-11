# 보상 항별 z-정규화 + gamma/lambda/entropy 수정 프로브 (본 코드 무수정, 래퍼로만 적용)
#   ① 항별 정규화 : phi = sum( RW_k * term_k / std_k )  — std_k 는 직전 에피소드의 스텝 간 표준편차
#      (mean 은 phi 차분에서 상쇄되므로 std 만 쓴다. std~0 인 항은 상수이므로 원값 유지)
#   ② Gamma=1 / GaeLambda=1 : 30,000 스텝 에피소드에서 0.99 는 유효지평 100 스텝 → 최종 성능 미전파
#   ③ EntropyCoef 축소 : advantage~0 일 때 엔트로피 항만 남아 정책이 균등분포로 되밀리는 것 방지
import sys, os, json, time, argparse, statistics as st

PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE)
sys.dont_write_bytecode = True

from fifo_sweep_comp2base import tou, worktime, FILES  # noqa: E402

QTY  = {"MODEL_A": 180, "MODEL_B": 180, "MODEL_C": 180}
DUE, MAXS, END_HOUR = 3, 2592000, 20.0
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0


def make_env_cls(base_cls, znorm: bool):
    """이벤트/SMT 기록 + (옵션) 보상 항별 z-정규화."""
    class _E(base_cls):
        znorm_std = {}      # 클래스 변수 — 에피소드 간 유지
        collect = {}
        term_log = []       # 에피소드별 최종 항 값

        def reset(self):
            cls = type(self)
            if znorm and cls.collect:                       # 직전 ep 수집분으로 std 갱신
                for k, vs in cls.collect.items():
                    if len(vs) > 1:
                        s = st.pstdev(vs)
                        cls.znorm_std[k] = s if s > 1e-9 else None
            super().reset()
            self.smt_batches = []
            cls.collect = {}

        def smt_record(self, line_id, equipment, code, t_end, array_cycle, array_energy):
            super().smt_record(line_id, equipment, code, t_end, array_cycle, array_energy)
            self.smt_batches.append({'start_sec': float(t_end) - float(array_cycle),
                                     'end_sec': float(t_end), 'kwh': float(array_energy)})

        def potential(self):
            for ws in self.workers:
                self._flush_idle(ws, self.env.now)
            terms = self.reward_terms()
            if not znorm:
                return sum(terms.values())
            cls = type(self)
            total = 0.0
            for k, v in terms.items():
                cls.collect.setdefault(k, []).append(v)
                s = cls.znorm_std.get(k)
                total += (v / s) if s else v                 # std 미확보/상수항 → 원값
            return total
    return _E


def evaluate(build, env_cls, agent_state, ckpt, no_tariff_obs):
    ckpt = None if (ckpt in (None, 'none')) else ckpt
    """argmax 결정적 평가 — 학습이 실제 배포 성능을 개선하는지 본다."""
    import torch, random, copy
    random.seed(1)
    torch.manual_seed(1)
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=env_cls)
    env.WorkEndTime, env.MaxEpisodeSec = END_HOUR * 3600.0, MAXS
    if no_tariff_obs:
        env.TariffObs = False
    env.reset()
    agent = build.build_agent(env, checkpoint=ckpt)
    if agent_state is not None:
        agent.load_state_dict(agent_state)
    agent.eval()
    if hasattr(agent, 'reset_buffer'):
        agent.reset_buffer()
    env.run(agent=agent, max_sec=MAXS)
    ms = env.env.now
    b, _ = tou(env, ms)
    w = b['normal'] + b['peak'] * (PEAK / NORMAL) + b['night'] * (OFF / NORMAL)
    return {'makespan_days': ms / 86400.0, 'work_time_h': worktime(env, ms) / 3600.0,
            'weighted_kwh': w, 'peak_kwh': b['peak'], 'total_kwh': env.total_energy_kwh()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', default='none')   # 'none' = 랜덤 초기화부터
    ap.add_argument('--out', required=True)
    ap.add_argument('--episodes', type=int, default=5)
    ap.add_argument('--znorm', action='store_true')
    ap.add_argument('--gamma', type=float, default=1.0)
    ap.add_argument('--lam', type=float, default=1.0)
    ap.add_argument('--ent', type=float, default=0.001)
    ap.add_argument('--no-tariff-obs', action='store_true')
    args = ap.parse_args()

    import path_extractor, build, run_trained, torch, random
    for f in FILES:
        path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
    env_cls = make_env_cls(run_trained._schedule_env_cls(), args.znorm)

    random.seed(1)
    torch.manual_seed(1)
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=env_cls)
    env.WorkEndTime, env.MaxEpisodeSec = END_HOUR * 3600.0, MAXS
    if args.no_tariff_obs:
        env.TariffObs = False
    env.reset()
    agent = build.build_agent(env, checkpoint=(None if args.ckpt=='none' else args.ckpt))
    agent.Gamma, agent.GaeLambda, agent.EntropyCoef = args.gamma, args.lam, args.ent
    print(f"[cfg] znorm={args.znorm} gamma={agent.Gamma} lam={agent.GaeLambda} "
          f"ent={agent.EntropyCoef} clip={agent.ClipEpsilon}", flush=True)

    rows = []
    ev0 = evaluate(build, env_cls, None, args.ckpt, args.no_tariff_obs)
    print(f"[eval ep-1(초기)] makespan={ev0['makespan_days']:.4f}d "
          f"work={ev0['work_time_h']:.2f}h wkwh={ev0['weighted_kwh']:.1f}", flush=True)
    rows.append({'episode': -1, 'eval': ev0})

    for ep in range(args.episodes):
        t0 = time.time()
        agent.train()
        agent.CurrentEpisode = ep
        agent.reset_buffer()
        env.run(agent=agent, max_sec=MAXS)
        R = env.episode_reward()
        terms = env.reward_terms()
        n = len(agent.buf)
        m = agent.learn(R, env.KnowledgeGraph)
        ev = evaluate(build, env_cls, agent.state_dict(), args.ckpt, args.no_tariff_obs)
        row = {'episode': ep, 'R': R, 'decisions': n, 'wall': round(time.time() - t0, 1),
               'train_makespan_days': env.env.now / 86400.0,
               'terms': {k: float(v) for k, v in terms.items()},
               'metrics': {k: (float(v) if isinstance(v, (int, float)) else v)
                           for k, v in (m or {}).items()},
               'znorm_std': {k: (float(v) if v else None)
                             for k, v in type(env).znorm_std.items()},
               'eval': ev}
        rows.append(row)
        print(f"[ep {ep}] R={R:+.5f} dec={n} wall={row['wall']}s "
              f"| train_ms={row['train_makespan_days']:.4f}d "
              f"| EVAL makespan={ev['makespan_days']:.4f}d work={ev['work_time_h']:.2f}h "
              f"wkwh={ev['weighted_kwh']:.1f} peak={ev['peak_kwh']:.1f} "
              f"| kl={m.get('stability/approx_kl', 0):.4f} "
              f"clip={m.get('stability/clip_fraction', 0):.3f} "
              f"ent={m.get('exploration/entropy', 0):.3f} "
              f"evar={m.get('critic/explained_variance', float('nan')):.3f}", flush=True)
        json.dump(rows, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"saved -> {args.out}")


if __name__ == '__main__':
    main()
