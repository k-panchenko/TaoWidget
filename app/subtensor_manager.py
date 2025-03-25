import os
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

import bittensor as bt


class SubtensorManager:
    def __init__(self):
        self._subtensor: Optional[bt.AsyncSubtensor] = None
        self._network = os.getenv("SUBTENSOR_NETWORK", "archive")

    async def _create_subtensor(self) -> bt.AsyncSubtensor:
        subtensor = bt.AsyncSubtensor(self._network)
        await subtensor.initialize()
        return subtensor

    @asynccontextmanager
    async def get_subtensor(self):
        """Get a subtensor instance, creating a new one if needed or if the current one is disconnected."""
        try:
            if self._subtensor is None:
                self._subtensor = await self._create_subtensor()
            yield self._subtensor
        except (AttributeError, ConnectionError):
            # If we get a connection error or attribute error (ws is None), create a new instance
            if self._subtensor is not None:
                try:
                    await self._subtensor.close()
                except:
                    pass
            self._subtensor = await self._create_subtensor()
            yield self._subtensor
        except Exception:
            # For any other error, close the current instance and create a new one
            if self._subtensor is not None:
                try:
                    await self._subtensor.close()
                except:
                    pass
            self._subtensor = await self._create_subtensor()
            yield self._subtensor

    async def close(self):
        """Close the current subtensor instance if it exists."""
        if self._subtensor is not None:
            try:
                await self._subtensor.close()
            except:
                pass
            self._subtensor = None


async def get_subtensor_manager() -> AsyncGenerator[SubtensorManager, None]:
    manager = SubtensorManager()
    try:
        yield manager
    finally:
        await manager.close() 