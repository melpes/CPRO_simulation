# 재배분 재측정 — Resource capacity 까지 조정 (util/exp_run.py 의 _sw_realloc 원본 로직)
#   이전 측정은 worker_count 딕셔너리만 바꿔 실제 처리능력이 안 변했음 → 전부 무효였다.
import sys, os, json, time, statistics as st
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

def sw_cls(base, mv, trig=600.0):
    moves = {l:k for l,k in zip(L,mv) if k}
    class _E(base):
        def reset(self):
            if not hasattr(self, '_w0'):
                self._w0 = {w:i['worker_count'] for w,i in self.workers.items()}
            for w,c in self._w0.items(): self.workers[w]['worker_count'] = c
            super().reset()
            self.sw_fired = None; self._src_jobs = 0; self._sw_done = False
            self.env.process(self._mon())
        def _run_job(self, ws, job, req):
            yield from super()._run_job(ws, job, req)
            if ws == SRC: self._src_jobs += 1
        def _mon(self):
            acc = 0.0
            while not self._sw_done:
                yield self.env.timeout(30.0)
                if not self._is_work_time(): continue
                idle = (self._src_jobs > 0 and self.in_progress.get(SRC,0)==0
                        and not self._pending[SRC])
                acc = acc + 30.0 if idle else 0.0
                if acc >= trig: self._fire()
        def _fire(self):
            now = self.env.now
            for ws in [SRC, *moves]: self._flush_idle(ws, now)
            for ws, n in moves.items():
                self.workers[ws]['worker_count'] += n
                res = self.worker_resources[ws]
                res._capacity += n * self.workers[ws].get('UnitsPerWorker', 1)
                res._trigger_put(None)
                self._wake_dispatcher(ws)
            moved = sum(moves.values())
            self.workers[SRC]['worker_count'] -= moved
            self.worker_resources[SRC]._capacity -= moved * self.workers[SRC].get('UnitsPerWorker',1)
            self._sw_done = True; self.sw_fired = float(now)
    return _E

#          F  L Fo  S  I  A  P  O
CASES = [('none',            None),
         ('F4-L1-Fo1-S1-I2', [4,1,1,1,2,0,0,0]),   # 기존 argmax 1위
         ('F6',              [6,0,0,0,0,0,0,0]),
         ('F10 몰빵',         [10,0,0,0,0,0,0,0]),
         ('I10 몰빵',         [0,0,0,0,10,0,0,0]),
         ('A10 몰빵',         [0,0,0,0,0,10,0,0])]
SEEDS = [9000, 9001, 9002]

def run(mv, sseed):
    random.seed(1); torch.manual_seed(1)
    cls = batch_log(base_cls) if mv is None else sw_cls(batch_log(base_cls), mv)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')}, env_cls=cls)
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(sseed); env.run(agent=ag, max_sec=2592000)
    h=env.env.now/3600.0; b,_=tou(env, env.env.now)
    w=b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    return h, w, getattr(env,'sw_fired',None), env.worker_resources['WWM_FwInputLine']._capacity

out=[]
print("q540 · due4 · 18:00 · 샘플링 — Resource capacity 조정 반영")
print(f"{'조합':18s} {'makespan 중앙':>13s} {'범위':>18s} {'가중kWh':>10s} {'발동':>8s} {'Fw cap':>7s}")
for name, mv in CASES:
    hs=[]; ws_=[]; fired=None; cap=None
    for s in SEEDS:
        h,w,f,c = run(mv, s); hs.append(h); ws_.append(w); fired=f; cap=c
    out.append({'combo':name,'makespan':hs,'wkwh':ws_,'fired_h':(fired/3600 if fired else None),'fw_cap':cap})
    print(f"{name:18s} {st.median(hs):12.2f}h {min(hs):8.2f}~{max(hs):.2f} {st.median(ws_):10.1f} "
          f"{(f'{fired/3600:.2f}h' if fired else '-'):>8s} {cap:6d}", flush=True)
    json.dump(out, open('exp_overtime/realloc_fixed.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
meds=[st.median(r['makespan']) for r in out]
noise=max((max(r['makespan'])-min(r['makespan']))/min(r['makespan'])*100 for r in out)
print(f"\n조합 간 폭 {(max(meds)-min(meds))/min(meds)*100:.2f}%  vs  시드 노이즈 최대 {noise:.2f}%")
print("최선:", min(out,key=lambda r:st.median(r['makespan']))['combo'])
