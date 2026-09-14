import re


def render_agg(agg, column):
    '''
    Maps the aggregation method in the query_spec (written in dbt keywords) and the relative column
    to actual SQL syntax

    '''
    if agg == "sum":
        return f"SUM({column})"
    elif agg == "count":
        return f"COUNT({column})"
    elif agg == "average":
        return f"AVG({column})"
    elif agg == "count_distinct":
        return f"COUNT(DISTINCT {column})"


def strip_dimension_wrapper(filter_str):
    '''
    Strips the dbt Jinja syntax to flat SQL syntax, eg, 
    {{ Dimension('fee_line_type') }} = 'invoice' -> fee_line_type = 'invoice'

    '''
    return re.sub(r"\{\{ Dimension\('(\w+)'\) \}\}", r"\1", filter_str)


def compile(query_spec, context):
    metric = query_spec["metric_name"]
    data = context[metric]
    if data["type"] == "simple":
        # e.g. "SUM(fee_amount_eur)" or "COUNT(DISTINCT client_id)"
        agg_expr = render_agg(data["agg"], data["column"])
        time_clause = f"DATE_TRUNC('{query_spec['time_grain']}', {data['time_column']}) AS period," if data[
            'time_column'] and query_spec['time_grain'] else ""
        measure_filter_clause = f" FILTER (WHERE {strip_dimension_wrapper(data['filter'])})" if data[
            'filter'] else ""
        group_by_select = f"{query_spec['group_by']}," if query_spec['group_by'] else ""
        group_by_clause = "GROUP BY 1, 2" if query_spec['group_by'] and data[
            'time_column'] and query_spec['time_grain'] else "GROUP BY 1" if query_spec['group_by'] or (data['time_column'] and query_spec['time_grain']) else ""

        return (f"""
        SELECT
            {time_clause}
            {group_by_select}
            {agg_expr}{measure_filter_clause} AS {metric}
        FROM {data['source_mart']}
        {f"WHERE {query_spec['where']}" if query_spec['where'] else ""}
        {group_by_clause}
        ORDER BY 1
        """
        )
    if data["type"] == "ratio":
        time_clause = f"DATE_TRUNC('{query_spec['time_grain']}', {data['time_column']}) AS period," if data[
            'time_column'] and query_spec['time_grain'] else ""
        num_expr = render_agg(data["numerator"]["agg"],
                              data["numerator"]["column"])
        num_filter_clause = f" FILTER (WHERE {strip_dimension_wrapper(data['numerator']['filter'])})" if data[
            "numerator"]["filter"] else ""
        den_expr = render_agg(
            data['denominator']["agg"], data['denominator']["column"])
        den_filter_clause = f" FILTER (WHERE {strip_dimension_wrapper(data['denominator']['filter'])})" if data[
            'denominator']["filter"] else ""
        group_by_select = f"{query_spec['group_by']}," if query_spec['group_by'] else ""
        group_by_clause = "GROUP BY 1, 2" if query_spec['group_by'] and data[
            'time_column'] and query_spec['time_grain'] else "GROUP BY 1" if query_spec['group_by'] or (data['time_column'] and query_spec['time_grain']) else ""

        return (f"""
        SELECT
            {time_clause}
            {group_by_select}
            {num_expr}{num_filter_clause} * 1.0
                / NULLIF({den_expr}{den_filter_clause}, 0) AS {metric}
        FROM {data['source_mart']}
        {f"WHERE {query_spec['where']}" if query_spec['where'] else ""}
        {group_by_clause}
        ORDER BY 1
        """
        )
