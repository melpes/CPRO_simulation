# 정책 관측 교란 분리 — FIFO(관측 미사용)로 재배분하면 인원 증가가 정상 작동하는가
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
SRC='WWM_SemiAssemblyLine'
LINES={'FwInput':'WWM_FwInputLine','Inspection':'WWM_InspectionLine',
       'SetAssembly':'WWM_SetAssemblyLine','LensHolder':'WWM_LensHolderLine',
       'Focus':'WWM_FocusLine','Aging':'WWM_AgingLine'}

def sw_cls(base, moves):
    class _E(base):
        def reset(self):
            if not hasattr(self,'_w0'): self._w0={w:i['worker_count'] for w,i in self.workers.items()}
            for w,c in self._w0.items(): self.workers[w]['worker_count']=c
            super().reset()
            self.sw_fired=None; self._src_jobs=0; self._sw_done=False
            self.env.process(self._mon())
        def _run_job(self, ws, job, req):
            yield from super()._run_job(ws, job, req)
            if ws==SRC: self._src_jobs+=1
        def _mon(self):
            acc=0.0
            while not self._sw_done:
                yield self.env.timeout(30.0)
                if not self._is_work_time(): continue
                idle=(self._src_jobs>0 and self.in_progress.get(SRC,0)==0 and not self._pending[SRC])
                acc=acc+30.0 if idle else 0.0
                if acc>=600.0: self._fire()
        def _fire(self):
            now=self.env.now
            for ws in [SRC,*moves]: self._flush_idle(ws, now)
            for ws,n in moves.items():
                self.workers[ws]['worker_count']+=n
                r=self.worker_resources[ws]
                r._capacity += n*self.workers[ws].get('UnitsPerWorker',1)
                r._trigger_put(None); self._wake_dispatcher(ws)
            mv=sum(moves.values())
            self.workers[SRC]['worker_count']-=mv
            self.worker_resources[SRC]._capacity -= mv*self.workers[SRC].get('UnitsPerWorker',1)
            self._sw_done=True; self.sw_fired=float(now)
    return _E

def run(moves, mode):
    random.seed(1); torch.manual_seed(1)
    cls = batch_log(base_cls) if not moves else sw_cls(batch_log(base_cls), moves)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')}, env_cls=cls)
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    if mode=='fifo':
        ag=None
    else:
        ag=build.build_agent(env, checkpoint='result/runs/q180s__compbase-300ep/agent_last.pt')
        ag.reset_buffer(); ag.train(True); torch.manual_seed(9000)
    env.run(agent=ag, max_sec=2592000)
    h=env.env.now/3600.0; b,_=tou(env, env.env.now)
    return h, b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL), getattr(env,'sw_fired',None)

CASES=[('none',{}), ('FwInput+6',{LINES['FwInput']:6}), ('Inspection+6',{LINES['Inspection']:6}),
       ('Aging+6',{LINES['Aging']:6})]
print("q540 · due4 · 18:00 — FIFO(관측 미사용) vs 학습정책")
print(f"{'조합':14s} {'FIFO makespan':>14s} {'FIFO Δ':>8s} | {'정책 makespan':>14s} {'정책 Δ':>8s}")
res={}
for name, mv in CASES:
    f_h,f_w,f_fire = run(mv,'fifo')
    p_h,p_w,p_fire = run(mv,'policy')
    res[name]=(f_h,p_h)
    fb = res['none'][0]; pb = res['none'][1]
    print(f"{name:14s} {f_h:13.2f}h {(f_h-fb)/fb*100:+7.2f}% | {p_h:13.2f}h {(p_h-pb)/pb*100:+7.2f}%"
          f"   (발동 {f_fire/3600 if f_fire else 0:.2f}h/{p_fire/3600 if p_fire else 0:.2f}h)", flush=True)
    json.dump(res, open('exp_overtime/realloc_fifo_check.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
