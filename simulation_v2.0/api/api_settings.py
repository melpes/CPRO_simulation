from os import cpu_count, getenv
from pathlib import Path


# ================================================ 이 코드가 놓인 simulation_v2.0 폴더: 파일 위치 기본값의 기준 ================================================
SIMULATION_FOLDER = Path(__file__).resolve().parent.parent


# ================================================ 설정에 적는 표시 값: 시뮬레이션 실행기 수를 CPU 수로 정함, 외부 MQTT 브로커 없이 서버가 내장 브로커를 띄움 ================================================
SIMULATION_RUNNER_COUNT_FROM_CPU_COUNT = 0
NO_EXTERNAL_MQTT_BROKER = ''


# ================================================ 환경변수 이름: 바깥과 약속한 설정 키(바꾸지 않음) ================================================
ENVIRONMENT_VARIABLE_NAMES = {
    'model_file_path': 'CPRO_CKPT',
    'aas_data_directory': 'CPRO_AAS_DIR',
    'jobs_directory': 'CPRO_RUNS_DIR',
    'simulation_runner_count': 'CPRO_WORKERS',
    'maximum_jobs_in_progress': 'CPRO_QUEUE_MAX',
    'random_seed': 'CPRO_SEED',
    'default_simulation_speed': 'CPRO_LIVE_SPEED',
    'publish_interval_sec': 'CPRO_LIVE_PUBLISH_SEC',
    'maximum_simulation_period_day': 'CPRO_LIVE_MAX_DAY',
    'mqtt_enabled': 'CPRO_MQTT',
    'mqtt_external_broker_address': 'CPRO_MQTT_BROKER',
    'mqtt_port': 'CPRO_MQTT_PORT',
    'mqtt_embedded_broker_bind_host': 'CPRO_MQTT_BIND',
    'mqtt_topic_prefix': 'CPRO_MQTT_TOPIC',
    'mqtt_qos': 'CPRO_MQTT_QOS',
}


# ================================================ 설정 기본값: 환경변수가 없을 때 쓰는 값 ================================================
DEFAULT_SETTING_VALUES = {
    'model_file_path': str(SIMULATION_FOLDER / 'model' / 'integrated_model.pt'),
    'aas_data_directory': str(SIMULATION_FOLDER / 'aas_data'),
    'jobs_directory': str(SIMULATION_FOLDER / 'result' / 'api_runs'),
    'simulation_runner_count': SIMULATION_RUNNER_COUNT_FROM_CPU_COUNT,
    'maximum_jobs_in_progress': 16,
    'random_seed': 42,
    'default_simulation_speed': 60.0,
    'publish_interval_sec': 1.0,
    'maximum_simulation_period_day': 365.0,
    'mqtt_enabled': True,
    'mqtt_external_broker_address': NO_EXTERNAL_MQTT_BROKER,
    'mqtt_port': 55101,
    'mqtt_embedded_broker_bind_host': '0.0.0.0',
    'mqtt_topic_prefix': '/이벤트-데이터',
    'mqtt_qos': 0,
}


# ================================================ 시뮬레이션 실행기 수를 CPU 수로 정하는 기준: CPU 2개마다 실행기 1개, 1개 이상 4개 이하 ================================================
SIMULATION_RUNNER_COUNT_BY_CPU_COUNT = {
    'cpu_count_per_simulation_runner': 2,
    'minimum': 1,
    'maximum': 4,
    'cpu_count_when_unknown': 2,
}


# ================================================ MQTT 발행을 끄는 환경변수 값 ================================================
MQTT_DISABLING_TEXTS = ['0', 'false', 'False']


# ================================================ 설정 하나 읽기: 환경변수가 있으면 그 값, 없으면 설정 기본값 ================================================
def read_text_setting(setting_name):
    environment_variable_text = getenv(ENVIRONMENT_VARIABLE_NAMES[setting_name])
    if environment_variable_text is None:
        return DEFAULT_SETTING_VALUES[setting_name]
    return environment_variable_text


def read_integer_setting(setting_name):
    environment_variable_text = getenv(ENVIRONMENT_VARIABLE_NAMES[setting_name])
    if environment_variable_text is None:
        return DEFAULT_SETTING_VALUES[setting_name]
    return int(environment_variable_text)


def read_float_setting(setting_name):
    environment_variable_text = getenv(ENVIRONMENT_VARIABLE_NAMES[setting_name])
    if environment_variable_text is None:
        return DEFAULT_SETTING_VALUES[setting_name]
    return float(environment_variable_text)


def read_mqtt_enabled_setting():
    environment_variable_text = getenv(ENVIRONMENT_VARIABLE_NAMES['mqtt_enabled'])
    if environment_variable_text is None:
        return DEFAULT_SETTING_VALUES['mqtt_enabled']
    return environment_variable_text not in MQTT_DISABLING_TEXTS


def read_simulation_runner_count_setting():
    simulation_runner_count = read_integer_setting('simulation_runner_count')
    if simulation_runner_count != SIMULATION_RUNNER_COUNT_FROM_CPU_COUNT:
        return simulation_runner_count
    cpu_count_of_this_computer = cpu_count()
    if not cpu_count_of_this_computer:
        cpu_count_of_this_computer = SIMULATION_RUNNER_COUNT_BY_CPU_COUNT['cpu_count_when_unknown']
    cpu_count_per_simulation_runner = (
        SIMULATION_RUNNER_COUNT_BY_CPU_COUNT['cpu_count_per_simulation_runner'])
    simulation_runner_count = cpu_count_of_this_computer // cpu_count_per_simulation_runner
    simulation_runner_count = min(SIMULATION_RUNNER_COUNT_BY_CPU_COUNT['maximum'],
                                  simulation_runner_count)
    return max(SIMULATION_RUNNER_COUNT_BY_CPU_COUNT['minimum'], simulation_runner_count)


# ================================================ 파일 위치 설정: 저장된 강화학습 모델 파일, 시나리오별 AAS 폴더를 담은 폴더, 실행 작업을 기록하는 폴더 ================================================
MODEL_FILE_PATH = read_text_setting('model_file_path')
AAS_DATA_DIRECTORY = read_text_setting('aas_data_directory')
JOBS_DIRECTORY = Path(read_text_setting('jobs_directory'))


# ================================================ 실행 작업 설정: 미리 띄워 두는 시뮬레이션 실행기 수, 끝나지 않은 실행 작업 수의 상한, 난수 시드 ================================================
SIMULATION_RUNNER_COUNT = read_simulation_runner_count_setting()
MAXIMUM_JOBS_IN_PROGRESS = read_integer_setting('maximum_jobs_in_progress')
RANDOM_SEED = read_integer_setting('random_seed')


# ================================================ 실시간 실행 설정: 요청에 배속이 없을 때의 배속(실시간 1초에 진행하는 시뮬레이션 초), 발행 주기(실시간 초), 요청에 기간이 없을 때의 상한(시뮬레이션 일) ================================================
DEFAULT_SIMULATION_SPEED = read_float_setting('default_simulation_speed')
PUBLISH_INTERVAL_SEC = read_float_setting('publish_interval_sec')
MAXIMUM_SIMULATION_PERIOD_DAY = read_float_setting('maximum_simulation_period_day')


# ================================================ MQTT 설정: 발행 여부, 외부 브로커 주소(host:port), 포트, 내장 브로커가 여는 주소, 토픽 앞머리, QoS ================================================
MQTT_ENABLED = read_mqtt_enabled_setting()
MQTT_EXTERNAL_BROKER_ADDRESS = read_text_setting('mqtt_external_broker_address')
MQTT_PORT = read_integer_setting('mqtt_port')
MQTT_EMBEDDED_BROKER_BIND_HOST = read_text_setting('mqtt_embedded_broker_bind_host')
MQTT_TOPIC_PREFIX = read_text_setting('mqtt_topic_prefix')
MQTT_QOS = read_integer_setting('mqtt_qos')
