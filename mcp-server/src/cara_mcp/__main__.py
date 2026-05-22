"""CLI entrypoint for the CARA MCP server.

Usage:
    python -m cara_mcp --transport stdio
    python -m cara_mcp --transport http --port 8500
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="cara-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport (default: stdio for Claude Desktop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8500,
        help="HTTP port if --transport http",
    )
    args = parser.parse_args()

    from cara_mcp.server import run

    return run(transport=args.transport, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
