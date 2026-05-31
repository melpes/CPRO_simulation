# -*- coding: utf-8 -*-
"""SMT 라인 전용 모듈 (PCB SelfManaged 보충 + SMT 공정 구현).

PCB 는 SelfManaged 하위조립체로 자체 SMT 공정에서 생산된다. 본 모듈은
SMT 라인 [Loader → ScreenPrinter → SPI → Mounter(×2 기종) → Reflow →
AOI → Unloader] 를 모델링해, PCB 별도 Warehouse 를 채운다.

현재는 stub 코루틴(`pcb_supply`) — 라인당 평균 생산량을 매 interval 마다
종류별로 균등 증가시킨다. 이 stub 자리에 실제 설비 단위 SMT 공정이 들어갈
예정 (Loader/Printer/SPI/Mounter/Reflow/AOI/Unloader IDEF0 → simpy 코루틴).

(path_extractor 가 SelfManaged 를 SelfManagedBOM 으로 분리 제공.)
"""
from __future__ import annotations

# TODO: 실제 SMT 라인 평균 PCB 생산량 출처(AAS/공정데이터) 확정 시 교체.
#       현재는 stub 상수. 단위 = PCB개 / 라인 / SUPPLY_INTERVAL_SEC.
AVG_PCB_PER_LINE   = 100.0
N_SMT_LINES        = 2
SUPPLY_INTERVAL_SEC = 3600.0      # 1 시뮬-시간마다 보충


def pcb_supply(env, pcb_warehouse,
               avg_pcb_per_line: float = AVG_PCB_PER_LINE,
               n_lines: int = N_SMT_LINES,
               interval: float = SUPPLY_INTERVAL_SEC):
    """PCB 창고 전용 일정증가 코루틴. env.process() 로 등록.

    pcb_warehouse : SelfManagedBOM 으로 build 된 Warehouse 인스턴스
                    (구조는 일반 Warehouse 와 동일, PCB 만 담김)
    """
    items = [(Category, item_code)
             for Category, codes in pcb_warehouse.inventory.items()
             for item_code in codes]
    n_types = len(items) or 1
    increment = avg_pcb_per_line * n_lines / n_types     # 종류별 매 interval 증가량
    while True:
        yield env.timeout(interval)
        for Category, item_code in items:
            pcb_warehouse.inventory[Category][item_code].present_stock += increment
