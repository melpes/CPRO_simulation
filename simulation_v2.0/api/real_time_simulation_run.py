from pathlib import Path
from time import sleep, time

from api import api_data_items, api_jobs, mqtt_publisher, simulation_engine
from api.mcf_instance_record import McfInstanceRecord


# ================================================ 실시간 실행 값: 한 번에 진행하는 최대 시뮬레이션 초, 시뮬레이션이 실시간보다 앞설 때 한 번에 쉬는 최대 실시간 초 ================================================
REAL_TIME_RUN_VALUES = {
    'maximum_advance_sec': 600,
    'maximum_wait_sec': 0.25,
}


# ================================================ 최대 속도를 뜻하는 시뮬레이션 배속 값: 실시간에 맞추지 않고 쉬지 않고 진행 ================================================
MAXIMUM_SPEED = 0.0


# ================================================ 발행 주기 설정이 0일 때: 0으로는 한 번에 진행할 폭을 정할 수 없어 이 주기(실시간 초)를 대신 씀. 지금 API(1.1.0)와 같은 값 ================================================
PUBLISH_INTERVAL_SEC_SETTING_ZERO = 0.0
PUBLISH_INTERVAL_SEC_USED_WHEN_SETTING_IS_ZERO = 5.0


# ================================================ 실시간 실행: 시뮬레이션 실행기 프로세스에서 실행 작업 하나를 처음부터 끝까지 진행. 시작할 때 그 시나리오의 MCF 인스턴스를 실행 작업 폴더로 복사해 둠 ================================================
def run_simulation_in_real_time(run_input, random_seed, job_directory):
    started_simulation = simulation_engine.start_simulation(
        run_input['execution_method'], run_input['infinite_operation'],
        run_input['target_quantity_by_product'], run_input['due_day_by_product'],
        run_input['simulation_period_day'], run_input['defect_rate_for_check'], random_seed)
    mcf_instance_record = McfInstanceRecord(
        job_directory, started_simulation['aas_directory'],
        started_simulation['mcf_recipe_structure'])
    real_time_run = RealTimeRun(
        job_directory, run_input['simulation_speed'], run_input['publish_interval_sec'],
        started_simulation['simulation_time_sec'], mcf_instance_record)
    return real_time_run.run_until_finished_or_stopped()


class RealTimeRun:

    def __init__(
            self, job_directory, simulation_speed, publish_interval_sec, start_sec,
            mcf_instance_record):
        self.job_directory = Path(job_directory)
        self.simulation_speed = simulation_speed
        self.publish_interval_sec = publish_interval_sec
        if self.publish_interval_sec == PUBLISH_INTERVAL_SEC_SETTING_ZERO:
            self.publish_interval_sec = PUBLISH_INTERVAL_SEC_USED_WHEN_SETTING_IS_ZERO
        self.start_sec = start_sec
        self.now_sec = start_sec
        self.published_sec = start_sec
        self.simulation_finished = False
        self.event_publisher = mqtt_publisher.EventPublisher(self.job_directory.name)
        self.mcf_instance_record = mcf_instance_record
        self.start_wall_sec = time()
        self.published_wall_sec = 0.0

    # ================================================ 진행 반복: 시뮬레이션이 끝나거나 중지 요청이 올 때까지 진행하고 발행 주기마다 발행, 끝나면 마지막 발행. 실행 결과에 MCF 인스턴스에 기록한 횟수와 걸린 실제 시간(초)을 함께 남김 ================================================
    def run_until_finished_or_stopped(self):
        while not self.simulation_finished:
            if api_jobs.is_stop_requested(self.job_directory):
                break
            self.advance_or_wait()
            if time() - self.published_wall_sec >= self.publish_interval_sec:
                self.publish(False)
        self.publish(True)
        return {
            'final_simulation_time_sec': self.now_sec,
            'stopped_by_request': api_jobs.is_stop_requested(self.job_directory),
            'mcf_instance_record_count': self.mcf_instance_record.record_count,
            'mcf_instance_record_wall_sec': self.mcf_instance_record.record_wall_sec,
        }

    # ================================================ 배속 맞추기: 실시간 경과에 배속을 곱한 시각까지 진행하고, 시뮬레이션이 앞서 있으면 쉼 ================================================
    def maximum_advance_sec(self):
        if self.simulation_speed > MAXIMUM_SPEED:
            sec_per_publish = self.simulation_speed * self.publish_interval_sec
            return min(REAL_TIME_RUN_VALUES['maximum_advance_sec'], sec_per_publish)
        return REAL_TIME_RUN_VALUES['maximum_advance_sec']

    def target_sec(self):
        if self.simulation_speed > MAXIMUM_SPEED:
            elapsed_wall_sec = time() - self.start_wall_sec
            return self.start_sec + elapsed_wall_sec * self.simulation_speed
        return self.now_sec + self.maximum_advance_sec()

    def advance_or_wait(self):
        target_sec = self.target_sec()
        if self.now_sec < target_sec:
            until_sec = min(target_sec, self.now_sec + self.maximum_advance_sec())
            advanced_simulation = simulation_engine.advance_simulation(until_sec)
            self.now_sec = advanced_simulation['simulation_time_sec']
            self.simulation_finished = advanced_simulation['simulation_finished']
        else:
            ahead_wall_sec = (self.now_sec - target_sec) / self.simulation_speed
            sleep(min(REAL_TIME_RUN_VALUES['maximum_wait_sec'], ahead_wall_sec))

    # ================================================ 발행: 실시간 데이터 파일을 새로 쓰고, 계산된 MCF 탄소배출량을 실행 작업 폴더의 MCF 인스턴스 사본에 적고, 직전 발행 뒤에 생긴 이벤트를 MQTT로 내보냄 ================================================
    def publish(self, is_final_publish):
        real_time_state = simulation_engine.read_real_time_state()
        carbon_emission = simulation_engine.read_carbon_emission()
        real_time_data = api_data_items.real_time_data_items(
            self.now_sec, real_time_state, carbon_emission)
        api_jobs.write_real_time_data(self.job_directory, real_time_data)
        self.mcf_instance_record.record(carbon_emission['mcf_carbon_emissions'])
        stopped_by_request = api_jobs.is_stop_requested(self.job_directory)
        if not (is_final_publish and stopped_by_request):
            self.publish_new_events()
        self.published_sec = self.now_sec
        self.published_wall_sec = time()

    def publish_new_events(self):
        new_events = simulation_engine.read_new_events()
        period = api_data_items.event_period(self.published_sec, self.now_sec)
        topic_names = mqtt_publisher.EVENT_TOPIC_NAMES
        self.event_publisher.publish(
            topic_names['machine'], period,
            api_data_items.machine_event_items(new_events['machine_events']))
        self.event_publisher.publish(
            topic_names['worker_process'], period,
            api_data_items.worker_process_event_items(new_events['worker_process_events']))
        self.event_publisher.publish(
            topic_names['warehouse'], period,
            api_data_items.warehouse_event_items(new_events['warehouse_events']))
        self.event_publisher.publish(
            topic_names['defect'], period,
            api_data_items.defect_event_items(new_events['defect_events']))
        self.event_publisher.publish(
            topic_names['box_completion'], period,
            api_data_items.box_completion_event_items(new_events['box_completion_events']))
