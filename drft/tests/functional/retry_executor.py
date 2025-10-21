import logging
import time
from typing import Callable, Any, Union, Optional, List

import asyncio
import aiohttp
from aiohttp import ClientTimeout, ClientError, ServerTimeoutError

log = logging.getLogger(__name__)


class RetryExecutor:
    def __init__(self, stats_updater: Callable, retry_delay: float = 1.0):
        self.stats_updater = stats_updater
        self.retry_delay = retry_delay

    async def _handle_timeout_error(
        self,
        error: Union[asyncio.TimeoutError, ServerTimeoutError],
        attempt: int,
        operation_name: str,
        start_time: float,
        max_timeout: float,
        retry_delay: float,
        retry_count: int,
        had_error: bool
    ) -> int:
        elapsed_after_error = time.monotonic() - start_time

        # Check if we have time for another retry
        if elapsed_after_error + retry_delay >= max_timeout:
            log.error(
                f"[RETRY FAILED] {operation_name} timed out on attempt {attempt}, no time for retry "
                f"(elapsed={elapsed_after_error:.2f}s/{max_timeout}s)"
            )
            self.stats_updater(
                operation_name, start_time, retry_count=retry_count + 1, had_timeout=True, had_error=had_error
            )
            raise error

        log.warning(
            f"[RETRY] Attempt {attempt} for {operation_name}  timed out: {str(error)}; "
            f"Elapsed: {elapsed_after_error:.2f}s/{max_timeout}s, Retrying in {retry_delay}s..."
        )

        await asyncio.sleep(retry_delay)
        return retry_count + 1

    async def _handle_connection_error(
        self,
        error: Union[ClientError, aiohttp.ClientConnectionError],
        attempt: int,
        operation_name: str,
        start_time: float,
        max_timeout: float,
        retry_delay: float,
        retry_count: int,
        had_timeout: bool
    ) -> int:
        elapsed_after_error = time.monotonic() - start_time

        if elapsed_after_error + retry_delay >= max_timeout:
            log.error(
                f"[RETRY FAILED] {operation_name} connection error on attempt {attempt}, no time for retry "
                f"(elapsed={elapsed_after_error:.2f}s/{max_timeout}s)"
            )
            self.stats_updater(
                operation_name, start_time, retry_count=retry_count + 1, had_timeout=had_timeout, had_error=True
            )
            raise error

        log.warning(
            f"[RETRY] Attempt {attempt} for {operation_name} failed with error: {str(error)} "
            f"Elapsed: {elapsed_after_error:.2f}s/{max_timeout}s, Retrying in {retry_delay}s..."
        )

        await asyncio.sleep(retry_delay)
        return retry_count + 1

    async def execute(
        self,
        request_func: Callable,
        max_timeout: float,
        request_timeout: float,
        operation_name: str,
        retry_delay: float = None,
        retry_on_statuses: Optional[List[int]] = None,
        on_retry_callback: Optional[Callable] = None,
    ) -> Any:
        """
        Execute async function with retry logic and two-level timeout control.

        Args:
            request_func: Async callable that performs the actual request
            max_timeout: Maximum total time allowed for all attempts
            request_timeout: Timeout for each individual request attempt
            operation_name: Name of the operation for logging/stats
            retry_delay: Delay between retries (defaults to self.retry_delay)
            retry_on_statuses: List of HTTP status codes that should trigger a retry
            on_retry_callback: Optional async callable to be invoked before each retry with signature

        Returns:
            Response from the successful request

        Raises:
            The last exception encountered if all retries fail
        """
        if retry_delay is None:
            retry_delay = self.retry_delay

        start_time = time.monotonic()
        attempt = 1
        last_error = None
        retry_count = 0
        had_timeout = False
        had_error = False

        while True:
            elapsed = time.monotonic() - start_time

            # Check if we've exceeded max timeout
            if elapsed >= max_timeout:
                log.error(
                    f"[RETRY FAILED] {operation_name} exceeded max_timeout after {attempt} attempts and {elapsed:.2f}s"
                )
                if last_error:
                    raise last_error
                raise asyncio.TimeoutError(f"{operation_name} exceeded max_timeout of {max_timeout}s")

            # Calculate remaining time and current attempt timeout
            remaining_time = max_timeout - elapsed
            current_timeout = min(request_timeout, remaining_time)

            try:
                retry_suffix = "[RETRY] " if attempt > 1 else ""
                log.debug(
                    f"{retry_suffix}Attempt {attempt} for {operation_name} (timeout={current_timeout:.2f}s, "
                    f"elapsed={elapsed:.2f}s/{max_timeout}s)"
                )

                response = await asyncio.wait_for(
                    request_func(ClientTimeout(total=current_timeout)), timeout=current_timeout
                )

                if retry_on_statuses and response.status in retry_on_statuses:
                    raise ClientError(f"Received retryable status code: {response.status}")

                # Success!
                total_elapsed = time.monotonic() - start_time
                if attempt > 1:
                    log.info(
                        f"[RETRY SUCCESS] {operation_name} succeeded on  attempt {attempt} after {total_elapsed:.2f}s "
                        f"with {retry_count} retries"
                    )

                self.stats_updater(
                    operation_name, start_time, retry_count=retry_count, had_timeout=had_timeout, had_error=had_error
                )

                return response

            except (asyncio.TimeoutError, ServerTimeoutError, ClientError, aiohttp.ClientConnectionError) as e:
                if on_retry_callback:
                    await on_retry_callback(e, attempt, operation_name)

                last_error = e
                if isinstance(e, (asyncio.TimeoutError, ServerTimeoutError)):
                    had_timeout = True
                    retry_count = await self._handle_timeout_error(
                        e, attempt, operation_name, start_time, max_timeout, retry_delay, retry_count, had_error
                    )
                else:
                    had_error = True
                    retry_count = await self._handle_connection_error(
                        e, attempt, operation_name, start_time, max_timeout, retry_delay, retry_count, had_timeout
                    )
                attempt += 1
