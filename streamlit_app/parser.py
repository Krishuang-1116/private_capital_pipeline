"""
parser.py — builds the governed METRIC_LOOKUP table from models/marts/*.yml
at agent startup.

Reads YAML only. Never touches the database, never computes a metric value —
see docs/v2_ai_agent.md for why that distinction matters. Output is pure
metadata that compiler.py later turns into SQL.

Two passes, per docs/v2_ai_agent_spec.md §3:
  1. parse_semantic_models() — index semantic models BY NAME, each holding
     its own source_mart / agg_time_dimension / entities / dimensions / measures.
     Keeping this keyed per semantic model (not flattened into global pools)
     is what lets step 3 answer "valid_dimensions for THIS metric" correctly
     once there's more than one semantic model in the project.
  2. parse_metrics() — flat list of what each metric needs resolved: its own
     name, its type (simple | ratio), and the measure name(s) it references.
     type matters here because simple and ratio metrics store their measure
     reference(s) under different type_params keys.
  3. build_metric_lookup() — joins the two: for each metric, find which
     semantic model owns its referenced measure(s), and assemble one
     METRIC_LOOKUP entry from that measure's agg/expr/filter plus its owning
     semantic model's source_mart/agg_time_dimension/valid_dimensions.
"""

import glob
import yaml

MARTS_DIR = "models/marts"


def parse_semantic_models(marts_dir=MARTS_DIR):
    """
    Returns: {
        semantic_model_name: {
            "source_mart": str,              # unwrapped from model: ref('...')
            "agg_time_dimension": str,
            # entities + categorical dimensions only
            "valid_dimensions": [str, ...],
                                              # (type: time dimensions excluded —
                                              #  they're handled via time_grain instead)
            "measures": {
                measure_name: {"agg": str, "expr": str, "filter": str | None},
                ...
            },
        },
        ...
    }
    """
    semantic_model_index = {}

    for filepath in glob.glob(f"{marts_dir}/*.yml"):
        with open(filepath) as f:
            content = yaml.safe_load(f)

        if not content or "semantic_models" not in content:
            continue

        for sm in content["semantic_models"]:
            sm_name = sm["name"]

            # TODO: sm["model"] looks like "ref('mart_fee_revenue')" — extract
            # just the mart name (string slicing or a small regex both work)
            source_mart = sm["model"].split("'")[1]

            # TODO: sm["defaults"]["agg_time_dimension"] — some semantic models
            # may not have a "defaults" key at all (check before indexing into it)
            agg_time_dimension = sm.get(
                "defaults", {}).get("agg_time_dimension")

            # TODO: entities — sm["entities"] is a list of {"name": ..., "type": ...}
            # every entity name is a valid group_by value, unconditionally
            entity_names = [entity["name"] for entity in sm["entities"]]

            # TODO: dimensions — sm["dimensions"] is a list of
            # {"name": ..., "type": "categorical" | "time", ...}.
            # Only keep names where type == "categorical" — skip type == "time"
            categorical_dimension_names = [
                dimension["name"] for dimension in sm["dimensions"]if dimension["type"] == "categorical"]

            # TODO: measures — sm["measures"] is a list of
            # {"name": ..., "agg": ..., "expr": ..., "filter": ... (may be absent)}.
            # Build {measure_name: {"agg":..., "expr":..., "filter":...}}.
            # filter is often not present at all — default it to None, don't skip
            # the measure or leave the key out.
            measures = {}
            for measure in sm["measures"]:
                measure_name = measure["name"]
                measures[measure_name] = {
                    "agg": measure["agg"],
                    "expr": measure["expr"],
                    "filter": measure.get("filter")
                }

            semantic_model_index[sm_name] = {
                "source_mart": source_mart,
                "agg_time_dimension": agg_time_dimension,
                "valid_dimensions": entity_names + categorical_dimension_names,
                "measures": measures
            }

    return semantic_model_index


def parse_metrics(marts_dir=MARTS_DIR):
    """
    Returns: [
        {"metric_name": str, "type": "simple", "measure": str},
        {"metric_name": str, "type": "ratio",
            "numerator_measure": str, "denominator_measure": str},
        ...
    ]
    One dict shape for simple metrics, a different one for ratio metrics —
    do not force both into the same "measure" key, since a ratio metric has
    two independent measure references, not one.
    """
    metric_refs = []

    for filepath in glob.glob(f"{marts_dir}/*.yml"):
        with open(filepath) as f:
            content = yaml.safe_load(f)

        if not content or "metrics" not in content:
            continue

        for metric in content["metrics"]:
            metric_name = metric["name"]
            metric_type = metric["type"]  # "simple" | "ratio"

            if metric_type == "simple":
                # pull metric["type_params"]["measure"]
                metric_measure = metric["type_params"]["measure"]

                metric_refs.append({
                    "metric_name": metric_name,
                    "metric_type": metric_type,
                    "measure": metric_measure
                })

            elif metric_type == "ratio":
                # pull metric["type_params"]["numerator"]["measure"]
                # and metric["type_params"]["denominator"]["measure"] — two
                # separate measure names, possibly from two different
                # semantic models (that's the fee_yield case — see below)
                numerator_measure = metric["type_params"]["numerator"]["measure"]
                denominator_measure = metric["type_params"]["denominator"]["measure"]

                metric_refs.append({
                    "metric_name": metric_name,
                    "metric_type": metric_type,
                    "numerator_measure": numerator_measure,
                    "denominator_measure": denominator_measure
                })
            else:
                raise ValueError(
                    f"unknown metric type: '{metric_type}' for metric '{metric_name}'")

    return metric_refs


def build_metric_lookup(marts_dir=MARTS_DIR):
    """
    Joins parse_semantic_models() and parse_metrics(): for each metric,
    find which semantic model(s) declare its referenced measure(s), and
    assemble one METRIC_LOOKUP entry.

    A measure name only tells you the name — you have to search across
    semantic_model_index's measures to find which semantic model declares
    it. For a simple metric this should resolve to exactly one semantic
    model. For a ratio metric, numerator and denominator measures should
    normally resolve to the SAME semantic model (e.g. both live under
    sem_client_retention) — if they resolve to two DIFFERENT semantic
    models instead, that's a cross-model metric (this is exactly what
    makes fee_yield unresolvable in v2 — its numerator measure lives on
    sem_fee_revenue, its denominator measure lives on sem_deal_snapshot).
    Those should be skipped, not silently included with a made-up
    source_mart — see docs/v2_ai_agent_spec.md §3, "Cross-model metrics".
    """
    semantic_model_index = parse_semantic_models(marts_dir)
    metric_refs = parse_metrics(marts_dir)

    lookup = {}

    for ref in metric_refs:
        # for ref["metric_type"] == "simple": find the one semantic model
        # whose "measures" dict contains ref["measure"]; if none found,
        # skip (or log) rather than crashing.
        if ref["metric_type"] == "simple":
            for sm_name, sm_data in semantic_model_index.items():
                if ref["measure"] in sm_data["measures"]:
                    lookup[ref["metric_name"]] = {
                        "source_mart": sm_data["source_mart"],
                        "type": ref["metric_type"],
                        "agg": sm_data["measures"][ref["measure"]]["agg"],
                        "column": sm_data["measures"][ref["measure"]]["expr"],
                        "filter": sm_data["measures"][ref["measure"]]["filter"],
                        "time_column": sm_data["agg_time_dimension"],
                        "valid_dimensions": sm_data["valid_dimensions"]
                    }
                    break  # stop the loop once a metric is found

        #
        # for ref["metric_type"] == "ratio": find the semantic model for
        # numerator_measure and for denominator_measure separately; if
        # they differ, skip this metric (cross-model, v2 excludes it);
        # if they match, assemble a lookup entry with per-side
        # {agg, column (=expr), filter} for numerator and denominator.

        if ref["metric_type"] == "ratio":
            numerator_sm = None
            denominator_sm = None
            num_data = None
            den_data = None

            for sm_name, sm_data in semantic_model_index.items():
                if ref["numerator_measure"] in sm_data["measures"]:
                    numerator_sm = sm_name
                    num_data = sm_data
                    break
            for sm_name, sm_data in semantic_model_index.items():
                if ref["denominator_measure"] in sm_data["measures"]:
                    denominator_sm = sm_name
                    den_data = sm_data
                    break
            if num_data is not None and den_data is not None and numerator_sm == denominator_sm:
                lookup[ref["metric_name"]] = {
                    "source_mart": num_data["source_mart"],
                    "type": ref["metric_type"],
                    "numerator": {
                        "agg": num_data["measures"][ref["numerator_measure"]]["agg"],
                        "column": num_data["measures"][ref["numerator_measure"]]["expr"],
                        "filter": num_data["measures"][ref["numerator_measure"]]["filter"],
                    },
                    "denominator": {
                        "agg": den_data["measures"][ref["denominator_measure"]]["agg"],
                        "column": den_data["measures"][ref["denominator_measure"]]["expr"],
                        "filter": den_data["measures"][ref["denominator_measure"]]["filter"],
                    },
                    "time_column": num_data["agg_time_dimension"],
                    "valid_dimensions": num_data["valid_dimensions"]
                }
    return lookup


if __name__ == "__main__":
    import json
    print(json.dumps(build_metric_lookup(), indent=2))
