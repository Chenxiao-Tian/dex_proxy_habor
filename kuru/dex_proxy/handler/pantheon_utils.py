# from pantheon import TimestampNs
import time

def get_current_timestamp_ns() -> int:
    """Get current timestamp in nanoseconds since epoch"""
    # return TimestampNs.now().get_ns_since_epoch()
    return int(time.time() * 1_000_000_000)