import anthropic
import json

TRANSLATOR_INSTRUCTION = (
    """
You are a query translation layer for a governed analytics system.

Your only job is to extract a structured JSON object from the user's question.
You do not generate SQL. You do not answer questions directly. You only classify intent.

Governed metrics (the only valid values for metric_name):
{governed_metrics_list}
Per-metric governed dimensions list: 
{governed_dimensions_list}
Some dimensions take special forms. client_id: CXXX(X being numbers). billing_period_label: YYYY-MM. cohort_quarter: YYYY-QN (Q being quarter, N being numbers from 1 to 4).
Other dimensions have a list of predefined values:
{dimension_values_list}

Output format — return ONLY valid JSON, no preamble, no explanation:
{{
  "metric_name": "<one of the governed metrics above, or UNGOVERNED>",
  "group_by": "<dimension name as a string, or null if not specified>",
  "where": "<SQL-style filter condition as a string, or null if not specified>",
  "time_grain": "<month | quarter | year, inferred from the question,
                  or null if not specified>"
}}

If the user's question cannot be mapped to any governed metric, set metric_name to
UNGOVERNED and leave all other fields null. Do not approximate or suggest alternatives.

"""

)


def translate(user_question: str, context: dict, dimension_values: dict):
    governed_metrics_list = ",".join(context.keys())
    governed_dimensions_list = "\n".join(
        f"metric: {k}, dimensions: {v.get('valid_dimensions')}" for k, v in context.items()
    )
    dimension_values_list = "\n".join(
        f"dimension: {k}, values: {v}"for k, v in dimension_values.items())
    formatted_prompt = TRANSLATOR_INSTRUCTION.format(
        governed_metrics_list=governed_metrics_list,
        governed_dimensions_list=governed_dimensions_list,
        dimension_values_list=dimension_values_list)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        system=formatted_prompt,
        messages=[{"role": "user", "content": user_question}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": ["object"],
                    "properties": {
                        "metric_name": {"type": "string"},
                        "group_by": {"type": ["string", "null"]},
                        "where": {"type": ["string", "null"]},
                        "time_grain": {"type": ["string", "null"]}
                    },
                    "required": ["metric_name", "group_by", "where", "time_grain"],
                    "additionalProperties": False
                }
            }}
    )
    raw_text = next(
        block.text for block in response.content if block.type == "text")
    parsed = json.loads(raw_text)
    return parsed
