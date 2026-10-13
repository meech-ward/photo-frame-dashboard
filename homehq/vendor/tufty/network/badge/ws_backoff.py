"""Jittered reconnect backoff for bounded network sessions.

Generic on purpose: nothing here knows about WebSockets, Supabase or Badgeware.
It exists because ~800 badges share one venue network, and an AP blip that drops
them all at once turns an unjittered retry schedule into a synchronized herd
that re-associates, re-handshakes TLS and re-joins in lockstep — repeatedly.
Spreading the retries is the whole job.

The policy owns no clock and never sleeps. A caller that renders frames while it
reconnects cannot afford ``await sleep(30_000)`` inside its loop; it asks for a
delay, stores a deadline, and keeps drawing. Callers that can afford to block are
free to sleep on the returned value instead.

Jitter is a fraction of the exponential base delay:

* ``jitter=0.5`` (the default) draws from ``[base/2, base]`` — "equal jitter";
  spread without the instant-retry storm that a zero floor allows.
* ``jitter=1.0`` draws from ``[0, base]`` — the AWS "full jitter" schedule.
* ``jitter=0`` disables spreading and returns the plain exponential base.
"""

import random


class BackoffPolicy:
    def __init__(
        self,
        initial_ms=1000,
        maximum_ms=30000,
        factor=2.0,
        jitter=0.5,
        random_source=None,
    ):
        self.initial_ms = int(initial_ms)
        self.maximum_ms = int(maximum_ms)
        self.factor = float(factor)
        self.jitter = float(jitter)
        if self.initial_ms < 1:
            raise ValueError("initial backoff must be positive")
        if self.maximum_ms < self.initial_ms:
            raise ValueError("maximum backoff must be at least the initial backoff")
        if self.factor < 1.0:
            raise ValueError("backoff factor must be at least 1.0")
        if self.jitter < 0.0 or self.jitter > 1.0:
            raise ValueError("jitter must be a fraction between 0.0 and 1.0")
        self.random_source = random_source or random.random
        self.attempts = 0
        self.last_delay_ms = None

    def reset(self):
        """Forget the failure history; the next delay starts at the initial one."""

        self.attempts = 0
        self.last_delay_ms = None

    def base_delay_ms(self, attempt=None):
        """The unjittered exponential delay for an attempt, capped at the maximum."""

        attempt = self.attempts if attempt is None else int(attempt)
        if attempt < 0:
            raise ValueError("attempt count cannot be negative")
        value = float(self.initial_ms)
        # Bounded by log(maximum/initial) iterations: the cap ends the loop.
        for _ in range(attempt):
            value *= self.factor
            if value >= self.maximum_ms:
                return self.maximum_ms
        return int(value)

    def next_delay_ms(self):
        """Consume one attempt and return its jittered delay in milliseconds."""

        base = self.base_delay_ms(self.attempts)
        self.attempts += 1
        if self.jitter:
            lower = base * (1.0 - self.jitter)
            base = lower + self.random_source() * (base - lower)
        self.last_delay_ms = max(0, int(base))
        return self.last_delay_ms
