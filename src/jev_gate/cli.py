import argparse
import sys

from . import GATE_VERSION
from .pack import default_pack_path
from .pidfile import replace_previous, write_pid
from .server import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jev-gate",
        description="Thin Jev role gate in front of OpenCodex.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10115)
    parser.add_argument("--upstream", default="http://127.0.0.1:10100")
    parser.add_argument("--pack", default=str(default_pack_path()))
    args = parser.parse_args(argv)
    replace_previous(args.port)
    try:
        httpd, _state = make_server(host=args.host, port=args.port, upstream=args.upstream, pack_path=args.pack)
    except OSError as exc:
        print(
            f"jev-gate could not bind {args.host}:{args.port}: {exc}\n"
            "Stop the old process, or pass --port. Codex App fails with HTTP/1.0 proxies.",
            file=sys.stderr,
        )
        return 1
    write_pid(args.port)
    print(f"jev-gate {GATE_VERSION} http://{args.host}:{args.port} -> {args.upstream}")
    print("GUI: http://%s:%s/" % (args.host, args.port))
    print("Codex openai_base_url: http://%s:%s/v1" % (args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\njev-gate stopped")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
