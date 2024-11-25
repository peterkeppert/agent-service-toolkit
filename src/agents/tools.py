import asyncio
import math
import re

import numexpr
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from agents.bg_task_agent.task import Task


async def calculator_func(expression: str, config: RunnableConfig) -> str:
    """Calculates a math expression using numexpr.

    Useful for when you need to answer questions about math using numexpr.
    This tool is only for math questions and nothing else. Only input
    math expressions.

    Args:
        expression (str): A valid numexpr formatted math expression.

    Returns:
        str: The result of the math expression.
    """
    task1 = Task("Simple task 1...")
    await task1.start(config=config)
    try:
        local_dict = {"pi": math.pi, "e": math.e}
        output = str(
            numexpr.evaluate(
                expression.strip(),
                global_dict={},  # restrict access to globals
                local_dict=local_dict,  # add common mathematical functions
            )
        )
        await asyncio.sleep(2)
        await task1.finish(result="success", config=config, data={"output": output})
        return re.sub(r"^\[|\]$", "", output)
    except Exception as e:
        await task1.finish(result="error", config=config, data={"output": "error"})
        raise ValueError(
            f'calculator("{expression}") raised error: {e}.'
            " Please try again with a valid numerical expression"
        )


calculator: BaseTool = tool(calculator_func)
calculator.name = "Calculator"
