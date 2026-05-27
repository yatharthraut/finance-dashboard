"""AI Scratch Space engine: turn a natural-language request into chart/table specs.

The model is given the same data guide plus two tools:
  * query_finances     — inspect data (read-only SELECT -> CSV)
  * make_visualization — emit a chart/table spec the app renders with Altair

The model never runs rendering code; it describes *what* to plot (chart type +
SQL + axes), and the app renders it deterministically. Returns (text, artifacts)
where each artifact carries the resolved DataFrame ready to draw.
"""

from __future__ import annotations

from datetime import date

from chat import assistant as A
from chat.assistant import DATA_GUIDE, run_finance_df, run_finance_query
from utils.config import settings

MAX_TURNS = 6

VIZ_SYSTEM = (
    "You build charts and tables from the user's request using their finance "
    "data. Follow the data access guide. Optionally use query_finances to check "
    "columns/values, then call make_visualization once per chart or table the "
    "user wants. Write tidy SQL against the ai_* views: for multiple series "
    "(e.g. this month vs last month) return LONG format with a category column "
    "and pass that column as `color`. Give each visual a clear title and a one-"
    "line explanation. After creating the visual(s), reply with a short summary."
)

VIZ_TOOL = {
    "name": "make_visualization",
    "description": (
        "Render a chart or table for the user. Provide a read-only SQL SELECT "
        "(using the ai_* views) returning the rows to plot, plus how to plot "
        "them. For charts, `x`/`y` must be column names returned by the SQL; use "
        "`color` to split into multiple series (long format)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "explanation": {"type": "string", "description": "One line on what this shows."},
            "chart_type": {
                "type": "string",
                "enum": ["line", "bar", "area", "scatter", "table", "metric"],
            },
            "sql": {"type": "string", "description": "Read-only SELECT returning the data."},
            "x": {"type": "string", "description": "Column for the x-axis (charts)."},
            "y": {"type": "string", "description": "Numeric column for the y-axis (charts)."},
            "color": {"type": "string", "description": "Optional column to split into series."},
        },
        "required": ["title", "chart_type", "sql"],
    },
}

TOOLS = [A.TOOLS[0], VIZ_TOOL]  # query_finances + make_visualization


def _build_artifact(spec: dict) -> tuple[str, dict | None]:
    """Run the spec's SQL and package an artifact, or return an error message."""
    df, err = run_finance_df(spec.get("sql", ""))
    if err:
        return err, None
    if df is None or df.empty:
        return "Query returned no rows — adjust the filters.", None

    art = {
        "title": spec.get("title", "Chart"),
        "explanation": spec.get("explanation", ""),
        "chart_type": spec.get("chart_type", "table"),
        "x": spec.get("x"),
        "y": spec.get("y"),
        "color": spec.get("color"),
        "sql": spec.get("sql", ""),
        "df": df,
    }
    for key in ("x", "y", "color"):
        col = art.get(key)
        if col and col not in df.columns:
            return (
                f"ERROR: column '{col}' is not in the result columns "
                f"{list(df.columns)}. Adjust the SQL or the axis names.",
                None,
            )
    return f"OK — {len(df)} rows; columns: {', '.join(df.columns)}.", art


def generate(user_request: str) -> tuple[str, list[dict]]:
    """Run the agentic loop; return (summary_text, [artifacts])."""
    if not settings.has_anthropic:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    system = [
        {"type": "text", "text": VIZ_SYSTEM},
        {"type": "text", "text": DATA_GUIDE, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Today's date: {date.today().isoformat()}"},
    ]
    convo: list[dict] = [{"role": "user", "content": user_request}]
    artifacts: list[dict] = []
    texts: list[str] = []

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1500,
            system=system,
            tools=TOOLS,
            messages=convo,
        )
        convo.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                if block.text.strip():
                    texts.append(block.text.strip())
            elif btype == "tool_use":
                if block.name == "query_finances":
                    output = run_finance_query(block.input.get("sql", ""))
                elif block.name == "make_visualization":
                    output, art = _build_artifact(block.input)
                    if art:
                        artifacts.append(art)
                else:
                    output = "ERROR: unknown tool."
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
        if resp.stop_reason != "tool_use":
            break
        convo.append({"role": "user", "content": tool_results})

    return "\n\n".join(texts).strip(), artifacts
