# 분포의 "뾰족함"이 성능을 어떻게 바꾸나 — logits 온도 스윕 (학습 없음)
#   T→0 : 균등 랜덤 / T=1 : 기본 샘플링 / T→∞ : argmax
#   "RL이 결정해야 하는 건 분포"라면 최적 T 가 중간에 존재해야 한다.
import sys, os, json, statistics as st
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, worktime, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, simulation as sim, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()

TEMP = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, None]     # None = argmax
_T = {'t': 1.0}
orig = sim.PPOAgent.choose

def patched(self, ready_pcs, env):
    kg = env.KnowledgeGraph; nl = list(kg.nodes.keys())
    emb = self.GNNEncoder(NodeFeatures=sim.obs_node_features(kg),
                          GraphTopology=sim.obs_graph_topology(kg))
    re_ = torch.stack([emb[nl.index(pc)] for pc in ready_pcs])
    stt = env.StateVector() if self.StateDim > 0 else None
    logits = self.Actor(ReadyNodeEmbeddings=re_, StateVector=stt)
    t = _T['t']
    if t is None:
        i = int(torch.as_tensor(logits).argmax())
    elif t == 0.0:
        i = int(torch.randint(len(ready_pcs), (1,))[0])
    else:
        i = int(torch.distributions.Categorical(logits=torch.as_tensor(logits) * t).sample())
    return ready_pcs[i]
sim.PPOAgent.choose = patched

def run(pseed, t, qty=180, end_h=20.0):
    _T['t'] = t
    random.seed(1); torch.manual_seed(pseed)
    env = build.build_simulation(target_qty={m: qty for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m: 3 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = end_h*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=None); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(7000 + pseed)
    env.run(agent=ag, max_sec=2592000)
    ms = env.env.now; b, _ = tou(env, ms)
    return ms/86400.0, b['normal'] + b['peak']*(PEAK/NORMAL) + b['night']*(OFF/NORMAL)

print("q180 · 20:00 · 랜덤 초기화 정책 3개 · logits 온도 스윕")
print(f"{'온도':>8s} {'makespan med':>13s} {'범위':>20s} {'가중kWh med':>12s}")
out = []
for t in TEMP:
    rs = [run(s, t) for s in (1, 2, 3)]
    ms = [r[0] for r in rs]; ws = [r[1] for r in rs]
    lbl = 'argmax' if t is None else ('균등(T=0)' if t == 0.0 else f'T={t:g}')
    print(f"{lbl:>8s} {st.median(ms):13.4f} {min(ms):9.4f}~{max(ms):.4f} {st.median(ws):12.1f}")
    out.append({'temp': t, 'makespan': ms, 'wkwh': ws})
json.dump(out, open('exp_overtime/temperature_sweep.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=1)
