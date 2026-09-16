from dotenv import load_dotenv

import streamlit as st
import duckdb

import parser
import translator
import validator
import compiler
import interpreter


DB_PATH = "dev.duckdb"
DB_SCHEMA = "dbt_pc_pipeline"

load_dotenv()

st.set_page_config(
    page_title="Ask the Private Capital Metrics", layout="centered")

if "result" not in st.session_state:
    st.session_state['result'] = None


@st.cache_resource
def load_context():
    """
    parser.build_metric_lookup() re-reads and re-walks every models/marts/*.yml
    file from scratch. Streamlit reruns this entire script top-to-bottom on
    every widget interaction (every button click, every text input change) —
    without caching, that YAML walk would repeat on every single question
    submitted in a session, not just once at startup.
    st.cache_resource runs this function once per session and hands back the
    same object on every rerun. Use cache_resource (not cache_data) for things
    like this that aren't plain serializable data — see get_connection() below
    for the same reasoning applied to the DuckDB connection.
    """
    return parser.build_metric_lookup()


@st.cache_resource
def get_connection():
    """One DuckDB connection per session, opened once — not one per question."""
    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute(f"SET search_path = '{DB_SCHEMA}'")
    return con


@st.cache_data
def get_dimension_value_hints(_con):
    dimensions = ['fee_basis', 'service_id', 'fee_line_type', 'is_paid']
    dimension_value = {}
    for dimension in dimensions:
        values = _con.execute(
            f"SELECT DISTINCT {dimension} FROM mart_fee_revenue").fetchall()
        # each row is a tuple of one-element
        dimension_value[dimension] = [row[0] for row in values]

    return dimension_value


context = load_context()
con = get_connection()
dimension_value_hints = get_dimension_value_hints(con)


st.title("Ask the Private Capital Metrics")
st.caption(
    "Ask a natural-language question about the private capital metrics you are interested in."
)


# Example questions, one per governed metric — derived from context so this
# list can't drift out of sync with the actual governed metric list.
# accept_new_options=True makes this a real combobox: clicking it opens a
# dropdown of the examples, but the user can also just type their own
# question — either way, nothing happens until Submit is clicked. This
# replaces the earlier button-row design, which had the example click itself
# trigger the backend call, bypassing Submit as the single gateway.
metric_names = list(context.keys())
example_questions = [
    f"What is the {name.replace('_', ' ')}?" for name in metric_names]

user_question = st.selectbox(
    "Your question",
    options=example_questions,
    index=None,
    accept_new_options=True,
    placeholder="Type your own question, or pick an example",
    key="user_question_input",
)

col_submit, col_clear = st.columns([1, 1])
submitted = col_submit.button("Submit", use_container_width=True)
# TODO (Kris) — "Clear" button, write-first, take 2. Same on_click-callback
# pattern needed here as any other keyed-widget reset (there's no example
# left in this file to crib from anymore, but the shape is: a function that
# sets session_state directly, passed as on_click=... rather than checked
# after the fact). Two things changed from your first attempt:
#   1. The widget is now a selectbox, not a text_input — its "empty" value
#      is None, not "".
#   2. It still needs to reset st.session_state['result'] too.


def _clear_all():
    st.session_state["user_question_input"] = None
    st.session_state["result"] = None


col_clear.button("Clear", on_click=_clear_all, use_container_width=True)


if submitted and user_question:
    # =========================================================================
    # TODO (Kris) — workflow orchestration.
    # Follow the four-step flow in docs/v2_ai_agent_spec.md §2 / §9's app.py
    # pseudocode. Roughly, in order:

    # 1. json_output = translator.translate(user_question, context)
    # Wrapped in a spinner — this block makes 1-2 live LLM calls plus a DB
    # round trip, so the page would otherwise sit blank with no feedback.
    with st.spinner("Thinking..."):
        json_output = translator.translate(
            user_question=user_question, context=context, dimension_values=dimension_value_hints)
        #
        # 2. result = validator.validate(json_output, context)
        result = validator.validate(json_output=json_output, context=context)
        #
        # 3. Branch on result.is_refused:
        #      - refused  -> display result.refusal_message (st.warning or
        #                    st.error), stop here — no SQL, no further calls.
        #      - accepted -> continue to step 4.
        # 4. sql = compiler.compile(result.query_spec, context)
        #    raw_df = con.execute(sql).fetchdf()
        #    NOTE: a DuckDB result object is single-consumption — .fetchall()
        #    or .fetchdf() drains it. Since both interpreter.interpret() and
        #    the "Raw result" expander below need the data, materialize it
        #    into raw_df ONCE here and reuse that variable for both — don't
        #    call .execute() or .fetchdf() a second time.
        #    interpretation = interpreter.interpret(raw_df, user_question)
        if result.is_refused:
            st.error(result.refusal_message)
            st.session_state['result'] = None
        else:
            sql = compiler.compile(
                query_spec=result.query_spec, context=context)
            raw_df = con.execute(sql).fetchdf()
            interpretation = interpreter.interpret(raw_df, user_question)

            metric_name = result.query_spec["metric_name"]
            st.session_state['result'] = {
                "sql": sql,
                "raw_df": raw_df,
                "interpretation": interpretation,
                # carried through for display formatting below — whether
                # this metric reads as currency (simple = SUM of a EUR
                # column) or a ratio (dimensionless, shown as a percentage)
                "metric_name": metric_name,
                "metric_type": context[metric_name]["type"],
            }
            #
            # 5. Display (only reached on the accepted path):
            #      - interpretation, as the primary result (st.write / st.markdown)
            #      - an expandable "SQL used" section showing `sql`
            #        (st.expander(...) containing st.code(sql, language="sql"))
            #      - an expandable "Raw result" section showing `raw_df`
            #        (st.expander(...) containing st.dataframe(raw_df))
            #    Per spec §11, both expanders are a deliberate trust signal — not
            #    hidden debug output — so they should sit right alongside the
            #    interpretation, not be left out.
            # =========================================================================


if st.session_state['result'] is not None:
    result_state = st.session_state['result']
    raw_df = result_state['raw_df']
    metric_name = result_state['metric_name']
    # simple metrics are a SUM of a EUR column (currency); ratio metrics are
    # dimensionless (percentage) — see the description table in
    # docs/data_spec_v2.md §5.2 for why this split holds for all 6 governed
    # metrics today. Revisit this if a future metric doesn't fit either mold.
    is_currency = result_state['metric_type'] == 'simple'

    st.markdown(result_state['interpretation'])

    # A single row with only the metric column (no group_by, no time_grain)
    # is the "all-time, no breakdown" case — show it as a real stat tile
    # instead of making the user open an expander to see one number.
    if raw_df.shape == (1, 1):
        scalar_value = raw_df.iloc[0, 0]
        formatted_value = (
            f"€{scalar_value:,.2f}" if is_currency else f"{scalar_value:.1%}"
        )
        st.metric(label=metric_name.replace('_', ' ').title(),
                  value=formatted_value)

    with st.expander("SQL used"):
        st.code(result_state['sql'], language='sql')
    with st.expander("Raw result"):
        column_config = {
            metric_name: st.column_config.NumberColumn(
                format='euro' if is_currency else 'percent'
            )
        }
        st.dataframe(raw_df, column_config=column_config)
