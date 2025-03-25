from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from typing import List
import asyncio
import bittensor as bt
from app.models import HistoricalData
from app.subtensor_manager import SubtensorManager, get_subtensor_manager

router = APIRouter(prefix="/api/v1", tags=["historical"])

BLOCKS_PER_DAY = 7200


async def _get_balance_at_block(subtensor: bt.AsyncSubtensor, coldkey: str, block: int) -> tuple[int, datetime, float]:
    balance = await subtensor.get_balance(coldkey, block)
    timestamp = datetime.now() - timedelta(days=(await subtensor.get_current_block() - block) // BLOCKS_PER_DAY)
    return block, timestamp, balance


async def _get_stake_at_block(subtensor: bt.AsyncSubtensor, coldkey: str, block: int) -> tuple[int, datetime, float]:
    stake = await subtensor.get_stake_for_coldkey(coldkey, block)
    timestamp = datetime.now() - timedelta(days=(await subtensor.get_current_block() - block) // BLOCKS_PER_DAY)
    return block, timestamp, sum(map(lambda x: x.stake if not x.netuid else 0, stake))


@router.get("/balance/{coldkey}", response_model=List[HistoricalData])
async def get_historical_balance(
    coldkey: str,
    days: int = Query(default=7, description="Number of days to look back"),
    subtensor_manager: SubtensorManager = Depends(get_subtensor_manager)
) -> List[HistoricalData]:
    total_blocks = days * BLOCKS_PER_DAY
    
    async with subtensor_manager.get_subtensor() as subtensor:
        current_block = await subtensor.get_current_block()
        blocks = range(current_block, current_block - total_blocks, -BLOCKS_PER_DAY)
        
        # Create tasks for all blocks
        tasks = [_get_balance_at_block(subtensor, coldkey, block) for block in blocks]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks)
        
        # Convert results to HistoricalData objects
        return [
            HistoricalData(block_number=block, timestamp=timestamp, value=value)
            for block, timestamp, value in results
        ]


@router.get("/stake/{coldkey}", response_model=List[HistoricalData])
async def get_historical_stake(
    coldkey: str,
    days: int = Query(default=7, description="Number of days to look back"),
    subtensor_manager: SubtensorManager = Depends(get_subtensor_manager)
) -> List[HistoricalData]:
    total_blocks = days * BLOCKS_PER_DAY
    
    async with subtensor_manager.get_subtensor() as subtensor:
        current_block = await subtensor.get_current_block()
        blocks = range(current_block, current_block - total_blocks, -BLOCKS_PER_DAY)
        
        # Create tasks for all blocks
        tasks = [_get_stake_at_block(subtensor, coldkey, block) for block in blocks]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks)
        
        # Convert results to HistoricalData objects
        return [
            HistoricalData(block_number=block, timestamp=timestamp, value=value)
            for block, timestamp, value in results
        ] 