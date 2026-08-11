# 재배분 탐색 — 라인별 이동 인원 스윕 (boxplot 용 데이터)
#   Resource capacity 조정 반영 (util/exp_run.py _sw_realloc 원본 로직)
#   src = SemiAssembly, 완전유휴 600초 누적 시 1회 발동
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

def sw_cls(base, moves, trig=600.0):
    class _E(base):
        def reset(self):
            if not hasattr(self,'_w0'):
                self._w0={w:i['worker_count'] for w,i in self.workers.items()}
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
                acc = acc+30.0 if idle else 0.0
                if acc>=trig: self._fire()
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

LINES = {'FwInput':'WWM_FwInputLine','LensHolder':'WWM_LensHolderLine','Focus':'WWM_FocusLine',
         'SetAssembly':'WWM_SetAssemblyLine','Inspection':'WWM_InspectionLine',
         'Aging':'WWM_AgingLine','Packaging':'WWM_PackagingLine','Oqc':'WWM_OqcLine'}
LEVELS = [6]             # 1차 스크리닝 — 전 라인 동일 인원으로 반응 라인만 골라낸다
SEEDS  = [9000]          # 시드 1개 — (라인 x 인원) 격자를 넓게 보는 쪽 우선

def run(moves, sseed):
    random.seed(1); torch.manual_seed(1)
    cls = batch_log(base_cls) if not moves else sw_cls(batch_log(base_cls), moves)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')}, env_cls=cls)
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag=build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(sseed); env.run(agent=ag, max_sec=2592000)
    h=env.env.now/3600.0; b,_=tou(env, env.env.now)
    return h, b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL), getattr(env,'sw_fired',None)

OUT='exp_overtime/realloc_explore.json'
out = json.load(open(OUT,encoding='utf-8')) if os.path.exists(OUT) else []
done = {(r['line'], r['n'], r['seed']) for r in out}

def add(line, n, moves):
    for s in SEEDS:
        if (line,n,s) in done: continue
        t0=time.time(); h,w,f = run(moves, s)
        out.append({'line':line,'n':n,'seed':s,'makespan_h':h,'wkwh':w,
                    'fired_h':(f/3600 if f else None)})
        json.dump(out, open(OUT,'w',encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"  {line:12s} n={n:2d} seed{s} {h:8.2f}h {w:9.1f} ({time.time()-t0:.0f}s)", flush=True)

print("=== 기준: 재배분 없음 ===", flush=True)
add('none', 0, {})

PHASE = os.environ.get('PHASE', '1')
if PHASE == '1':
    for nm, ws in LINES.items():
        print(f"=== {nm} 단독 (n=6 스크리닝) ===", flush=True)
        for n in LEVELS:
            add(nm, n, {ws: n})
else:
    # 2차 — 1차에서 반응한 라인만 곡선 채우고, 둘을 섞는다
    for nm in ('Aging', 'Packaging'):
        print(f"=== {nm} 곡선 ===", flush=True)
        for n in (2, 4, 8, 10):
            add(nm, n, {LINES[nm]: n})
    print("=== 혼합 (Aging + Packaging) ===", flush=True)
    for a, pk in ((4,2), (6,2), (4,4), (8,2)):
        add(f'A{a}-P{pk}', a+pk, {LINES['Aging']: a, LINES['Packaging']: pk})
print("done", flush=True)
