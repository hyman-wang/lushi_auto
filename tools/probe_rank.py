# -*- coding: utf-8 -*-
"""读一次盒子排行接口里的传说名次（只读，不点击）。

用法：
    python tools/probe_rank.py          # 现在读一次
    python tools/probe_rank.py --loop   # 每 2s 读一次，直到 Ctrl+C

数据源：盒子 client-home 页面里的 ladder_static（见 src/recommendation/cdp_source.py）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.cdp_source import CdpLadderStatsSource  # noqa: E402


def probe(source: CdpLadderStatsSource) -> None:
    stats = source.ladder_stats()
    if stats is None:
        print(f"读不到（{source.last_error or '接口没返回'}）")
        return
    print(f"段位={stats.get('duanwei')} 名次={stats.get('level')} "
          f"最高={stats.get('max_level')} 赛季={stats.get('season')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="读一次传说名次")
    parser.add_argument("--loop", action="store_true", help="每 2s 读一次")
    args = parser.parse_args()

    source = CdpLadderStatsSource()
    try:
        if not args.loop:
            probe(source)
            return 0
        while True:
            print(time.strftime("%H:%M:%S"), end=" ")
            probe(source)
            time.sleep(2)
    except KeyboardInterrupt:
        return 0
    finally:
        source.close()


if __name__ == "__main__":
    raise SystemExit(main())
