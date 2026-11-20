import math

import numpy
import torch

from reinforcement_learning import model


# ================================================ PPO 설정값 ================================================
PPO_SETTINGS = {
    'discount_factor': 1.0,
    'advantage_decay': 0.95,
    'update_epochs': 10,
    'minibatch_size': 32,
    'clip_range': 0.2,
    'value_loss_weight': 0.5,
    'max_gradient_norm': 0.5,
    'priority_learning_rate': 0.0003,
    'process_start_learning_rate': 0.001,
    'optimizer_epsilon': 0.00001,
    'episodes_per_update': 4,
}


# ================================================ 계산에 쓰는 고정값: 이득 정규화의 0 나눗셈 방지 값, 마지막 결정 뒤의 가치, 에피소드가 1개일 때의 이득, 제곱 지수 ================================================
ADVANTAGE_NORMALIZATION_EPSILON = 0.00000001
VALUE_AFTER_LAST_DECISION = 0.0
ADVANTAGE_WHEN_SINGLE_EPISODE = 0.0
SQUARE_EXPONENT = 2


# ================================================ optimizer 생성: 작업 우선순위 신경망용과 공정 착수 신경망용 ================================================
def create_optimizers(reinforcement_learning_model, priority_learning_rate,
                      process_start_learning_rate):
    priority_optimizer = torch.optim.Adam(
        reinforcement_learning_model.priority_parameters(),
        lr=priority_learning_rate, eps=PPO_SETTINGS['optimizer_epsilon'])
    process_start_optimizer = torch.optim.Adam(
        reinforcement_learning_model.process_start_parameters(),
        lr=process_start_learning_rate, eps=PPO_SETTINGS['optimizer_epsilon'])
    return {
        'priority': priority_optimizer,
        'process_start': process_start_optimizer,
    }


# ================================================ 이득과 가치 목표값 계산: 한 에피소드의 결정 구간마다 ================================================
def advantages_and_value_targets(decisions, discount_factor, advantage_decay):
    values = [decision['value'] for decision in decisions]
    values.append(VALUE_AFTER_LAST_DECISION)
    advantages = [0.0] * len(decisions)
    later_advantage = 0.0
    for index in reversed(range(len(decisions))):
        reward = decisions[index]['reward']
        value_error = reward + discount_factor * values[index + 1] - values[index]
        later_advantage = value_error + discount_factor * advantage_decay * later_advantage
        advantages[index] = later_advantage
    value_targets = []
    for index, advantage in enumerate(advantages):
        value_targets.append(advantage + values[index])
    return {
        'advantages': advantages,
        'value_targets': value_targets,
    }


def normalized_advantages(advantages):
    centered_advantages = advantages - advantages.mean()
    return centered_advantages / (advantages.std() + ADVANTAGE_NORMALIZATION_EPSILON)


# ================================================ 손실 계산: 행동의 로그 확률, 확률 비율을 제한한 행동 손실, 가치 오차 제곱 ================================================
def action_log_probability(network_output, action):
    standard_deviation = network_output['log_standard_deviation'].exp()
    action_distribution = torch.distributions.Normal(network_output['mean'], standard_deviation)
    return action_distribution.log_prob(action)


def clipped_action_loss(probability_ratio, advantage, clip_range):
    unclipped_objective = probability_ratio * advantage
    clipped_ratio = probability_ratio.clamp(1 - clip_range, 1 + clip_range)
    clipped_objective = clipped_ratio * advantage
    return -torch.min(unclipped_objective, clipped_objective)


def squared_value_error(value, value_target):
    return (value - value_target) ** SQUARE_EXPONENT


def is_probability_ratio_outside_clip_range(probability_ratio, clip_range):
    return abs(float(probability_ratio.detach()) - 1.0) > clip_range


def mean_loss(sample_losses):
    return torch.stack(sample_losses).mean()


def last_value_or_none(values):
    if values:
        return values[-1]
    return None


# ================================================ 작업 우선순위 신경망 갱신: 결정 구간을 섞어 minibatch마다 한 걸음 ================================================
def priority_training_samples(episodes):
    decisions = []
    advantages = []
    value_targets = []
    for episode in episodes:
        estimates = advantages_and_value_targets(
            episode['decisions'], PPO_SETTINGS['discount_factor'],
            PPO_SETTINGS['advantage_decay'])
        decisions.extend(episode['decisions'])
        advantages.extend(estimates['advantages'])
        value_targets.extend(estimates['value_targets'])
    raw_advantages = torch.tensor(advantages, dtype=torch.float32)
    return {
        'decisions': decisions,
        'raw_advantages': raw_advantages,
        'advantages': normalized_advantages(raw_advantages),
        'value_targets': torch.tensor(value_targets, dtype=torch.float32),
    }


def priority_sample_losses(reinforcement_learning_model, decision, advantage, value_target,
                           edge_connections):
    network_output = reinforcement_learning_model.priority_forward(
        torch.as_tensor(decision['node_features']), edge_connections,
        torch.as_tensor(decision['global_information']),
        torch.tensor([decision['process_start_action']], dtype=torch.float32))
    priority_weights = torch.as_tensor(decision['priority_weights'])
    log_probability = action_log_probability(network_output, priority_weights).sum()
    probability_ratio = torch.exp(log_probability - decision['log_probability'])
    clip_range = PPO_SETTINGS['clip_range']
    return {
        'action_loss': clipped_action_loss(probability_ratio, advantage, clip_range),
        'value_loss': squared_value_error(network_output['value'], value_target),
        'log_probability_decrease': float(
            decision['log_probability'] - log_probability.detach()),
        'is_clipped': float(
            is_probability_ratio_outside_clip_range(probability_ratio, clip_range)),
    }


def priority_minibatch_step(reinforcement_learning_model, priority_optimizer,
                            priority_parameters, training_samples, sample_indices,
                            edge_connections):
    sample_losses = []
    for sample_index in sample_indices:
        sample_losses.append(priority_sample_losses(
            reinforcement_learning_model, training_samples['decisions'][sample_index],
            training_samples['advantages'][sample_index],
            training_samples['value_targets'][sample_index], edge_connections))
    action_loss = mean_loss([losses['action_loss'] for losses in sample_losses])
    value_loss = mean_loss([losses['value_loss'] for losses in sample_losses])
    total_loss = action_loss + PPO_SETTINGS['value_loss_weight'] * value_loss
    priority_optimizer.zero_grad(set_to_none=True)
    total_loss.backward()
    torch.nn.utils.clip_grad_norm_(priority_parameters, PPO_SETTINGS['max_gradient_norm'])
    priority_optimizer.step()
    return {
        'action_loss': float(action_loss.detach()),
        'value_loss': float(value_loss.detach()),
        'approximate_kl_divergence': float(numpy.mean(
            [losses['log_probability_decrease'] for losses in sample_losses])),
        'clipped_fraction': float(numpy.mean(
            [losses['is_clipped'] for losses in sample_losses])),
    }


def update_priority_network(reinforcement_learning_model, priority_optimizer, episodes,
                            edge_connections, shuffle_generator):
    training_samples = priority_training_samples(episodes)
    sample_count = len(training_samples['decisions'])
    priority_parameters = reinforcement_learning_model.priority_parameters()
    minibatch_size = PPO_SETTINGS['minibatch_size']
    step_records = []
    for epoch in range(PPO_SETTINGS['update_epochs']):
        shuffled_indices = torch.randperm(sample_count, generator=shuffle_generator)
        for minibatch_start in range(0, sample_count, minibatch_size):
            minibatch_end = minibatch_start + minibatch_size
            sample_indices = shuffled_indices[minibatch_start:minibatch_end].tolist()
            step_records.append(priority_minibatch_step(
                reinforcement_learning_model, priority_optimizer, priority_parameters,
                training_samples, sample_indices, edge_connections))
    minibatches_per_epoch = max(1, math.ceil(sample_count / minibatch_size))
    last_epoch_records = step_records[-minibatches_per_epoch:]
    return {
        'priority_sample_count': sample_count,
        'priority_optimizer_steps': len(step_records),
        'priority_action_loss_last': step_records[-1]['action_loss'],
        'priority_value_loss_last': step_records[-1]['value_loss'],
        'priority_approximate_kl_divergence_last_epoch': float(numpy.mean(
            [record['approximate_kl_divergence'] for record in last_epoch_records])),
        'priority_clipped_fraction_last_epoch': float(numpy.mean(
            [record['clipped_fraction'] for record in last_epoch_records])),
        'priority_advantage_standard_deviation': float(
            training_samples['raw_advantages'].std()),
    }


# ================================================ 공정 착수 신경망 갱신: 에피소드 묶음 전체로 한 걸음씩, 행동 손실은 탐색으로 착수 판단이 바뀐 에피소드만 ================================================
def process_start_training_episodes(episodes):
    reward_sums = []
    values = []
    for episode in episodes:
        reward_sums.append(sum(decision['reward'] for decision in episode['decisions']))
        values.append(episode['process_start_decision']['value'])
    episode_reward_sums = torch.tensor(reward_sums, dtype=torch.float32)
    values_before_update = torch.tensor(values, dtype=torch.float32)
    advantages = episode_reward_sums - values_before_update
    if len(episodes) > 1:
        advantages = normalized_advantages(advantages)
    else:
        advantages = advantages * ADVANTAGE_WHEN_SINGLE_EPISODE
    training_episodes = []
    for episode_index, episode in enumerate(episodes):
        process_start_decision = episode['process_start_decision']
        training_episodes.append({
            'process_start_decision': process_start_decision,
            'episode_reward_sum': episode_reward_sums[episode_index],
            'advantage': advantages[episode_index],
            'uses_action_loss': bool(
                process_start_decision['start_judgment_changed_by_exploration']),
        })
    return {
        'training_episodes': training_episodes,
        'episode_reward_sums': episode_reward_sums,
        'values_before_update': values_before_update,
    }


def process_start_episode_losses(reinforcement_learning_model, training_episode,
                                 edge_connections):
    process_start_decision = training_episode['process_start_decision']
    network_output = reinforcement_learning_model.process_start_forward(
        torch.as_tensor(process_start_decision['node_features']), edge_connections,
        torch.as_tensor(process_start_decision['global_information']))
    episode_losses = {
        'value_loss': squared_value_error(
            network_output['value'], training_episode['episode_reward_sum']),
    }
    if training_episode['uses_action_loss']:
        process_start_action = torch.tensor(process_start_decision['process_start_action'])
        log_probability = action_log_probability(network_output, process_start_action)
        probability_ratio = torch.exp(
            log_probability - process_start_decision['log_probability'])
        clip_range = PPO_SETTINGS['clip_range']
        episode_losses['action_loss'] = clipped_action_loss(
            probability_ratio, training_episode['advantage'], clip_range)
        episode_losses['log_probability_decrease'] = float(
            process_start_decision['log_probability'] - log_probability.detach())
        episode_losses['is_clipped'] = float(
            is_probability_ratio_outside_clip_range(probability_ratio, clip_range))
    return episode_losses


def process_start_epoch_step(reinforcement_learning_model, process_start_optimizer,
                             training_episodes, edge_connections):
    all_episode_losses = []
    for training_episode in training_episodes:
        all_episode_losses.append(process_start_episode_losses(
            reinforcement_learning_model, training_episode, edge_connections))
    action_episode_losses = [losses for losses in all_episode_losses if 'action_loss' in losses]
    value_loss = mean_loss([losses['value_loss'] for losses in all_episode_losses])
    total_loss = PPO_SETTINGS['value_loss_weight'] * value_loss
    if action_episode_losses:
        action_loss = mean_loss([losses['action_loss'] for losses in action_episode_losses])
        total_loss = total_loss + action_loss
    process_start_optimizer.zero_grad(set_to_none=True)
    total_loss.backward()
    if not action_episode_losses:
        for parameter in reinforcement_learning_model.process_start_action_parameters():
            parameter.grad = None
    parameters_with_gradient = []
    for parameter in reinforcement_learning_model.process_start_parameters():
        if parameter.grad is not None:
            parameters_with_gradient.append(parameter)
    torch.nn.utils.clip_grad_norm_(parameters_with_gradient, PPO_SETTINGS['max_gradient_norm'])
    process_start_optimizer.step()
    step_record = {'value_loss': float(value_loss.detach())}
    if action_episode_losses:
        step_record['action_loss'] = float(action_loss.detach())
        step_record['approximate_kl_divergence'] = float(numpy.mean(
            [losses['log_probability_decrease'] for losses in action_episode_losses]))
        step_record['clipped_fraction'] = float(numpy.mean(
            [losses['is_clipped'] for losses in action_episode_losses]))
    return step_record


def update_process_start_network(reinforcement_learning_model, process_start_optimizer,
                                 episodes, edge_connections):
    prepared = process_start_training_episodes(episodes)
    training_episodes = prepared['training_episodes']
    step_records = []
    for epoch in range(PPO_SETTINGS['update_epochs']):
        step_records.append(process_start_epoch_step(
            reinforcement_learning_model, process_start_optimizer, training_episodes,
            edge_connections))
    judgment_changed_episodes = [training_episode for training_episode in training_episodes
                                 if training_episode['uses_action_loss']]
    action_step_records = [record for record in step_records if 'action_loss' in record]
    return {
        'process_start_episode_count': len(episodes),
        'process_start_judgment_changed_episode_count': len(judgment_changed_episodes),
        'process_start_action_steps': len(action_step_records),
        'process_start_value_loss_last': step_records[-1]['value_loss'],
        'process_start_action_loss_last': last_value_or_none(
            [record['action_loss'] for record in action_step_records]),
        'process_start_approximate_kl_divergence_last': last_value_or_none(
            [record['approximate_kl_divergence'] for record in action_step_records]),
        'process_start_clipped_fraction_last': last_value_or_none(
            [record['clipped_fraction'] for record in action_step_records]),
        'process_start_episode_reward_sums': prepared['episode_reward_sums'].tolist(),
        'process_start_values_before_update': prepared['values_before_update'].tolist(),
    }


# ================================================ PPO 갱신: 에피소드 묶음의 결정 기록으로 두 신경망의 가중치 갱신 ================================================
def ppo_update(reinforcement_learning_model, optimizers, episodes, edge_connections,
               shuffle_seed):
    edge_connection_tensors = model.edge_connection_tensors(edge_connections)
    shuffle_generator = torch.Generator().manual_seed(int(shuffle_seed))
    reinforcement_learning_model.train()
    priority_statistics = update_priority_network(
        reinforcement_learning_model, optimizers['priority'], episodes,
        edge_connection_tensors, shuffle_generator)
    process_start_statistics = update_process_start_network(
        reinforcement_learning_model, optimizers['process_start'], episodes,
        edge_connection_tensors)
    reinforcement_learning_model.eval()
    log_standard_deviations = {
        'priority_log_standard_deviation':
            reinforcement_learning_model.priority_log_standard_deviation.detach().tolist(),
        'process_start_log_standard_deviation':
            float(reinforcement_learning_model.process_start_log_standard_deviation.detach()),
    }
    update_statistics = {}
    update_statistics.update(priority_statistics)
    update_statistics.update(process_start_statistics)
    update_statistics.update(log_standard_deviations)
    return update_statistics
