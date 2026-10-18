"""Create a run-owned async loop without changing process-wide policy."""

import asyncio


def create_event_loop() -> asyncio.AbstractEventLoop:
    # uvloop remains optional. Construct its loop directly instead of installing
    # a policy that would affect unrelated callers after this run has finished.
    try:
        import uvloop
    except ImportError:
        return asyncio.new_event_loop()
    return uvloop.new_event_loop()
