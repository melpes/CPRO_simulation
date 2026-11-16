from json import dumps, load
from operator import itemgetter
from os import replace
from pathlib import Path
from time import sleep, time
from uuid import uuid4


# ================================================ 실행 작업의 상태 값: 현재 등록값 응답의 '상태'에 그대로 나감 ================================================
JOB_STATUS = {
    'queued': 'queued',
    'running': 'running',
    'done': 'done',
    'failed': 'failed',
}


# ================================================ 실행 작업 폴더 안의 파일 이름: 실행 입력, 상태, 실시간 데이터, 중지 요청 표시, 계산값을 적는 MCF 인스턴스 사본을 두는 폴더 ================================================
JOB_FILE_NAMES = {
    'run_input': 'input.json',
    'status': 'status.json',
    'real_time_data': 'real_time_data.json',
    'stop_request': 'STOP',
    'mcf_instance_folder': 'mcf_instances',
}


# ================================================ 서버와 시뮬레이션 실행기가 같은 파일을 동시에 읽고 쓸 때 다시 시도하는 횟수와 간격(실시간 초) ================================================
FILE_RETRY = {
    'read_count': 5,
    'replace_count': 20,
    'wait_sec': 0.05,
}


# ================================================ 서버가 다시 켜졌을 때 끝나지 않은 실행 작업에 적는 오류 ================================================
INTERRUPTED_JOB_ERROR = {
    'type': 'interrupted',
    'message': '서버 재시작으로 중단됨',
}


# ================================================ JSON 파일 쓰기: 임시 파일에 쓴 뒤 바꿔치기해 읽는 쪽이 쓰다 만 파일을 보지 않게 함 ================================================
def write_json_file(file_path, content):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file_path = file_path.with_name(file_path.name + '.tmp')
    with open(temporary_file_path, 'w', encoding='utf-8') as temporary_file:
        temporary_file.write(dumps(content, ensure_ascii=False))
    for attempt_number in range(FILE_RETRY['replace_count']):
        try:
            replace(temporary_file_path, file_path)
            return
        except PermissionError:
            sleep(FILE_RETRY['wait_sec'])
    replace(temporary_file_path, file_path)


# ================================================ JSON 파일 읽기: 없으면 None, 쓰는 쪽이 바꿔치기하는 중이면 잠깐 기다렸다 다시 읽음 ================================================
def read_json_file(file_path):
    with open(file_path, encoding='utf-8') as json_file:
        return load(json_file)


def read_json_file_if_exists(file_path):
    if not file_path.exists():
        return None
    return read_json_file(file_path)


def read_json_file_being_replaced(file_path):
    for attempt_number in range(FILE_RETRY['read_count']):
        if not file_path.exists():
            return None
        try:
            return read_json_file(file_path)
        except (OSError, ValueError):
            sleep(FILE_RETRY['wait_sec'])
    return None


# ================================================ 실시간 데이터 파일: 시뮬레이션 실행기가 발행 때마다 쓰고 서버의 GET이 읽음 ================================================
def write_real_time_data(job_directory, real_time_data):
    write_json_file(Path(job_directory) / JOB_FILE_NAMES['real_time_data'], real_time_data)


def read_real_time_data(job_directory):
    return read_json_file_being_replaced(Path(job_directory) / JOB_FILE_NAMES['real_time_data'])


# ================================================ 중지 요청: 서버가 실행 작업 폴더에 표시 파일을 만들고 시뮬레이션 실행기가 발행 때마다 확인 ================================================
def request_stop(job_directory):
    job_directory = Path(job_directory)
    if job_directory.exists():
        (job_directory / JOB_FILE_NAMES['stop_request']).touch()


def is_stop_requested(job_directory):
    return (Path(job_directory) / JOB_FILE_NAMES['stop_request']).exists()


# ================================================ 실행 작업 기록: 실행 작업마다 폴더 하나, 끝난 실행 작업은 서버가 다시 켜져도 남음 ================================================
class JobStore:

    def __init__(self, jobs_directory):
        self.jobs_directory = Path(jobs_directory)
        self.jobs_directory.mkdir(parents=True, exist_ok=True)

    def job_directory(self, job_id):
        return self.jobs_directory / job_id

    # ================================================ 실행 작업 만들기: 실행 입력과 처음 상태 기록 ================================================
    def create_job(self, run_input, random_seed):
        job_id = uuid4().hex
        job_directory = self.job_directory(job_id)
        write_json_file(job_directory / JOB_FILE_NAMES['run_input'], run_input)
        status = {
            'job_id': job_id,
            'random_seed': random_seed,
            'status': JOB_STATUS['queued'],
            'created_at': time(),
            'started_at': None,
            'finished_at': None,
            'run_result': None,
            'error': None,
        }
        write_json_file(job_directory / JOB_FILE_NAMES['status'], status)
        return status

    # ================================================ 상태 바꾸기: 실행 중, 완료, 실패 ================================================
    def update_status(self, job_id, changed_items):
        status = self.read_status(job_id)
        status.update(changed_items)
        write_json_file(self.job_directory(job_id) / JOB_FILE_NAMES['status'], status)
        return status

    def mark_running(self, job_id):
        return self.update_status(job_id, {
            'status': JOB_STATUS['running'],
            'started_at': time(),
        })

    def mark_done(self, job_id, run_result):
        return self.update_status(job_id, {
            'status': JOB_STATUS['done'],
            'finished_at': time(),
            'run_result': run_result,
        })

    def mark_failed(self, job_id, error_type, error_message):
        return self.update_status(job_id, {
            'status': JOB_STATUS['failed'],
            'finished_at': time(),
            'error': {'type': error_type, 'message': error_message},
        })

    def fail_unfinished_jobs(self):
        unfinished_statuses = [JOB_STATUS['queued'], JOB_STATUS['running']]
        for status in self.list_statuses_newest_first():
            if status['status'] in unfinished_statuses:
                self.mark_failed(
                    status['job_id'], INTERRUPTED_JOB_ERROR['type'],
                    INTERRUPTED_JOB_ERROR['message'])

    # ================================================ 기록 읽기: 상태, 실행 입력, 만든 시각이 늦은 순서의 상태 목록 ================================================
    def read_status(self, job_id):
        return read_json_file_if_exists(self.job_directory(job_id) / JOB_FILE_NAMES['status'])

    def read_run_input(self, job_id):
        return read_json_file_if_exists(
            self.job_directory(job_id) / JOB_FILE_NAMES['run_input'])

    def list_statuses_newest_first(self):
        statuses = []
        for job_directory in self.jobs_directory.iterdir():
            status_file_path = job_directory / JOB_FILE_NAMES['status']
            if job_directory.is_dir() and status_file_path.exists():
                statuses.append(read_json_file(status_file_path))
        return sorted(statuses, key=itemgetter('created_at'), reverse=True)

    def list_done_statuses_newest_first(self):
        done_statuses = []
        for status in self.list_statuses_newest_first():
            if status['status'] == JOB_STATUS['done']:
                done_statuses.append(status)
        return done_statuses
