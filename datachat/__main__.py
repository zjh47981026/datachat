import argparse
import json
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="DataChat local LangChain analyst")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=8766)
    server.add_argument("--data-dir", default=None)
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--ai", action="store_true", help="Actually call local AI for each benchmark question")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve
        serve(args.port, args.data_dir)
    else:
        from .data import DatasetStore
        from .evaluation import evaluate
        from .planner import Planner
        with tempfile.TemporaryDirectory() as folder:
            result = evaluate(DatasetStore(Path(folder)), Planner() if args.ai else None)
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
