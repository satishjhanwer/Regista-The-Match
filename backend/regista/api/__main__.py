"""python -m regista.api [--host 0.0.0.0] [--port 8000]"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(prog="regista.api")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run("regista.api.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
