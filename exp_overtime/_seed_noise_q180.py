# 노이즈 바닥 측정 — 같은 정책(argmax 결정적), 환경 시드만 변경.
# 정책 간 차이(파라미터 프로브)와 비교해 학습 가능한 SNR이 있는지 판정한다.
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, worktime, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
QTY = {"MODEL_A": 180, "MODEL_B": 180, "MODEL_C": 180}
DUE, MAXS, END = 3, 2592000, 20.0
CKPT = 'result/runs/q180s__q540val-300ep/agent_mod.pt'

import path_extractor, build, run_trained, torch, random
for f in FILES:
    path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
base_cls = run_trained._schedule_env_cls()

out = []
for env_seed in (1, 2, 3, 4, 5, 6, 7):
    t0 = time.time()
    random.seed(env_seed); torch.manual_seed(1)          # 환경만 바뀜, 정책 고정
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime = END * 3600.0; env.MaxEpisodeSec = MAXS; env.TariffObs = False
    env.reset()
    agent = build.build_agent(env, checkpoint=CKPT)
    if hasattr(agent, 'reset_buffer'): agent.reset_buffer()
    env.run(agent=agent, max_sec=MAXS)
    ms = env.env.now
    b, _ = tou(env, ms)
    w = b['normal'] + b['peak']*(PEAK/NORMAL) + b['night']*(OFF/NORMAL)
    r = {'env_seed': env_seed, 'wall': round(time.time()-t0,1),
         'makespan_days': ms/86400.0, 'work_time_h': worktime(env, ms)/3600.0,
         'weighted_kwh': w, 'peak_kwh': b['peak'], 'total_kwh': env.total_energy_kwh()}
    out.append(r)
    print(f"[seed] {env_seed} wall={r['wall']}s makespan={r['makespan_days']:.4f}d "
          f"work={r['work_time_h']:.2f}h wkwh={w:.1f} peak={b['peak']:.1f}", flush=True)
json.dump(out, open('exp_overtime/seed_noise_q180.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)

import statistics as st
for k in ('makespan_days','work_time_h','weighted_kwh','peak_kwh'):
    v=[r[k] for r in out]
    print(f"{k:15s} mean={st.mean(v):10.4f}  std={st.pstdev(v):9.5f}  "
          f"cv={st.pstdev(v)/st.mean(v)*100:6.3f}%  range=[{min(v):.4f}, {max(v):.4f}]")
