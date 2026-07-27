# -*- coding: utf-8 -*-
# API 서버 실행 진입점 —  python run_api.py [--host 0.0.0.0] [--port 8000]  (또는 동결된 exe)
# 상세 설정(워커 수·타임아웃·샘플링 주기 등)은 환경변수로: API.md 참조.
import argparse
import multiprocessing
import os
import sys


def main():
    parser = argparse.ArgumentParser(description='CPRO 시뮬레이션 실행 API 서버')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()

    if getattr(sys, 'frozen', False):
        # exe 배포: AAS(쓰기 대상)·체크포인트·결과는 exe 옆에 둔다 — 번들 내부는 임시·읽기전용
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        os.environ.setdefault('CPRO_AAS_DIR', os.path.join(exe_dir, 'aas_data'))
        os.environ.setdefault('CPRO_CKPT', os.path.join(exe_dir, 'agent_mod.pt'))
        os.environ.setdefault('CPRO_RUNS_DIR', os.path.join(exe_dir, 'result', 'api_runs'))

    import uvicorn
    from api.main import app          # 환경변수 확정 후 import (config 가 env 를 읽는다)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    multiprocessing.freeze_support()   # Windows 동결 exe 의 워커 프로세스 재실행 진입 처리
    main()
