# -*- coding: utf-8 -*-
"""PCB(SelfManaged 하위조립체) 전용 모듈.

PCB 는 원래 자체 SMT 공정으로 생산되는 SelfManaged entity 다. 본 시뮬은
아직 SMT 라인을 모델링하지 않으므로, '일단' 실제 생산을 다음 stub 으로 대체:

    매 interval 마다 각 PCB 종류 재고 += (라인당 평균 PCB 생산량 × 라인수) / PCB 종류수

→ 전체 PCB 가 종류별로 균등하게 일정 증가. PCB 는 별도 Warehouse 인스턴스에
보관되고(시뮬 코드가 SelfManagedBOM 으로 build), 본 모듈의 코루틴이 그 인스턴스만
채운다. (path_extractor 가 SelfManaged 를 SelfManagedBOM 으로 분리 제공.)

향후 실제 SMT 라인 모듈로 교체될 자리. 그때 본 파일이 SMT 공정 구현을 가짐.
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
