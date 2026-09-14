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


context = load_context()
con = get_connection()

st.title("Ask the Private Capital Metrics")
st.caption(
    "Ask a natural-language question about the private capital metrics you are interested in."
)

user_question = st.text_input("Your question")
submitted = st.button("Submit")

if submitted and user_question:
    # =========================================================================
    # TODO (Kris) — workflow orchestration.
    # Follow the four-step flow in docs/v2_ai_agent_spec.md §2 / §9's app.py
    # pseudocode. Roughly, in order:

    # 1. json_output = translator.translate(user_question, context)
    json_output = translator.translate(
        user_question=user_question, context=context)
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
        sql = compiler.compile(query_spec=result.query_spec, context=context)
        raw_df = con.execute(sql).fetchdf()
        interpretation = interpreter.interpret(raw_df, user_question)

        st.session_state['result'] = {
            "sql": sql,
            "raw_df": raw_df,
            "interpretation": interpretation
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
    st.markdown(st.session_state['result']['interpretation'])
    with st.expander("SQL used"):
        st.code(st.session_state['result']['sql'], language='sql')
    with st.expander("Raw result"):
        st.dataframe(st.session_state['result']['raw_df'])
