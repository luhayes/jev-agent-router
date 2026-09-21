"""One JSON request on stdin, one JSON response on stdout, then exit."""
import asyncio
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from jev_agent_router import ConfigurationError, RouteRequest
from integrations.bridge import decide, options, router_context

MAX_INPUT = 1024 * 1024


async def run(payload, args):
    async with router_context(args.test_only_offline) as router:
        return await decide(router, payload, timeout=args.timeout, test_only=args.test_only_offline)


def main():
    args = options()
    code = 0
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("Input too large")
        payload = json.loads(raw)
        RouteRequest.model_validate(payload)
        result = asyncio.run(run(payload, args))
    except ConfigurationError:
        result, code = {"error": "routing_failed_check_configuration"}, 3
    except (ValueError, ValidationError):
        result, code = {"error": "invalid_request"}, 2
    except TimeoutError:
        result, code = {"error": "timeout"}, 3
    except KeyboardInterrupt:
        result, code = {"error": "cancelled"}, 130
    except Exception:
        result, code = {"error": "routing_failed_check_configuration"}, 3
    print(json.dumps(result, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
