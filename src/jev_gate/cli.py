import argparse

from .pack import default_pack_path
from .server import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jev-gate",
        description="Thin Jev role gate in front of OpenCodex.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10111)
    parser.add_argument("--upstream", default="http://127.0.0.1:10100")
    parser.add_argument("--pack", default=str(default_pack_path()))
    args = parser.parse_args(argv)
    httpd, _state = make_server(host=args.host, port=args.port, upstream=args.upstream, pack_path=args.pack)
    print(f"jev-gate http://{args.host}:{args.port} -> {args.upstream}")
    print("GUI /  Codex Base URL: http://%s:%s/v1" % (args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\njev-gate stopped")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
