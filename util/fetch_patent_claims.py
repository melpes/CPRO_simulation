"""이미 수집한 특허의 청구항(claims)을 추가로 받아 본문 파일에 덧붙인다.

처음 수집할 때 명세서(description) 영역만 뽑아 청구항이 빠졌다.
청구항에는 '~ 내지 ~', '바람직하게는' 같은 파라미터 정의역 표현이 몰려 있어
실시예보다 범위를 잡기에 낫다.

Google Patents 는 요청이 몰리면 차단하므로 12초 간격으로 천천히 받는다.
"""

import glob
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
GAP = 12          # 요청 간격(초)
MARK = "# 청구항"  # 이미 붙였는지 표시

sess = requests.Session()
sess.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(glob.glob(os.path.join(OUT_DIR, "*", "특허", "0*.txt")))
    done = skip = fail = 0

    for f in files:
        txt = open(f, encoding="utf-8").read()
        if MARK in txt:
            skip += 1
            continue
        m = re.search(r"https://patents\.google\.com/patent/(\S+)/ko", txt)
        if not m:
            skip += 1
            continue
        num = m.group(1)

        try:
            r = sess.get(f"https://patents.google.com/patent/{num}/ko", timeout=60)
        except Exception as e:
            print(f"  ! {num} 예외 {str(e)[:40]}")
            fail += 1
            continue
        if r.status_code != 200 or "<title>Sorry" in r.text[:400]:
            print(f"  차단 — {num} 에서 중단 (이번 실행 {done}건)")
            break
        r.encoding = "utf-8"
        sec = BeautifulSoup(r.text, "html.parser").find("section", {"itemprop": "claims"})
        claims = re.sub(r"\n{3,}", "\n\n", sec.get_text("\n", strip=True)) if sec else ""
        if not claims:
            print(f"  - {num} 청구항 없음")
            fail += 1
            time.sleep(GAP)
            continue

        with open(f, "a", encoding="utf-8") as fh:
            fh.write("\n\n" + "=" * 60 + "\n" + MARK + "\n\n" + claims)
        n_range = len(re.findall(r"내지|바람직하게|이상|이하|~", claims))
        print(f"  o {os.path.basename(os.path.dirname(os.path.dirname(f)))[:18]:20} "
              f"{num:16} 청구항 {len(claims):>6}자 / 범위표현 {n_range}")
        done += 1
        time.sleep(GAP)

    print(f"\n청구항 추가 {done}건 / 건너뜀 {skip} / 실패 {fail}")


if __name__ == "__main__":
    main()
