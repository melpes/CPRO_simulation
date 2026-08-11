# q180 · 20:00 기준 FIFO / 랜덤초기화 정책 비교 — 정책 공간 변동폭 판정용
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, worktime, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
QTY = {"MODEL_A": 180, "MODEL_B": 180, "MODEL_C": 180}
DUE, MAXS, END = 3, 2592000, 20.0

import path_extractor, build, run_trained, torch, random
for f in FILES:
    path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
base_cls = run_trained._schedule_env_cls()

def one(label, mk_agent, seed):
    t0 = time.time()
    random.seed(1); torch.manual_seed(seed)
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime = END * 3600.0; env.MaxEpisodeSec = MAXS; env.TariffObs = False
    env.reset()
    agent = mk_agent(env)
    if agent is not None and hasattr(agent, 'reset_buffer'):
        agent.reset_buffer()
    env.run(agent=agent, max_sec=MAXS)
    ms = env.env.now
    b, _ = tou(env, ms)
    w = b['normal'] + b['peak']*(PEAK/NORMAL) + b['night']*(OFF/NORMAL)
    r = {'label': label, 'seed': seed, 'wall': round(time.time()-t0,1),
         'makespan_days': ms/86400.0, 'work_time_h': worktime(env, ms)/3600.0,
         'weighted_kwh': w, 'total_kwh': env.total_energy_kwh(),
         'met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty)}
    print(f"[{label}] seed={seed} wall={r['wall']}s makespan={r['makespan_days']:.4f}d "
          f"work={r['work_time_h']:.2f}h wkwh={w:.1f} met={r['met']}", flush=True)
    return r

out = []
out.append(one('FIFO', lambda e: None, 1))
for s in (11, 22, 33):
    out.append(one('RANDOM_INIT', lambda e: build.build_agent(e, checkpoint=None), s))
json.dump(out, open('exp_overtime/baseline_q180.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
print('saved')
