"""The model pool: errors reach the request that made the call. That the
event loop stays free while it works is test_concurrency.py."""

import pytest

from grounded_rag.compute import run_model


@pytest.mark.asyncio
async def test_an_error_in_a_model_call_is_raised_in_the_request():
    def broken():
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await run_model(broken)
