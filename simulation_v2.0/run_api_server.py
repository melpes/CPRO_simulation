import argparse
import multiprocessing

import uvicorn

from api import api_server


# ================================================ 서버가 여는 주소의 기본값: 모든 주소에서 받음, 포트 55100(API 명세의 고정값). MQTT 브로커 포트와 그 밖의 설정은 환경변수(api/api_settings.py 맨 위) ================================================
DEFAULT_SERVER_ADDRESS = {
    'host': '0.0.0.0',
    'port': 55100,
}


# ================================================ 명령줄 입력: 서버가 여는 주소와 포트 ================================================
def read_command_line_arguments():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('--host', default=DEFAULT_SERVER_ADDRESS['host'])
    argument_parser.add_argument('--port', type=int, default=DEFAULT_SERVER_ADDRESS['port'])
    return argument_parser.parse_args()


# ================================================ 실행: API 서버 시작. 서버가 뜰 때 시뮬레이션 실행기 프로세스가 AAS와 저장된 강화학습 모델을 불러 둠 ================================================
def main():
    arguments = read_command_line_arguments()
    uvicorn.run(api_server.app, host=arguments.host, port=arguments.port)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
