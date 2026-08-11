import argparse
import json
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)

DEFAULTS = {
    'fileset': 'default',
    'seed': 1,
    'due_day': 3,
    'max_sec': 30 * 86400,
    'episodes': 50,
    'checkpoint': None,
    'record_events': True,
    'env_overrides': {},
    'sw_realloc': {'enabled': False},
    'rl_realloc': {'enabled': False},
    'reward_override': {'enabled': False},
}


def load_settings(path):
    cfg = {**DEFAULTS, **json.load(open(path, encoding='utf-8'))}
    cfg = {k: v for k, v in cfg.items() if not k.startswith('_')}
    for key in ('run_name', 'mode', 'target_qty'):
        if not cfg.get(key):
            raise SystemExit(f'세팅에 {key} 가 필요합니다: {path}')
    if cfg['mode'] not in ('train', 'fifo', 'trained'):
        raise SystemExit(f"mode 는 train|fifo|trained 중 하나: {cfg['mode']}")
    if not isinstance(cfg['due_day'], dict):
        cfg['due_day'] = {m: cfg['due_day'] for m in cfg['target_qty']}
    return cfg


def make_env_cls(cfg):
    import simulation as sim
    sw = cfg.get('sw_realloc') or {}
    sw_on = bool(sw.get('enabled'))
    sw_src = sw.get('src', 'WWM_SemiAssemblyLine')
    sw_moves = sw.get('moves', {})
    sw_trigger = float(sw.get('idle_trigger_sec', 600))
    sw_tick = float(sw.get('tick_sec', 30))

    class ExpEnv(sim.CproSimEnv):
        def reset(self):
            if not hasattr(self, '_workers0'):
                self._workers0 = {ws: i['worker_count'] for ws, i in self.workers.items()}
            for ws, wc in self._workers0.items():
                self.workers[ws]['worker_count'] = wc
            super().reset()
            self.events = []
            self.sw_fired_sec = None
            if sw_on:
                self._sw_src_jobs = 0
                self._sw_done = False
                self.env.process(self._sw_monitor())

        def _run_job(self, ws, job, req):
            t0 = self.env.now
            node = self.KnowledgeGraph.nodes[job['pc']]
            yield from super()._run_job(ws, job, req)
            if sw_on and ws == sw_src:
                self._sw_src_jobs += 1
            self.events.append({'type': 'job', 'model': node.model_id, 'pc': job['pc'],
                                'line': ws, 't0': float(t0),
                                't_cycle': float(t0 + node.CycleTimeSec),
                                't_total': float(self.env.now)})

        def smt_record(self, line_id, equipment, code, now, dt, kwh):
            base_cycle = next((c for n, c, _ in equipment if 'AOI' in n), equipment[-1][1])
            first = dt > base_cycle + 1e-9
            for name, cycle, power in equipment:
                on = cycle if first else min(cycle, base_cycle)
                self.events.append({'type': 'smt_eq', 'eq': name, 'line': line_id,
                                    't0': float(now - dt), 't_total': float(now),
                                    'kwh': power * on / 3600.0})

        def _sw_monitor(self):
            idle_acc = 0.0
            while not self._sw_done:
                yield self.env.timeout(sw_tick)
                if not self._is_work_time():
                    continue
                fully_idle = (self._sw_src_jobs > 0
                              and self.in_progress.get(sw_src, 0) == 0
                              and not self._pending[sw_src])
                idle_acc = idle_acc + sw_tick if fully_idle else 0.0
                if idle_acc >= sw_trigger:
                    self._sw_realloc()

        def _sw_realloc(self):
            now = self.env.now
            for ws in [sw_src, *sw_moves]:
                self._flush_idle(ws, now)
            for ws, n in sw_moves.items():
                self.workers[ws]['worker_count'] += n
                res = self.worker_resources[ws]
                res._capacity += n * self.workers[ws].get('UnitsPerWorker', 1)
                res._trigger_put(None)
                self._wake_dispatcher(ws)
            moved = sum(sw_moves.values())
            self.workers[sw_src]['worker_count'] -= moved
            self.worker_resources[sw_src]._capacity -= moved * self.workers[sw_src].get('UnitsPerWorker', 1)
            self._sw_done = True
            self.sw_fired_sec = now
            self.events.append({'type': 'realloc', 'line': sw_src, 't0': float(now),
                                'src': sw_src, 'moves': dict(sw_moves)})
            print(f'[SW] realloc fired t={now:.0f}s ({now / 3600:.2f}h): {sw_src} -{moved} → '
                  + ', '.join(f'{k}+{v}' for k, v in sw_moves.items()), flush=True)

    return ExpEnv


def dump_events(env, path):
    with open(path, 'w', encoding='utf-8') as fp:
        for ev in env.events:
            fp.write(json.dumps(ev, ensure_ascii=False) + '\n')


def snapshot(cfg, env, out_dir, extra=None, files=None):
    import build
    if files is None:
        files = build.DEFAULT_AAS_FILES if cfg['fileset'] == 'default' else build.TRAINING_AAS_FILES
    snap = {**cfg,
            'fileset_files': list(files),
            'realloc_params': getattr(env, 'realloc_params', None),
            'env': {'InfiniteStock': env.InfiniteStock, 'ScenarioMode': env.ScenarioMode,
                    'DefaultProcessConsumedPowerKw': env.DefaultProcessConsumedPowerKw,
                    'IdleRewardMode': env.IdleRewardMode, 'DueRewardMode': env.DueRewardMode,
                    'W2HorizonMode': getattr(env, 'W2HorizonMode', 'bottleneck'),
                    'SmtPlanEffective': getattr(env, 'SmtPlanEffective', None)},
            'workers': {ws: {'worker_count': i['worker_count'],
                             'UnitsPerWorker': i.get('UnitsPerWorker', 1)}
                        for ws, i in env.workers.items()},
            **(extra or {})}
    json.dump(snap, open(os.path.join(out_dir, 'settings.resolved.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


def run_once(cfg, env, agent, out_dir, label):
    summary = env.run(agent=agent, max_sec=cfg['max_sec'])
    makespan = env.env.now
    res = {
        'mode': label, 'makespan_sec': makespan, 'makespan_h': round(makespan / 3600, 2),
        'throughput': dict(env.Throughput), 'target': cfg['target_qty'],
        'CompletionSec': {m: env.CompletionSec.get(m) for m in cfg['target_qty']},
        'total_energy_kwh': round(env.total_energy_kwh(), 3),
        'assembly_energy_kwh': round(env.EpisodeEnergyKwh, 3),
        'baseline_energy_kwh': round(env.baseline_energy_kwh(), 3),
        'smt_energy_kwh': round(env.SMTEnergyKwh, 3),
        'sw_fired_sec': env.sw_fired_sec,
        'line_idle_time': {k: round(float(v), 1) for k, v in env.line_idle_time.items()},
        'workers_final': {ws: i['worker_count'] for ws, i in env.workers.items()},
        'smt_equip_energy': {l: {e: round(v, 4) for e, v in d.items()}
                             for l, d in env.smt_equip_energy.items()},
        'smt_plan_produced': sum(e['pcb'] for e in getattr(env, 'smt_plan_log', [])),
        'smt_last_output_sec': max((e['end_sec'] for e in getattr(env, 'smt_plan_log', [])),
                                   default=None),
    }
    json.dump(res, open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    if cfg['record_events']:
        dump_events(env, os.path.join(out_dir, 'events.jsonl'))
    print(json.dumps({k: res[k] for k in ('makespan_h', 'throughput', 'total_energy_kwh',
                                          'sw_fired_sec')}, ensure_ascii=False))
    return res


def run_train(cfg, env, out_dir):
    import torch
    import build
    from util.rl_logger import RLLogger

    logger = RLLogger(os.path.join(out_dir, 'rl_log.jsonl'), resume=True)
    ckpt = os.path.join(out_dir, 'agent_mod.pt')
    ckpt_last = os.path.join(out_dir, 'agent_last.pt')
    resume_from = next((p for p in (ckpt_last, ckpt)
                        if logger.next_episode and os.path.exists(p)), None)
    agent = build.build_agent(env, checkpoint=resume_from)
    agent.train()

    CRITERIA = {'best_R':     (max, lambda R, s: R),
                'min_idle':   (min, lambda R, s: s['TotalIdleTime']),
                'min_energy': (min, lambda R, s: s['EpisodeEnergyKwh'])}
    best = {}
    bc_path = os.path.join(out_dir, 'best_criteria.json')
    if logger.next_episode and os.path.exists(bc_path):
        best = {k: (float(v['value']), int(v['episode']))
                for k, v in json.load(open(bc_path, encoding='utf-8')).items()}

    print(f"[exp_run:train] run={cfg['run_name']} ep={logger.next_episode}→{cfg['episodes']} "
          f"E_max={env.MaxEpisodeEnergyKwh:.0f}kWh InfStock={env.InfiniteStock}", flush=True)
    for episode in range(logger.next_episode, cfg['episodes']):
        if os.path.exists(os.path.join(out_dir, 'STOP')):
            print(f'[ep {episode}] STOP sentinel — graceful exit', flush=True)
            break
        agent.CurrentEpisode = episode
        agent.reset_buffer()
        summary = env.run(agent=agent, max_sec=cfg['max_sec'])
        R = env.episode_reward()
        decisions = len(agent.buf)
        metrics = agent.learn(R, env.KnowledgeGraph)
        re_extra = None
        if hasattr(env, 'realloc_moves'):
            mv = {}
            for m in env.realloc_moves:
                mv[m['tgt']] = mv.get(m['tgt'], 0) + 1
            re_extra = {'realloc/moves_total': len(env.realloc_moves),
                        **{f'realloc/moves/{k}': v for k, v in mv.items()},
                        **{f'realloc/wc_final/{ws}': i['worker_count']
                           for ws, i in env.workers.items()}}
            if getattr(env, 'realloc_ratio', None):
                re_extra.update({f'realloc/ratio/{ws}': round(p, 4) for ws, p in
                                 zip(env.realloc_params['targets'], env.realloc_ratio)})
        is_best = logger.log_episode(
            episode, R=R, makespan=summary['makespan_sec'],
            energy=summary['EpisodeEnergyKwh'],
            throughput=dict(env.Throughput), target_qty=dict(env.target_qty),
            decisions=decisions, metrics=metrics,
            violations={'stock_shortage': env.StockShortageCount,
                        'stock_overflow': env.StockOverflowCount,
                        'idle_violation': env.IdleViolationCount,
                        'due_pace_deficit': env.DuePaceDeficit},
            reward_terms=summary.get('RewardTerms'),
            line_energy=summary.get('LineEnergy'),
            idle_energy=summary.get('IdleEnergyKwh'),
            smt_energy=summary.get('SMTEnergyKwh'),
            smt_equip_energy=summary.get('SMTEquipEnergy'),
            completion_sec=summary.get('CompletionSec'),
            idle_time_total=summary.get('TotalIdleTime'),
            line_idle_time=summary.get('LineIdleTime'),
            extra=re_extra)
        if is_best:
            torch.save({'model': agent.state_dict(), 'optim': agent.optimizer.state_dict()}, ckpt)
        torch.save({'model': agent.state_dict(), 'optim': agent.optimizer.state_dict()}, ckpt_last)
        for name, (agg, key) in CRITERIA.items():
            v = float(key(R, summary))
            if name not in best or v == agg(v, best[name][0]):
                best[name] = (v, episode)
                dump_events(env, os.path.join(out_dir, f'events_{name}.jsonl'))
                json.dump({k: {'value': val, 'episode': ep} for k, (val, ep) in best.items()},
                          open(bc_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        thru = ' '.join(f'{m}:{env.Throughput[m]}/{env.target_qty[m]}' for m in env.target_qty)
        re_str = (f' moves={len(env.realloc_moves)}' if hasattr(env, 'realloc_moves') else '')
        print(f'[ep {episode:>4}] R={R:+.4f} decisions={decisions} '
              f'makespan={summary["makespan_sec"]:.0f} E={summary["EpisodeEnergyKwh"]:.2f} '
              f'idle={summary["TotalIdleTime"]:.0f} thru=[{thru}]{re_str} {"BEST↑" if is_best else ""}', flush=True)
    print(f'[exp_run:train] DONE best={ {k: (round(v, 4), e) for k, (v, e) in best.items()} }', flush=True)


def main():
    parser = argparse.ArgumentParser(description='통합 실험 러너 — 세팅 JSON 하나로 학습/FIFO/학습정책 추론을 실행.')
    parser.add_argument('settings')
    cfg = load_settings(parser.parse_args().settings)

    import torch
    import path_extractor, build
    files = list(build.DEFAULT_AAS_FILES if cfg['fileset'] == 'default' else build.TRAINING_AAS_FILES)
    rl_re = cfg.get('rl_realloc') or {}
    env_cls = make_env_cls(cfg)
    if rl_re.get('enabled'):
        from util import exp_realloc
        files = [exp_realloc.PSM_REALLOC_FILE if f == 'ProvisionOfSimulationModel.json' else f
                 for f in files]
        rp = exp_realloc.load_params(os.path.join(ROOT, 'aas_data'), overrides=rl_re)
        env_cls = exp_realloc.wrap_env_cls(env_cls, rp)
        exp_realloc.install(rp)
    ro = cfg.get('reward_override') or {}
    if ro.get('enabled'):
        from util import exp_reward_tmp
        env_cls = exp_reward_tmp.wrap_env_cls(env_cls, ro)
    for f in files:
        path_extractor.load(os.path.join(ROOT, 'aas_data', f))

    out_dir = os.path.join(ROOT, 'result', 'runs', cfg['run_name'])
    os.makedirs(out_dir, exist_ok=True)

    env = build.build_simulation(target_qty=dict(cfg['target_qty']),
                                 due_day=dict(cfg['due_day']),
                                 env_cls=env_cls)
    for k, v in (cfg['env_overrides'] or {}).items():
        if v is not None and not k.startswith('_'):
            setattr(env, k, v)

    random.seed(cfg['seed'])
    torch.manual_seed(cfg['seed'])
    env.reset()
    snapshot(cfg, env, out_dir, files=files)

    if cfg['mode'] == 'train':
        run_train(cfg, env, out_dir)
    elif cfg['mode'] == 'fifo':
        run_once(cfg, env, agent=None, out_dir=out_dir, label='fifo')
    else:
        ckpt = cfg['checkpoint'] or os.path.join(out_dir, 'agent_mod.pt')
        if not os.path.exists(ckpt):
            raise SystemExit(f'checkpoint 없음: {ckpt}')
        agent = build.build_agent(env, checkpoint=ckpt)
        agent.eval()
        run_once(cfg, env, agent=agent, out_dir=out_dir, label='trained')


if __name__ == '__main__':
    main()
