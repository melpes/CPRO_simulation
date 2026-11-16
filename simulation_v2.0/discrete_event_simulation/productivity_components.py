import random


# ================================================ 작업자 유휴시간 증가분: 작업하지 않은 인원 × 직전 기록 이후의 근무시간 ================================================
def worker_idle_time_increase_sec(idle_worker_count, work_time_sec):
    if idle_worker_count > 0 and work_time_sec > 0:
        return idle_worker_count * work_time_sec
    return 0.0


# ================================================ 목표 달성 여부: 생산량이 목표 수량 이상인지 ================================================
def is_target_quantity_reached(production_quantity, target_quantity):
    return production_quantity >= target_quantity


class ProductivityComponents:

    # ================================================ 생산성 지표 속성 만들기: 생산량(실행 시작부터, 목표 구간 시작부터), 목표 달성 시각, 작업자 유휴시간, 불량 수 ================================================
    def reset_productivity_components(self):
        self.production_quantity_by_product = {}
        self.production_quantity_in_target_period_by_product = {}
        self.completion_sec_by_product = {}
        for product in self.target_quantity_by_product:
            self.production_quantity_by_product[product] = 0
            self.production_quantity_in_target_period_by_product[product] = 0
            self.completion_sec_by_product[product] = None
        self.defect_count_by_product = {}
        self.repair_count_by_product = {}
        self.worker_idle_time_sec_by_worker_group = {}
        self.idle_time_recorded_sec_by_worker_group = {}
        for worker_group in self.worker_groups:
            self.worker_idle_time_sec_by_worker_group[worker_group] = 0.0
            self.idle_time_recorded_sec_by_worker_group[worker_group] = 0.0

    # ================================================ 생산량과 목표 달성 시각: 제품의 마지막 공정이 끝나면 생산량 1 증가, 목표 구간 시작부터의 생산량이 목표 수량에 처음 도달한 시각 기록(목표 수량 실행은 목표 구간이 하나뿐이라 실행 시작부터의 생산량과 같음) ================================================
    def record_production(self, process_code):
        is_last_process = self.simulation_processes.is_last_process(process_code)
        product = self.simulation_processes.processes[process_code].product_code
        if is_last_process and product in self.production_quantity_by_product:
            self.production_quantity_by_product[product] += 1
            self.production_quantity_in_target_period_by_product[product] += 1
        if product not in self.completion_sec_by_product:
            return is_last_process
        if self.completion_sec_by_product[product] is not None:
            return is_last_process
        production_quantity = self.production_quantity_in_target_period_by_product.get(product, 0)
        target_quantity = self.target_quantity_by_product[product]
        if is_target_quantity_reached(production_quantity, target_quantity):
            self.completion_sec_by_product[product] = self.simpy_environment.now
        return is_last_process

    # ================================================ 생산 완료 시각: 모든 제품이 목표 수량에 도달하고 SMT 생산 계획의 PCB를 모두 만들어 재고에 반영한 시각. 무한가동은 생산 완료가 없어 None ================================================
    def sum_pcb_count_by_item_code(self, pcb_records, pcb_item_codes):
        pcb_count_by_item_code = {}
        for pcb_item_code in pcb_item_codes:
            pcb_counts = []
            for pcb_record in pcb_records:
                if pcb_record['pcb_item_code'] == pcb_item_code:
                    pcb_counts.append(pcb_record['pcb_count'])
            pcb_count_by_item_code[pcb_item_code] = sum(pcb_counts)
        return pcb_count_by_item_code

    def production_completion_sec(self):
        if self.infinite_operation_conditions['applied']:
            return None
        for product, target_quantity in self.target_quantity_by_product.items():
            production_quantity = self.production_quantity_by_product[product]
            if not is_target_quantity_reached(production_quantity, target_quantity):
                return None
            if self.completion_sec_by_product[product] is None:
                return None
        planned_pcb_count_by_item_code = {}
        for pcb_production_plan in self.smt_production_plan.values():
            for planned_item in pcb_production_plan:
                planned_pcb_count = planned_item['array_count'] * planned_item['quantity_per_array']
                planned_pcb_count_by_item_code[planned_item['item_code']] = planned_pcb_count
        produced_pcb_count_by_item_code = self.sum_pcb_count_by_item_code(
            self.produced_pcb_arrays, planned_pcb_count_by_item_code)
        stocked_pcb_count_by_item_code = self.sum_pcb_count_by_item_code(
            self.smt_production_records, planned_pcb_count_by_item_code)
        if produced_pcb_count_by_item_code != planned_pcb_count_by_item_code:
            return None
        if stocked_pcb_count_by_item_code != planned_pcb_count_by_item_code:
            return None
        end_secs = []
        for completion_sec in self.completion_sec_by_product.values():
            end_secs.append(float(completion_sec))
        for produced_pcb_array in self.produced_pcb_arrays:
            end_secs.append(produced_pcb_array['end_sec'])
        return max(end_secs)

    # ================================================ 작업자 유휴시간: 직전 기록 이후 작업하지 않은 인원 × 근무시간을 작업자 그룹별로 누적 ================================================
    def accumulate_worker_idle_time(self, worker_group, now_sec):
        worker_count = self.worker_groups[worker_group]['worker_count']
        running_job_count = self.running_job_count_by_worker_group.get(worker_group, 0)
        recorded_sec = self.idle_time_recorded_sec_by_worker_group[worker_group]
        work_time_sec = (
            self.elapsed_work_time_sec(now_sec) - self.elapsed_work_time_sec(recorded_sec))
        self.worker_idle_time_sec_by_worker_group[worker_group] += worker_idle_time_increase_sec(
            worker_count - running_job_count, work_time_sec)
        self.idle_time_recorded_sec_by_worker_group[worker_group] = now_sec

    # ================================================ 불량 수: 끝난 공정마다 불량률로 불량 판정(이미 불량인 제품은 다시 판정하지 않음), 수리 횟수 ================================================
    def judge_defects(
            self, product, finished_process_codes, is_defective, completed_process_codes):
        for process_code in finished_process_codes:
            if is_defective:
                continue
            process = self.simulation_processes.processes[process_code]
            defect_probability_per_output_item = process.defect_probability_per_output_item
            if random.random() < defect_probability_per_output_item:
                is_defective = True
                defect_count = self.defect_count_by_product.get(product, 0)
                self.defect_count_by_product[product] = defect_count + 1
                self.on_defect(product, process_code, completed_process_codes)
        return is_defective

    def on_defect(self, product, process_code, completed_process_codes):
        pass

    def count_repair(self, product):
        repair_count = self.repair_count_by_product.get(product, 0)
        self.repair_count_by_product[product] = repair_count + 1
