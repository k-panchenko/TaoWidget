import os
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator
from async_substrate_interface import AsyncSubstrateInterface


class SubtensorManager:
    def __init__(self):
        self._substrate: Optional[AsyncSubstrateInterface] = None
        self._network = os.getenv("SUBTENSOR_NETWORK", "archive")
        self._url = os.getenv("SUBTENSOR_URL", "wss://archive.chain.opentensor.ai:443")

    async def _create_substrate(self) -> AsyncSubstrateInterface:
        substrate = AsyncSubstrateInterface(
            url=self._url,
            ss58_format=42,
            use_remote_preset=True,
            chain_name="Bittensor",
        )
        await substrate.initialize()
        return substrate

    @asynccontextmanager
    async def get_subtensor(self):
        """Get a substrate instance, creating a new one if needed or if the current one is disconnected."""
        substrate = None
        try:
            if self._substrate is None:
                self._substrate = await self._create_substrate()
            substrate = self._substrate
            yield substrate
        except Exception:
            # For any error, close the current instance and create a new one
            if self._substrate is not None:
                try:
                    await self._substrate.close()
                except:
                    pass
                self._substrate = None
            self._substrate = await self._create_substrate()
            yield self._substrate
        finally:
            # Only close if this is a temporary instance created during error recovery
            if substrate is not self._substrate:
                try:
                    await substrate.close()
                except:
                    pass

    async def close(self):
        """Close the current substrate instance if it exists."""
        if self._substrate is not None:
            try:
                await self._substrate.close()
            except:
                pass
            self._substrate = None


async def get_subtensor_manager() -> AsyncGenerator[SubtensorManager, None]:
    manager = SubtensorManager()
    try:
        yield manager
    finally:
        await manager.close() 