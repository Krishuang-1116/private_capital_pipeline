
from collections import namedtuple

ValidationResult = namedtuple(
    "ValidationResult", ["is_refused", "refusal_message", "query_spec"])


def validate(json_output, context: dict):
    governed_metrics_list = list(context.keys())
    if json_output["metric_name"] not in governed_metrics_list:
        refusal_message = (
            f"I can only answer questions about these metrics: "
            f"{', '.join(governed_metrics_list)}. Try rephrasing your question around one of them."
        )
        return ValidationResult(is_refused=True,
                                refusal_message=refusal_message, query_spec=None)
    else:
        governed_dimensions_list = context[json_output["metric_name"]
                                           ]["valid_dimensions"]
        if json_output["group_by"] is not None and json_output["group_by"] not in governed_dimensions_list:
            refusal_message = (
                f"I can only slice this metric by these dimensions: "
                f"{', '.join(governed_dimensions_list)}. Try one of these dimensions instead."
            )
            return ValidationResult(is_refused=True,
                                    refusal_message=refusal_message, query_spec=None)
        else:
            return ValidationResult(
                is_refused=False, refusal_message=None, query_spec=json_output)
