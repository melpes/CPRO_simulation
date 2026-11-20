from discrete_event_simulation import carbon_components


# ================================================ 보상 항목 가중치 ================================================
REWARD_WEIGHTS = {
    'production_time': 1.0,
    'carbon_emission': 1.0,
    'delivery_delay': 5.0,
}


# ================================================ 보상 항목 정규화 분모: 기준 실행(S1-2, 제품별 540개, 2026-10-19 사전 검증 1회)의 결과 ================================================
REFERENCE_RUN_COMPLETION_SEC = 243625.0
REFERENCE_RUN_WEIGHTED_ENERGY_KWH = 10188.229662725927
REWARD_NORMALIZATION_DENOMINATORS = {
    'production_time': REFERENCE_RUN_COMPLETION_SEC,
    'carbon_emission': REFERENCE_RUN_WEIGHTED_ENERGY_KWH,
}


# ================================================ 보상 항목 계산: 생산 시간·탄소 배출량·납기 지연 ================================================
def production_time_reward(weight, work_time_sec, denominator_work_time_sec):
    return -weight * work_time_sec / denominator_work_time_sec


def carbon_emission_reward(weight, carbon_emission, denominator_energy_kwh):
    return -weight * carbon_emission / denominator_energy_kwh


def delivery_delay_reward(weight, now_sec, due_sec_by_product, completion_sec_by_product):
    delay_ratios = []
    for product, due_sec in due_sec_by_product.items():
        completion_sec = completion_sec_by_product[product]
        if completion_sec is None:
            end_sec = now_sec
        else:
            end_sec = min(completion_sec, now_sec)
        delay_sec = max(0.0, end_sec - due_sec)
        delay_ratios.append(delay_sec / due_sec)
    product_count = max(len(delay_ratios), 1)
    return -weight * sum(delay_ratios) / product_count


# ================================================ 누적 보상 계산: 목표 구간 시작부터 지정 시각까지의 항목별 보상과 합계. 목표 구간이 바뀌면 생산 시간과 탄소 배출량을 0부터 다시 세고 납기 지연은 그 목표 구간의 납기로 계산(시각은 모두 목표 구간 시작부터 잰 값). 목표 수량 실행은 목표 구간이 0초에 시작하는 하나뿐이라 실행 시작부터 센 값과 같음. 납기 지연은 목표 수량과 납기가 있는 제품만 계산 ================================================
class CumulativeReward:

    def __init__(self, simulation_model):
        self.simulation_model = simulation_model
        reference_completion_sec = REWARD_NORMALIZATION_DENOMINATORS['production_time']
        self.denominator_work_time_sec = float(
            simulation_model.elapsed_work_time_sec(reference_completion_sec))
        self.denominator_energy_kwh = REWARD_NORMALIZATION_DENOMINATORS['carbon_emission']
        self.cache = {}
        self.cached_target_period_number = None
        self.weighted_kwh_at_start_by_target_period_number = {}

    def reward_items(self, sec):
        simulation_model = self.simulation_model
        return self.reward_items_in_target_period(
            sec, simulation_model.target_period_number,
            simulation_model.target_period_start_sec,
            simulation_model.target_period_due_sec_by_product,
            simulation_model.completion_sec_by_product)

    def reward_items_of_ended_target_periods(self):
        reward_items_by_target_period_number = {}
        for target_period_record in self.simulation_model.target_period_records:
            target_period_number = target_period_record['target_period_number']
            reward_items_by_target_period_number[target_period_number] = (
                self.reward_items_in_target_period(
                    target_period_record['end_sec'], target_period_number,
                    target_period_record['start_sec'],
                    target_period_record['due_sec_by_product'],
                    target_period_record['completion_sec_by_product']))
        return reward_items_by_target_period_number

    def reward_items_in_target_period(
            self, sec, target_period_number, target_period_start_sec,
            target_period_due_sec_by_product, completion_sec_by_product):
        simulation_model = self.simulation_model
        work_time_sec_at_start = simulation_model.elapsed_work_time_sec(target_period_start_sec)
        work_time_sec = simulation_model.elapsed_work_time_sec(sec) - work_time_sec_at_start
        weighted_kwh_at_start = self.weighted_kwh_at_target_period_start(
            target_period_number, target_period_start_sec)
        weighted_kwh_until_sec = simulation_model.aggregate_energy(sec)['weighted_kwh']
        weighted_kwh = weighted_kwh_until_sec - weighted_kwh_at_start
        carbon_emission = carbon_components.convert_to_carbon_emission(weighted_kwh)
        due_sec_by_product = {}
        completion_sec_by_product_with_due = {}
        for product, quantity in simulation_model.target_quantity_by_product.items():
            has_due = product in target_period_due_sec_by_product
            if quantity > 0 and has_due:
                due_sec_by_product[product] = (
                    target_period_due_sec_by_product[product] - target_period_start_sec)
                completion_sec = completion_sec_by_product.get(product)
                if completion_sec is not None:
                    completion_sec = completion_sec - target_period_start_sec
                completion_sec_by_product_with_due[product] = completion_sec
        return {
            'production_time': production_time_reward(
                REWARD_WEIGHTS['production_time'], work_time_sec, self.denominator_work_time_sec),
            'carbon_emission': carbon_emission_reward(
                REWARD_WEIGHTS['carbon_emission'], carbon_emission, self.denominator_energy_kwh),
            'delivery_delay': delivery_delay_reward(
                REWARD_WEIGHTS['delivery_delay'], sec - target_period_start_sec,
                due_sec_by_product, completion_sec_by_product_with_due),
        }

    def weighted_kwh_at_target_period_start(self, target_period_number, target_period_start_sec):
        weighted_kwh_at_start_by_number = self.weighted_kwh_at_start_by_target_period_number
        if target_period_number not in weighted_kwh_at_start_by_number:
            energy_at_start = self.simulation_model.aggregate_energy(target_period_start_sec)
            weighted_kwh_at_start_by_number[target_period_number] = energy_at_start['weighted_kwh']
        return weighted_kwh_at_start_by_number[target_period_number]

    def total_at(self, sec):
        sec = float(sec)
        target_period_number = self.simulation_model.target_period_number
        if target_period_number != self.cached_target_period_number:
            self.cache = {}
            self.cached_target_period_number = target_period_number
        if sec not in self.cache:
            self.cache[sec] = sum(self.reward_items(sec).values())
        return self.cache[sec]


# ================================================ 구간 보상 계산: 결정 구간 동안 변한 누적 보상. 결정 구간은 한 목표 구간 안에서만 셈: 다음 결정이 같은 목표 구간에 있으면 다음 결정까지, 없으면 그 목표 구간이 끝난 시점까지(끝나지 않은 목표 구간이면 실행 종료 시점까지). 목표 수량 실행은 목표 구간이 하나뿐이라 다음 결정 또는 실행 종료 시점까지 ================================================
def interval_rewards(decisions, target_period_numbers_of_decisions, final_reward_items,
                     reward_items_of_ended_target_periods):
    final_reward = sum(final_reward_items.values())
    decision_count = len(decisions)
    for index, decision in enumerate(decisions):
        target_period_number = target_period_numbers_of_decisions[index]
        interval_end = final_reward
        if target_period_number in reward_items_of_ended_target_periods:
            reward_items_at_end = reward_items_of_ended_target_periods[target_period_number]
            interval_end = sum(reward_items_at_end.values())
        next_index = index + 1
        if next_index < decision_count:
            if target_period_numbers_of_decisions[next_index] == target_period_number:
                interval_end = decisions[next_index]['cumulative_reward']
        decision['reward'] = interval_end - decision['cumulative_reward']
    return decisions
