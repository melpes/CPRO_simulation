# 결정적 좋은 규칙 vs 확률 샘플링 — q540 에서도 "분산 자체가 이득"인지 판정
import sys, os, json, random as pyrandom, statistics as st
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, worktime, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
CKPT = 'result/runs/q180s__q540val-300ep/agent_mod.pt'
ENDS = [18.0, 19.0, 20.0]

class Rule:
    def __init__(self, fn, seed=0): self.fn, self.rng = fn, pyrandom.Random(seed)
    def choose(self, pcs, env): return self.fn(list(pcs), env, self.rng)

def idle(e, c):
    w = e._workstation_of(c); return e.env.now - e.last_active.get(w, 0.0)
def r_idle(p, e, r):  return max(p, key=lambda c: (idle(e, c), r.random()))   # 결정적 최선 규칙
def r_rnd(p, e, r):   return r.choice(p)                                     # 균등 랜덤

def run(qty, end_h, mode, seed=0):
    random.seed(1); torch.manual_seed(1)
    env = build.build_simulation(target_qty={m: qty for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m: (3 if qty <= 180 else 5) for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = end_h*3600.0, 2592000, False
    env.reset()
    if mode == 'idle':      ag = Rule(r_idle, seed)
    elif mode == 'rnd':     ag = Rule(r_rnd, seed)
    elif mode == 'fifo':    ag = None
    else:
        ag = build.build_agent(env, checkpoint=CKPT); ag.reset_buffer()
        ag.train(mode == 'samp')
        if mode == 'samp': torch.manual_seed(9000+seed)
    env.run(agent=ag, max_sec=2592000)
    ms = env.env.now; b, _ = tou(env, ms)
    w = b['normal'] + b['peak']*(PEAK/NORMAL) + b['night']*(OFF/NORMAL)
    return ms/86400.0, worktime(env, ms)/3600.0, w

for qty, lbl in ((540, 'q540'),):
    print(f"=== {lbl} (모델당 {qty}) ===")
    print(f"{'종료':>5s} {'FIFO':>9s} {'[상황]유휴':>10s} {'랜덤균등med':>11s} {'정책argmax':>10s} {'정책샘플med':>11s}")
    out = []
    for e in ENDS:
        f_ = run(qty, e, 'fifo')[0]
        i_ = run(qty, e, 'idle')[0]
        rr = [run(qty, e, 'rnd', s)[0] for s in range(3)]
        a_ = run(qty, e, 'argmax')[0]
        ss = [run(qty, e, 'samp', s)[0] for s in range(3)]
        print(f"{e:5.1f} {f_:9.3f} {i_:10.3f} {st.median(rr):11.3f} {a_:10.3f} {st.median(ss):11.3f}")
        out.append({'end': e, 'fifo': f_, 'idle': i_, 'rnd': rr, 'argmax': a_, 'samp': ss})
    json.dump(out, open('exp_overtime/rule_vs_sampling_q540.json','w',encoding='utf-8'),
              ensure_ascii=False, indent=1)
