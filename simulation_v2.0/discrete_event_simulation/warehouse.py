from dataclasses import dataclass


# ================================================ 품목 하나의 재고와 발주 기준: 현재 재고, 최소 재고, 최대 재고, 발주 비율, 발주 중 여부 ================================================
@dataclass
class StockItem:
    present_stock: float
    minimum_stock_quantity: float
    capacity_quantity: float
    replenishment_ratio: float
    on_order: bool = False


# ================================================ 재고 계산식: 발주 기준 재고(최소 재고 × 발주 비율), 한 번에 보충되는 수량(최대 재고 × 발주 비율) ================================================
def reorder_point(minimum_stock_quantity, replenishment_ratio):
    return minimum_stock_quantity * replenishment_ratio


def replenishment_quantity(capacity_quantity, replenishment_ratio):
    return capacity_quantity * replenishment_ratio


def needs_order(stock_item):
    return stock_item.present_stock <= reorder_point(
        stock_item.minimum_stock_quantity, stock_item.replenishment_ratio)


# ================================================ 분류별 품목 재고 만들기: 처음 재고는 최소 재고 ================================================
def generate_stock_items_by_category(item_codes_by_category, stock_policy_by_category):
    stock_items_by_category = {}
    for category_code, item_codes in item_codes_by_category.items():
        stock_policy = stock_policy_by_category[category_code]
        stock_items = {}
        for item_code in item_codes:
            stock_items[item_code] = StockItem(
                present_stock=stock_policy.minimum_stock_quantity,
                minimum_stock_quantity=stock_policy.minimum_stock_quantity,
                capacity_quantity=stock_policy.capacity_quantity,
                replenishment_ratio=stock_policy.replenishment_ratio)
        stock_items_by_category[category_code] = stock_items
    return stock_items_by_category


# ================================================ 자재 사용: 쓴 수량만큼 재고 차감 뒤 발주 기준 재고 이하인 품목을 발주 중으로 바꿔 돌려줌 ================================================
def deduct_stock_and_order(stock_items_by_category, used_quantity_by_item_code, deducts_stock):
    newly_ordered_stock_items = []
    if not deducts_stock:
        return newly_ordered_stock_items
    for item_code, used_quantity in used_quantity_by_item_code.items():
        for stock_items in stock_items_by_category.values():
            if item_code in stock_items:
                stock_items[item_code].present_stock -= used_quantity
                break
    for stock_items in stock_items_by_category.values():
        for stock_item in stock_items.values():
            if needs_order(stock_item) and not stock_item.on_order:
                stock_item.on_order = True
                newly_ordered_stock_items.append(stock_item)
    return newly_ordered_stock_items


# ================================================ 창고: 창고가 재고를 관리하는 품목(CoManagedEntity)과 공장에서 직접 만드는 품목(SelfManagedEntity, PCB)의 재고를 나눠 갖고 inventory로 함께 보여줌 ================================================
class Warehouse:

    def __init__(self, co_managed_item_codes_by_category, self_managed_item_codes_by_category,
                 stock_policy_by_category):
        self.co_managed_stock_items_by_category = generate_stock_items_by_category(
            co_managed_item_codes_by_category, stock_policy_by_category)
        self.self_managed_stock_items_by_category = generate_stock_items_by_category(
            self_managed_item_codes_by_category, stock_policy_by_category)
        self.self_managed_item_codes = set()
        for stock_items in self.self_managed_stock_items_by_category.values():
            self.self_managed_item_codes.update(stock_items)
        self.inventory = {}
        self.inventory.update(self.co_managed_stock_items_by_category)
        self.inventory.update(self.self_managed_stock_items_by_category)

    # ================================================ 자재 사용: 품목을 두 재고로 나눠 차감. 보충할 발주 품목은 창고가 재고를 관리하는 품목에서만 돌려줌 ================================================
    def use_items(self, InputItemCodeList, deducts_stock):
        co_managed_quantity_by_item_code = {}
        self_managed_quantity_by_item_code = {}
        for item_code, input_quantity in InputItemCodeList.items():
            if item_code in self.self_managed_item_codes:
                self_managed_quantity_by_item_code[item_code] = input_quantity
            else:
                co_managed_quantity_by_item_code[item_code] = input_quantity
        newly_ordered_stock_items = []
        if co_managed_quantity_by_item_code:
            newly_ordered_stock_items = deduct_stock_and_order(
                self.co_managed_stock_items_by_category, co_managed_quantity_by_item_code,
                deducts_stock)
        if self_managed_quantity_by_item_code:
            deduct_stock_and_order(
                self.self_managed_stock_items_by_category, self_managed_quantity_by_item_code,
                deducts_stock)
        return newly_ordered_stock_items

    # ================================================ 입고·보충: 보충 소요시간 뒤 발주 품목 입고. 입고 뒤에도 발주 기준 재고 이하이면 다시 발주 ================================================
    def replenish_items(self, simpy_environment, replenishment_lead_time_sec,
                        ordered_stock_items, notify_stock_arrival):
        yield simpy_environment.timeout(replenishment_lead_time_sec)
        for stock_item in ordered_stock_items:
            stock_item.present_stock += replenishment_quantity(
                stock_item.capacity_quantity, stock_item.replenishment_ratio)
            stock_item.on_order = False
            if needs_order(stock_item):
                stock_item.on_order = True
                simpy_environment.process(self.replenish_items(
                    simpy_environment, replenishment_lead_time_sec, [stock_item],
                    notify_stock_arrival))
        notify_stock_arrival()

    # ================================================ SMT 라인이 만든 PCB 입고 알림: PCB 수량은 시뮬레이션 모델의 PCB 재고가 관리하므로 여기서는 하는 일 없음(API의 입출고 기록이 이 메서드를 덮어씀) ================================================
    def record_produced_items(self, produced_quantity_by_item_code):
        pass
