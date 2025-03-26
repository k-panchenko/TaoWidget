from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from typing import List, Dict
import asyncio
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import re
from app.models import DailyData, HistoricalData
from app.subtensor_manager import SubtensorManager, get_subtensor_manager
from collections import defaultdict

router = APIRouter(prefix="/api/v1", tags=["historical"])

# Set the style for all plots
plt.style.use('dark_background')

BLOCKS_PER_DAY = 7200


def shorten_address(address: str) -> str:
    # Remove any non-alphanumeric characters from the start and end
    clean_address = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', address)
    if len(clean_address) <= 12:
        return clean_address
    return f"{clean_address[:6]}...{clean_address[-6:]}"


async def _get_balance_at_block(substrate, coldkey: str, block: int) -> tuple[int, datetime, float]:
    # Query the System.Account storage for the balance
    result = await substrate.query(
        module='System',
        storage_function='Account',
        params=[coldkey],
        block_hash=await substrate.get_block_hash(block)
    )
    balance = result["data"]["free"] / 1e9
    timestamp = datetime.now() - timedelta(days=(await substrate.get_block_number() - block) // BLOCKS_PER_DAY)
    return block, timestamp, balance


async def _get_stake_at_block(substrate, coldkey: str, block: int) -> tuple[int, datetime, float]:
    # Query the runtime API for stake information
    result = await substrate.runtime_call(
        api="StakeInfoRuntimeApi",
        method="get_stake_info_for_coldkey",
        params=[coldkey],
        block_hash=await substrate.get_block_hash(block)
    )
    
    if result.value is None:
        return block, datetime.now(), 0.0
        
    # Sum up all stakes
    total_stake = sum(stake['stake'] for stake in result.value if stake['stake'] > 0)
    stake = total_stake / 1e9  # Convert from Planck to Tao
    
    timestamp = datetime.now() - timedelta(days=(await substrate.get_block_number() - block) // BLOCKS_PER_DAY)
    return block, timestamp, stake


@router.get("/balance/{coldkey}", response_model=List[HistoricalData])
async def get_historical_balance(
    coldkey: str,
    days: int = Query(default=7, description="Number of days to look back"),
    subtensor_manager: SubtensorManager = Depends(get_subtensor_manager)
) -> List[HistoricalData]:
    total_blocks = days * BLOCKS_PER_DAY
    
    async with subtensor_manager.get_subtensor() as substrate:
        current_block = await substrate.get_block_number()
        blocks = range(current_block, current_block - total_blocks, -BLOCKS_PER_DAY)
        
        # Create tasks for all blocks
        tasks = [_get_balance_at_block(substrate, coldkey, block) for block in blocks]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out any exceptions and convert results to HistoricalData objects
        valid_results = [
            result for result in results 
            if not isinstance(result, Exception)
        ]
        
        return [
            HistoricalData(block_number=block, timestamp=timestamp, value=value)
            for block, timestamp, value in valid_results
        ]


@router.get("/stake/{coldkey}", response_model=List[HistoricalData])
async def get_historical_stake(
    coldkey: str,
    days: int = Query(default=7, description="Number of days to look back"),
    subtensor_manager: SubtensorManager = Depends(get_subtensor_manager)
) -> List[HistoricalData]:
    total_blocks = days * BLOCKS_PER_DAY
    
    async with subtensor_manager.get_subtensor() as substrate:
        current_block = await substrate.get_block_number()
        blocks = range(current_block, current_block - total_blocks, -BLOCKS_PER_DAY)
        
        # Execute tasks sequentially
        results = []
        for block in blocks:
            try:
                result = await _get_stake_at_block(substrate, coldkey, block)
                results.append(result)
            except Exception as e:
                print(f"Error getting stake for block {block}: {e}")
                continue
        
        # Convert results to HistoricalData objects
        return [
            HistoricalData(block_number=block, timestamp=timestamp, value=value)
            for block, timestamp, value in results
        ]


@router.get("/balance-history/{coldkey}", response_model=List[DailyData])
async def get_combined_data(
    coldkey: str,
    days: int = Query(default=7, description="Number of days to look back"),
    subtensor_manager: SubtensorManager = Depends(get_subtensor_manager)
) -> List[DailyData]:
    total_blocks = days * BLOCKS_PER_DAY
    
    async with subtensor_manager.get_subtensor() as substrate:
        current_block = await substrate.get_block_number()
        blocks = range(current_block, current_block - total_blocks, -BLOCKS_PER_DAY)
        
        # Get balance data concurrently
        balance_tasks = [_get_balance_at_block(substrate, coldkey, block) for block in blocks]
        balance_results = await asyncio.gather(*balance_tasks, return_exceptions=True)
        valid_balance_results = [
            result for result in balance_results 
            if not isinstance(result, Exception)
        ]
        
        # Get stake data sequentially
        stake_results = []
        for block in blocks:
            try:
                result = await _get_stake_at_block(substrate, coldkey, block)
                stake_results.append(result)
            except Exception as e:
                print(f"Error getting stake for block {block}: {e}")
                continue
        
        # Group data by date
        daily_data: Dict[datetime, Dict[str, float]] = defaultdict(lambda: {"balance": 0.0, "stake": 0.0})
        
        # Process balance results
        for block, timestamp, value in valid_balance_results:
            date = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            daily_data[date]["balance"] = value
        
        # Process stake results
        for block, timestamp, value in stake_results:
            date = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            daily_data[date]["stake"] = value
        
        # Convert to list and sort by date
        return [
            DailyData(
                date=date,
                balance=data["balance"],
                stake=data["stake"]
            )
            for date, data in sorted(daily_data.items())
        ]


@router.get("/chart/{coldkey}")
async def get_chart(
    coldkey: str,
    days: int = Query(default=7, description="Number of days to look back"),
    subtensor_manager: SubtensorManager = Depends(get_subtensor_manager)
) -> StreamingResponse:
    # Get the historical data
    data = await get_combined_data(coldkey, days, subtensor_manager)
    
    if not data:
        return Response(status_code=404, content="No data available for the specified period")
    
    # Create figure with extra space at bottom for legend and sync date
    fig = plt.figure(figsize=(12, 7.5), facecolor='#1a1a1a')
    
    # Create main axis for the chart
    ax = plt.subplot2grid((12, 1), (0, 0), rowspan=10, fig=fig)
    ax.set_facecolor('#1a1a1a')
    
    # Add title with custom styling and shortened address
    title = f"Balance of {shorten_address(coldkey)}"
    ax.set_title(title, pad=20, color='#ffffff', fontsize=14, fontweight='bold')
    
    # Plot balance and stake
    dates = [d.date for d in data]
    balances = [d.balance for d in data]
    stakes = [d.stake for d in data]
    totals = [b + s for b, s in zip(balances, stakes)]
    
    # Plot lines with gradients
    balance_line = ax.plot(dates, balances, label='Free', marker='o', color='#ff4444', linewidth=2, markersize=6)
    stake_line = ax.plot(dates, stakes, label='Staked', marker='o', color='#00ff99', linewidth=2, markersize=6)
    total_line = ax.plot(dates, totals, label='Total', color='#ffaa44', linewidth=2, marker='o', markersize=6)

    # Add grid with custom style
    ax.grid(True, linestyle='--', alpha=0.2, color='#ffffff')
    
    # Customize axes
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('#333333')
    ax.spines['left'].set_color('#333333')
    
    # Format dates on x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    plt.xticks(rotation=0)
    
    # Add labels with custom styling
    ax.set_ylabel('Amount (τ)', color='#999999', fontsize=10)
    
    # Customize tick labels
    ax.tick_params(colors='#999999', grid_alpha=0.3)
    
    # Create a new axis for legend and sync date
    footer_ax = plt.subplot2grid((12, 1), (10, 0), rowspan=2, fig=fig)
    footer_ax.axis('off')
    
    # Add legend
    legend = footer_ax.legend(
        ax.get_legend_handles_labels()[0],
        ax.get_legend_handles_labels()[1],
        loc='center left',
        ncol=3,
        facecolor='#1a1a1a',
        edgecolor='#333333',
        framealpha=0.8,
        fontsize=10,
        borderaxespad=0,
    )
    for text in legend.get_texts():
        text.set_color('#999999')
    
    # Add current balances and sync timestamp
    if data:
        latest = data[-1]
        total = latest.balance + latest.stake
        
        # Add balances with matching colors
        footer_ax.text(
            0.35, 0.5,
            f"Free τ {latest.balance:.3f}",
            fontsize=10,
            color='#ff4444',  # Match Free line color
            ha='left',
            va='center',
            family='monospace'
        )
        footer_ax.text(
            0.5, 0.5,
            f"Staked τ {latest.stake:.3f}",
            fontsize=10,
            color='#00ff99',  # Match Staked line color
            ha='left',
            va='center',
            family='monospace'
        )
        footer_ax.text(
            0.65, 0.5,
            f"Total τ {total:.3f}",
            fontsize=10,
            color='#ffaa44',  # Match Total line color
            ha='left',
            va='center',
            family='monospace'
        )
        
        # Add sync timestamp
        sync_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        footer_ax.text(
            0.98, 0.5,
            f'Sync: {sync_time}',
            fontsize=8,
            color='#666666',
            ha='right',
            va='center',
            alpha=0.8
        )
    
    # Adjust layout
    plt.subplots_adjust(bottom=0.2, top=0.95, left=0.1, right=0.95)
    
    # Save the chart to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300, bbox_inches='tight', facecolor='#1a1a1a')
    plt.close()
    
    # Reset buffer position
    buf.seek(0)
    
    # Return the image
    return StreamingResponse(buf, media_type="image/png") 