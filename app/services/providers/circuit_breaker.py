import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GiftHubException
from app.core.logging import get_logger
from app.models.provider import CircuitState, ProviderHealth, ProviderStatus

logger = get_logger(__name__)


class ProviderUnavailableError(GiftHubException):
    pass


class CircuitBreaker:
    """
    In-memory and DB-backed circuit breaker for payment and fulfillment providers.
    Trips from CLOSED -> OPEN after consecutive failures.
    Allows probe requests in HALF_OPEN after cooldown.
    """
    FAILURE_THRESHOLD = 5
    COOLDOWN_SECONDS = 60

    def __init__(self):
        # In-memory fast cache: provider_name -> {state, consecutive_failures, last_failure_ts, last_probe_ts}
        self._states: Dict[str, dict] = {}

    def _get_or_init_state(self, provider_name: str) -> dict:
        if provider_name not in self._states:
            self._states[provider_name] = {
                "state": CircuitState.CLOSED.value,
                "consecutive_failures": 0,
                "last_failure_ts": 0.0,
                "last_probe_ts": 0.0
            }
        return self._states[provider_name]

    def get_state(self, provider_name: str) -> CircuitState:
        """Returns the current circuit state for the specified provider."""
        st = self._get_or_init_state(provider_name)
        try:
            return CircuitState(st["state"])
        except Exception:
            return CircuitState.CLOSED

    def can_execute(self, provider_name: str) -> bool:
        """Checks if a call to the provider is permitted."""
        st = self._get_or_init_state(provider_name)
        state = st["state"]

        if state == CircuitState.CLOSED.value:
            return True

        if state == CircuitState.OPEN.value:
            now = time.time()
            if now - st["last_failure_ts"] >= self.COOLDOWN_SECONDS:
                # Cooldown elapsed, enter HALF_OPEN probe mode
                st["state"] = CircuitState.HALF_OPEN.value
                st["last_probe_ts"] = now
                logger.info(f"Circuit for provider '{provider_name}' transitioned to HALF_OPEN (testing recovery)")
                return True
            return False

        if state == CircuitState.HALF_OPEN.value:
            # Only allow limited probe traffic
            now = time.time()
            if now - st.get("last_probe_ts", 0) > 5.0:
                st["last_probe_ts"] = now
                return True
            return False

        return False

    def record_success(self, provider_name: str) -> None:
        """Records a successful provider interaction and closes circuit if recovering."""
        st = self._get_or_init_state(provider_name)
        if st["state"] != CircuitState.CLOSED.value:
            logger.info(f"Provider '{provider_name}' succeeded. Resetting circuit to CLOSED (HEALTHY)")
        st["state"] = CircuitState.CLOSED.value
        st["consecutive_failures"] = 0

    def record_failure(self, provider_name: str, error: str) -> None:
        """Records provider failure and trips circuit if threshold exceeded."""
        st = self._get_or_init_state(provider_name)
        st["consecutive_failures"] += 1
        st["last_failure_ts"] = time.time()

        if st["consecutive_failures"] >= self.FAILURE_THRESHOLD:
            if st["state"] != CircuitState.OPEN.value:
                logger.error(
                    f"Circuit breaker TRIPPED to OPEN for provider '{provider_name}' "
                    f"after {st['consecutive_failures']} consecutive failures. Error: {error}"
                )
            st["state"] = CircuitState.OPEN.value

    async def sync_to_db(self, session: AsyncSession, provider_name: str, error: Optional[str] = None, is_success: bool = True) -> None:
        """Persists provider health statistics to the database."""
        try:
            ph = await session.get(ProviderHealth, provider_name)
            now = datetime.now(timezone.utc)
            if not ph:
                ph = ProviderHealth(
                    provider_name=provider_name,
                    status=ProviderStatus.HEALTHY.value,
                    circuit_state=CircuitState.CLOSED.value,
                    failure_count=0,
                    success_count=0,
                    consecutive_failures=0
                )
                session.add(ph)

            st = self._get_or_init_state(provider_name)
            ph.circuit_state = st["state"]

            if is_success:
                ph.success_count += 1
                ph.consecutive_failures = 0
                ph.last_success_at = now
                if ph.status != ProviderStatus.DISABLED.value:
                    ph.status = ProviderStatus.HEALTHY.value
            else:
                ph.failure_count += 1
                ph.consecutive_failures = st["consecutive_failures"]
                ph.last_failure_at = now
                if ph.consecutive_failures >= self.FAILURE_THRESHOLD and ph.status != ProviderStatus.DISABLED.value:
                    ph.status = ProviderStatus.DEGRADED.value

            await session.flush()
        except Exception as e:
            logger.warning(f"Could not persist provider health for {provider_name}: {e}")

    async def is_provider_available(self, session: AsyncSession, provider_name: str) -> Tuple[bool, str]:
        """Checks DB admin status + in-memory circuit breaker."""
        ph = await session.get(ProviderHealth, provider_name)
        if ph:
            if ph.status == ProviderStatus.DISABLED.value:
                return False, f"Provider '{provider_name}' is disabled: {ph.disabled_reason or 'Administrator action'}"

        if not self.can_execute(provider_name):
            return False, f"Provider '{provider_name}' circuit breaker is OPEN (temporary outage)"

        return True, "OK"


circuit_breaker = CircuitBreaker()
