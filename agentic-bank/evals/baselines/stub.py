"""A fake assistant that honours the solution contract, to prove the harness.

`refuse` answers without calling the bank. `pay` pays, on the first turn and
without confirming, the whole remaining amount of the first bill. `oracle` does
the turn's `must_check` reads and then exactly its `executes`.
It talks to the bank through MCP with X-Account-Id, like the real solution, so
the bank records its calls. `/stats` exposes what each POST carried.
"""

import argparse
from pathlib import Path

import uvicorn

from baselines.app import create_app
from harness.adapters.dataset_file import DATASET, load_dataset
from harness.domain.calibration import MODES

BANK_URL = "http://127.0.0.1:8001/mcp"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bank-url", default=BANK_URL)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--delay-s", type=float, default=0.0)
    args = parser.parse_args()
    app = create_app(
        args.mode,
        dataset=load_dataset(args.dataset),
        bank_url=args.bank_url,
        delay_s=args.delay_s,
    )
    print(
        f"stub mode={args.mode} url=http://127.0.0.1:{args.port}"
        f" bank={args.bank_url}"
        " use=POST /chat with X-Account-Id",
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
