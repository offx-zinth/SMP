"""Services: Scheduler — The Abyss Step 01."""

from smp.demo.mega_test.chain.step_02 import step_02
from smp.demo.mega_test.core.base_engine import BaseProcessor

processor = BaseProcessor()


def run_scheduled_task(task_data: dict):
    """Top-level scheduler that kicks off processing and the chain."""
    result = processor.execute_logic(task_data)
    chain_result = step_02()
    return {"scheduled": result, "chain": chain_result}
