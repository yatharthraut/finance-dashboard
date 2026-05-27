"""Claude chat with a read-only SQL tool over the finance database.

Instead of dumping a fixed context, the model is given:
  * a data-access guide ("skill") describing the ai_* views and conventions, and
  * a ``query_finances`` tool that runs ONE read-only SELECT and returns CSV.

The model queries the smallest data it needs (aggregate views by default,
individual transactions only when necessary), which keeps token costs low. The
guide is sent as a cached system block so it's paid for once per cache window.
"""

from __future__ import annotations

import csv
import io
import pathlib
import sqlite3
from datetime import date

from utils.config import settings

# The "skill" the model follows whenever it accesses the data.
DATA_GUIDE = pathlib.Path(__file__).with_name("data_guide.md").read_text(encoding="utf-8")

SYSTEM_PROMPT = (
    "You are a financial analyst for the user's personal finances. You have a "
    "read-only SQL tool (query_finances) over their data. Always follow the data "
    "access guide. Query the smallest amount of data needed to answer — prefer "
    "the aggregate views and only pull individual transactions when necessary. "
    "Cite concrete numbers from the results, and if the data can't answer, say so."
)

MAX_ROWS = 200          # cap rows returned to the model per query
MAX_CHARS = 8000        # hard cap on a single tool result
MAX_TOOL_TURNS = 6      # safety bound on the agentic loop

TOOLS = [
    {
        "name": "query_finances",
        "description": (
            "Run ONE read-only SQL SELECT against the personal-finance SQLite "
            "database and get rows back as CSV. Use the ai_* views from the data "
            "guide. Filter and LIMIT to keep results small."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single read-only SELECT (or WITH ... SELECT) statement.",
                }
            },
            "required": ["sql"],
        },
    }
]

_BANNED = {
    "insert", "update", "delete", "drop", "alter", "attach", "detach",
    "create", "replace", "pragma", "vacuum", "reindex", "truncate",
}


def _validate_select(sql: str) -> tuple[str | None, str | None]:
    """Return (clean_sql, None) if a safe read-only SELECT, else (None, error)."""
    sql = (sql or "").strip().rstrip(";").strip()
    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return None, "ERROR: only read-only SELECT queries are allowed."
    if ";" in sql:
        return None, "ERROR: only a single statement is allowed."
    tokens = set(low.replace("(", " ").replace(")", " ").replace(",", " ").split())
    if tokens & _BANNED:
        return None, "ERROR: read-only queries only."
    if "access_token" in low:
        return None, "ERROR: that table is not accessible."
    return sql, None


def _readonly_conn():
    # Read-only connection — writes are impossible even if a check is missed.
    return sqlite3.connect(f"file:{settings.db_file}?mode=ro", uri=True)


def run_finance_query(sql: str) -> str:
    """Execute a guarded read-only SELECT and return CSV (or an ERROR string)."""
    clean, err = _validate_select(sql)
    if err:
        return err

    con = None
    try:
        con = _readonly_conn()
        con.row_factory = sqlite3.Row
        rows = con.execute(clean).fetchmany(MAX_ROWS + 1)
    except Exception as exc:
        return f"ERROR: {exc}"
    finally:
        if con is not None:
            con.close()

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    if not rows:
        return "(no rows)"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(rows[0].keys())
    for r in rows:
        writer.writerow([r[k] for k in r.keys()])
    out = buf.getvalue()
    if truncated:
        out += f"-- truncated to {MAX_ROWS} rows; add filters/LIMIT --\n"
    return out[:MAX_CHARS]


def run_finance_df(sql: str):
    """Run a guarded read-only SELECT and return (DataFrame|None, error|None)."""
    import pandas as pd

    clean, err = _validate_select(sql)
    if err:
        return None, err
    con = None
    try:
        con = _readonly_conn()
        df = pd.read_sql_query(clean, con)
    except Exception as exc:
        return None, f"ERROR: {exc}"
    finally:
        if con is not None:
            con.close()
    return df.head(MAX_ROWS), None


def _system_blocks() -> list[dict]:
    """System prompt: role + cached data guide + a small live accounts snapshot."""
    accounts = run_finance_query("SELECT * FROM ai_accounts")
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": DATA_GUIDE, "cache_control": {"type": "ephemeral"}},
        {
            "type": "text",
            "text": f"Today's date: {date.today().isoformat()}\n\nCurrent accounts:\n{accounts}",
        },
    ]


def is_available() -> bool:
    return settings.has_anthropic


def stream_reply(messages: list[dict]):
    """Yield text chunks of Claude's reply, running data queries as needed.

    ``messages`` is the chat history: [{"role": "user"|"assistant", "content": str}].
    Raises RuntimeError if no API key is configured.
    """
    if not settings.has_anthropic:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    system = _system_blocks()
    convo: list[dict] = [dict(m) for m in messages]

    for _ in range(MAX_TOOL_TURNS):
        with client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=1500,
            system=system,
            tools=TOOLS,
            messages=convo,
        ) as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()

        if final.stop_reason != "tool_use":
            return

        # Record the assistant turn (text + tool_use blocks), then run the tools.
        convo.append({"role": "assistant", "content": final.content})
        results = []
        for block in final.content:
            if getattr(block, "type", None) == "tool_use":
                if block.name == "query_finances":
                    output = run_finance_query(block.input.get("sql", ""))
                else:
                    output = "ERROR: unknown tool."
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )
        convo.append({"role": "user", "content": results})
        yield "\n\n_…checked your data…_\n\n"

    yield "\n\n_(stopped after several lookups)_"
