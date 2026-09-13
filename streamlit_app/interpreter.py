from __future__ import annotations
import anthropic
from pandas import DataFrame


INTERPRETER_INSTRUCTION = (
    """
You are a query interpretation layer for a governed analytics system.

Your only job is to translate the SQL-generated query results into plain natural English for the users.
The currency being used in this system is defaulted to EUR.
You do not generate SQL. You do not answer questions directly. You only translate a given query result.
"""
)


def interpret(query_result: DataFrame, user_question: str):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        system=INTERPRETER_INSTRUCTION,
        messages=[
            {"role": "user", "content": f"'user_question': {user_question}, 'results': {query_result}"}]
    )
    raw_text = next(
        block.text for block in response.content if block.type == "text")
    return raw_text
