# 재배분 목적지 확장 — Aging·Packaging·OQC 포함. 경향 확인용.
#   Aging 은 UnitsPerWorker=45 라 인원 1명당 캐파 +45.
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
CK = 'result/runs/q180s__compbase-300ep/agent_last.pt'
SRC = 'WWM_SemiAssemblyLine'
L = ['WWM_FwInputLine','WWM_LensHolderLine','WWM_FocusLine','WWM_SetAssemblyLine',
     'WWM_InspectionLine','WWM_AgingLine','WWM_PackagingLine','WWM_OqcLine']
#          F  L Fo  S  I  A  P  O
GRID = [('none(기준)',        None),
        ('F7-L1-Fo1-I1(기존최선)',[7,1,1,0,1,0,0,0]),
        ('A10 에이징몰빵',      [0,0,0,0,0,10,0,0]),
        ('A5-F5',             [5,0,0,0,0,5,0,0]),
        ('A5-I5',             [0,0,0,0,5,5,0,0]),
        ('P10 포장몰빵',        [0,0,0,0,0,0,10,0]),
        ('I5-P5',             [0,0,0,0,5,0,5,0]),
        ('F4-I3-P3',          [4,0,0,0,3,0,3,0]),
        ('A3-F3-I2-P2',       [3,0,0,0,2,3,2,0]),
        ('O10 OQC몰빵',        [0,0,0,0,0,0,0,10]),
        ('넓게 F2L2Fo2I2P2',   [2,2,2,0,2,0,2,0])]

def sw_cls(base, mv):
    if not mv: return base
    moves = {l: k for l, k in zip(L, mv) if k}
    class _E(base):
        def reset(self):
            super().reset(); self.sw_fired = None
            self.env.process(self._w())
        def _w(self):
            while True:
                yield self.env.timeout(30.0)
                if self.sw_fired is not None: return
                if self.in_progress.get(SRC,0)==0 and (self.env.now-self.last_active.get(SRC,0.0))>=600.0:
                    s = self.workers[SRC]
                    for t_, k in moves.items():
                        m = min(k, s['worker_count']-1)
                        if m>0: s['worker_count']-=m; self.workers[t_]['worker_count']+=m
                    self.sw_fired=float(self.env.now); return
    return _E

out=[]
print("q540 · due4 · 18:00 · 샘플링 · 목적지 확장 (Aging·Packaging·OQC 포함)")
print(f"{'조합':24s} {'makespan':>10s} {'가중kWh':>10s} {'Aging캐파':>9s}")
for name, mv in GRID:
    t0=time.time(); random.seed(1); torch.manual_seed(1)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=sw_cls(batch_log(base_cls), mv))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(9000); env.run(agent=ag, max_sec=2592000)
    h = env.env.now/3600.0; b,_ = tou(env, env.env.now)
    w = b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    ai = env.workers['WWM_AgingLine']
    cap = ai['worker_count']*ai['UnitsPerWorker']
    out.append({'combo':name,'makespan_h':h,'wkwh':w,'aging_cap':cap})
    print(f"{name:24s} {h:9.2f}h {w:10.1f} {cap:8d}  ({time.time()-t0:.0f}s)", flush=True)
    json.dump(out, open('exp_overtime/realloc_grid2.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
ms=[r['makespan_h'] for r in out]
print(f"\n범위 {min(ms):.2f}~{max(ms):.2f}h  폭 {(max(ms)-min(ms))/min(ms)*100:.2f}%")
print("최선:", min(out,key=lambda r:r['makespan_h'])['combo'])
