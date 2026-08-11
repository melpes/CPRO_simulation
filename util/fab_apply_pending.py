"""docx 에서 되돌린 md 에 반영 대기 항목을 적용한다.

사용자가 docx 에서 손본 내용이 정본이므로, pandoc 으로 md 를 되돌린 뒤
scratch/_fab_반영대기.md 의 항목만 얹는다.
확인 사항은 Ⅰ 에서 걷어내 Ⅳ 체크리스트로 합치고, 체크리스트는 분류별로 다시 나눈다.
"""
import re

SRC = r"C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/docs/FAB/_from_docx.md"
OUT = r"C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/docs/FAB/핵심공정선정_방문자료.md"

s = open(SRC, encoding="utf-8").read()

# ── pandoc 이스케이프 정리 ──────────────────────────────────────────────
s = s.replace(r"\-", "-").replace(r"\~", "~").replace(r"\#", "#")
s = s.replace("GLASS\\_MOVEMENT", "GLASS_MOVEMENT")
s = re.sub(r"`\s*``\s*", "", s)                      # `PR ``도포`` ``및`` ``현상` 같은 깨진 코드펜스
s = s.replace("Spin coater · Spin Developer · PR 도포 및 현상`", "`Spin coater · Spin Developer · PR 도포 및 현상`")
s = re.sub(r"^#\s*$\n\n", "", s, flags=re.M)         # 빈 헤딩
s = re.sub(r"^##\s*$\n\n", "", s, flags=re.M)
s = re.sub(r"^###\s*$\n\n", "", s, flags=re.M)

# ── Ⅰ. 확인 사항 절 제거 (체크리스트로 이관) ────────────────────────────
a = s.index("## 확인 사항")
b = s.index("## 요청 자료 우선순위")
s = s[:a] + s[b:]

# ── Ⅱ. 포토 — Post/Hard bake 택일, 스컴 애싱 표기, 세정 근거 ────────────
old = s[s.index("### 포토\n"):s.index("### 포토 관련 장비 5대")]
new = """### 포토

| 순서 | 세부공정 | 파라미터 | 설비 |
|---|---|---|---|
| 1 | 세정 | (기재 없음) | 기판세정기 |
| 2 | 코팅 | Coating RPM / Time | **현상장비** |
| 3 | 프리베이크 | Prebake Temp. / Time | **현상장비** |
| 4 | 노광 | Exposure (mJ) | **마스크얼라이너** |
| 5 | 현상 | Develop RPM / Time (TMAH 2.38%) | **현상장비** |
| 6 | 포스트베이크 **또는** 하드베이크 | Post bake / Hard bake Temp. · Time | **현상장비** |
| 7 | 스컴 애싱 | O2 50 sccm / 60 sec | **박막증착장비 chC** |

재료 : ZPP1700PG-30(PR) · TMAH 2.38% 수용액(현상액) / 공정 수 : 7

- **6번은 택일** — 6개 공정은 Post bake, 31번(PDL patterning)만 Hard bake
- **7번 스컴 애싱은 4개 공정만** (4 · 18 · 24 · 31)
- 1번 세정은 파라미터가 하나도 없음. `사용장비` 열 나열 순서가 근거

`PR patterning` 1공정이 실제로는 설비 4대를 경유. 현상장비는 노광 전후로 두 번 사용

```
기판세정기 → 현상장비(코팅·프리베이크) → 마스크얼라이너(노광) → 현상장비(현상·포스트베이크) → chC(스컴 애싱)
```

`Wet Cleaner` 가 병기된 공정은 증착 3 (1·2·3) + 포토 7 = 10개. 식각·박리에는 없음

"""
s = s.replace(old, new)

# ── Ⅱ. 세정/제거 — Equipment 단위로 통합 ────────────────────────────────
old = s[s.index("### 세정/제거\n"):s.index("**박리 담당 장비가 자료마다 다름**")]
new = """### 세정/제거

| Equipment | 물리 장비 | 공정 수 | 약액 | 온도 | 시간 | DI 세척 | 후처리 |
|---|---|---|---|---|---|---|---|
| Wet stripper | 엣쳐/스트리퍼 | 5 (6·11·21·26·30) | Organic strip chemical | 50℃ | 100~120 s (일부 U/S) | 120 s | Air knife 2 · Wet cleaning 3 |
| Manual stripper | 엣쳐/스트리퍼 | 2 (16·20) | **NMP** | 60℃ | **10 min + U/S** | 5 min | Wet cleaning |
| Wet Cleaner | 기판세정기 | 부속 | - | - | (runsheet 미기재) | - | - |

- `Air knife` = 공기로 물기 제거(건조) / `Wet cleaning` = 습식 세정. 둘 다 값은 `Standard` 뿐이라 선택 항목으로 보임
- Wet stripper 5공정은 약액·온도·DI세척이 동일. 시간 표기와 후처리만 갈림
- 항목명 표기가 공정마다 일관되지 않음 (`Air knife` / `Wet cleaning`, `(min)` 유무, `with U/S` 유무)

"""
s = s.replace(old, new)

# ── Ⅱ. 챔버 배치 — chC 에 스컴 애싱 병기 ────────────────────────────────
s = s.replace(
    "| chC      | Dry etcher | ASHING 8 · CF4 4 · MO 2 |",
    "| chC      | **건식 식각 + 스컴 애싱** | ASHING 8 · CF4 4 · MO 2 |")

# ── Ⅱ. 포토 장비 5대 — 스핀디벨로퍼 8인치 아님 명시 ─────────────────────
s = s.replace(
    "-   뒤 3종은 runsheet 미등장\n",
    "- 뒤 3종은 runsheet 미등장. **스핀디벨로퍼는 370×470 으로 8인치 라인이 아님** "
    "(8인치 3종 = 스핀 트랙 · 마스크얼라이너(8인치) · PEALD)\n")

# ── Ⅲ. 이상값·번호 기준 주석 ────────────────────────────────────────────
s = s.replace("## 공정 순서 31 (PI 기판)",
              "## 공정 순서 31 (PI 기판)\n\n문서 전체의 공정 번호는 runsheet `PI Run sheet` 를 위에서부터 센 순번")

open(OUT, "w", encoding="utf-8").write(s)
print("본문 적용 완료 :", len(s), "자")
