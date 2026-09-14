
from collections import namedtuple

ValidationResult = namedtuple(
    "ValidationResult", ["is_refused", "refusal_message", "query_spec"])


def validate(json_output, context: dict):
    governed_metrics_list = list(context.keys())
    if json_output["metric_name"] not in governed_metrics_list:
        refusal_message = f"The metric you are querying is not a valid one from the {governed_metrics_list}."
        return ValidationResult(is_refused=True,
                                refusal_message=refusal_message, query_spec=None)
    else:
        governed_dimensions_list = context[json_output["metric_name"]
                                           ]["valid_dimensions"]
        if json_output["group_by"] is not None and json_output["group_by"] not in governed_dimensions_list:
            refusal_message = f"The dimension you are querying is not a valid one from the {governed_dimensions_list}."
            return ValidationResult(is_refused=True,
                                    refusal_message=refusal_message, query_spec=None)
        else:
            return ValidationResult(
                is_refused=False, refusal_message=None, query_spec=json_output)
