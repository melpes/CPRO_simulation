from __future__ import annotations
import os, time

import torch

from util.rl_logger import RLLogger
from simulation import EPISODE_DURATION_SEC

_ROOT = os.path.dirname(os.path.abspath(__file__))

RUNS_DIR        = os.path.join(_ROOT, 'result', 'runs')
AAS_DIR         = os.path.join(_ROOT, 'aas_data')
STOP_SENTINEL   = 'STOP'
LOG_NAME        = 'rl_log.jsonl'
CHECKPOINT_NAME = 'agent_mod.pt'
DEPLOY_DIR      = 'deploy'


def train(env, agent, MaxEpisodes, run_name=None, episode_max_sec=EPISODE_DURATION_SEC, resume=False):
    if run_name is None:
        run_name = 'run_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    out_dir = os.path.join(RUNS_DIR, run_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f'[train] outputs → result/runs/{run_name}/', flush=True)
    logger = RLLogger(os.path.join(out_dir, LOG_NAME), resume=resume)
    checkpoint_path = os.path.join(out_dir, CHECKPOINT_NAME)

    for episode in range(logger.next_episode, logger.next_episode + MaxEpisodes):
        if os.path.exists(os.path.join(out_dir, STOP_SENTINEL)):
            print(f'[ep {episode}] STOP sentinel — graceful exit', flush=True)
            break
        agent.reset_buffer()
        summary = env.run(agent=agent, max_sec=episode_max_sec)
        R = env.episode_reward()
        decisions = len(agent.buf)
        metrics = agent.learn(R, env.KnowledgeGraph)
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
            line_idle_time=summary.get('LineIdleTime'))
        if is_best:
            torch.save({'model': agent.state_dict(), 'optim': agent.optimizer.state_dict()}, checkpoint_path)
        throughput_line = ' '.join(f'{m}:{env.Throughput[m]}/{env.target_qty[m]}' for m in env.target_qty)
        explained_variance = (metrics or {}).get('critic/explained_variance')
        print(f'[ep {episode:>4}] R={R:+.4f} decisions={decisions} '
              f'makespan={summary["makespan_sec"]:.0f} E={summary["EpisodeEnergyKwh"]:.2f} '
              f'thru=[{throughput_line}] ev={explained_variance} {"BEST↑" if is_best else ""}', flush=True)

    if os.path.exists(checkpoint_path):
        import package
        package_dir = package.build_package(checkpoint_path, os.path.join(out_dir, DEPLOY_DIR))
        print(f'[train] deploy package → {os.path.relpath(package_dir, _ROOT)}/', flush=True)


if __name__ == '__main__':
    import path_extractor
    import build

    for filename in build.TRAINING_AAS_FILES:
        path_extractor.load(os.path.join(AAS_DIR, filename))

    env   = build.build_simulation()
    agent = build.build_agent(env)
    train(env, agent, env.MaxEpisodes, episode_max_sec=env.MaxEpisodeSec)
