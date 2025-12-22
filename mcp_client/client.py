import asyncio
import datetime
from typing import TypedDict, List, Optional

from fastmcp import Client
from google import genai
from langgraph.graph import StateGraph, END

# Rich UI imports
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich.text import Text

# ----------------------------------------------------------------
# Setup Gemini and MCP Client
# ----------------------------------------------------------------
MCP_URL = "http://localhost:8000/mcp"
client = Client(MCP_URL)
gemini = genai.Client(api_key="AIzaSyBIGaGEwxj7EJIuo3Gj0M1YGPqN6ZgSGs4") 

console = Console()

# ----------------------------------------------------------------
# Define the agent state
# ----------------------------------------------------------------
class AgentState(TypedDict):
    user_query: str
    kb_results: Optional[List[dict]]
    incident_results: Optional[List[dict]]
    user_feedback: Optional[str]
    user_create_incident: Optional[str]
    incident_number: Optional[str]
    final_response: Optional[str]

# ----------------------------------------------------------------
# Resolver Node
# ----------------------------------------------------------------
async def resolver_node(state: AgentState) -> AgentState:
    console.print("[bold blue]\nSearching knowledge base and incidents...[/bold blue]")

    # Call MCP server tools
    kb_results = await client.call_tool_mcp(
        "search_knowledge_base",
        {"short_description_contains": state["user_query"], "limit": 5}
    )
    incident_results = await client.call_tool_mcp(
        "search_incidents",
        {"short_description_contains": state["user_query"], "limit": 5}
    )

    # Extract actual result
    kb_data = kb_results.structuredContent.get("result", []) if hasattr(kb_results, "structuredContent") else []
    inc_data = incident_results.structuredContent.get("result", []) if hasattr(incident_results, "structuredContent") else []

    # Display of KBs
    kb_table = Table(title="Knowledge Base Results", show_lines=True)
    kb_table.add_column("Number", style="cyan")
    kb_table.add_column("Short Description", style="green")
    kb_table.add_column("Category", style="magenta")
    kb_table.add_column("Author", style="yellow")

    if kb_data:
        for kb in kb_data:
            kb_table.add_row(
                kb.get("number", "N/A"),
                kb.get("short_description", "No description"),
                kb.get("category", "Unknown"),
                kb.get("author", "N/A")
            )
    else:
        kb_table.add_row("-", "No KB articles found", "-", "-")

    console.print(kb_table)

    # Display of Incidents
    inc_table = Table(title="Related Incidents", show_lines=True)
    inc_table.add_column("Number", style="cyan")
    inc_table.add_column("Short Description", style="green")
    inc_table.add_column("State", style="yellow")

    if inc_data:
        for inc in inc_data:
            inc_table.add_row(
                inc.get("number", "N/A"),
                inc.get("short_description", "No description"),
                inc.get("state", "Unknown")
            )
    else:
        inc_table.add_row("-", "No incidents found", "-")

    console.print(inc_table)

    # Summarization
    reasoning_prompt = f"""
    User issue: "{state['user_query']}"

    Related Knowledge Base entries:
    {kb_data}

    Related Incidents:
    {inc_data}

    - Include KB numbers that mention the topic even if not exact matches.
    - Suggest clear next steps or escalation guidance.
    """

    summary = gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=[reasoning_prompt]
    )

    console.print(Panel(Markdown(f"💡 **Suggested Fix:**\n\n{summary.text.strip()}"), style="bold green"))

    return {
        **state,
        "kb_results": kb_data,
        "incident_results": inc_data,
        "final_response": summary.text.strip(),
    }


# ----------------------------------------------------------------
# 💬 Confirmation Node
# ----------------------------------------------------------------
async def confirmation_node(state: AgentState) -> AgentState:
    feedback = Prompt.ask("\nDid this solution resolve your issue?", choices=["yes", "no"], default="no")
    if feedback == "no":
        create_incident = Prompt.ask("Would you like to create an incident?", choices=["yes", "no"], default="yes")
        return {**state, "user_feedback": feedback, "user_create_incident": create_incident}
    else:
        return {**state, "user_feedback": feedback, "user_create_incident": "no"}


# ----------------------------------------------------------------
# Escalation Node
# ----------------------------------------------------------------
async def escalation_node(state: AgentState) -> AgentState:
    if state.get("user_feedback") == "no" and state.get("user_create_incident") == "yes":
        console.print(Panel("Please provide incident details below", style="bold yellow"))
        short_description = Prompt.ask("Short description of the issue")
        description = Prompt.ask("Detailed description of what happened")
        assigned_to = Prompt.ask("Assign to (optional)", default="")

        incident_number = f"INC{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        opened = datetime.datetime.now().isoformat()

        console.print("[yellow]Creating your incident... please wait...[/yellow]")

        await client.call_tool_mcp(
            "create_incident",
            {
                "number": incident_number,
                "opened": opened,
                "short_description": short_description,
                "description": description,
                "state": "New",
                "assigned_to": assigned_to or None,
            },
        )

        await client.call_tool_mcp(
            "email_send_mock",
            {
                "to": ["support@example.com"],
                "subject": f"New Incident {incident_number}",
                "body": f"Issue reported: {short_description}\n\n{description}",
            },
        )

        console.print(Panel(f"Incident [bold red]{incident_number}[/bold red] created successfully and notification sent to support.", style="bold green"))
        return {**state, "incident_number": incident_number, "final_response": f"Incident {incident_number} created."}

    elif state.get("user_feedback") == "no":
        return {**state, "final_response": "No incident created. Issue remains unresolved."}
    else:
        return {**state, "final_response": "Glad it helped! No escalation needed."}


# ----------------------------------------------------------------
# Build LangGraph Workflow
# ----------------------------------------------------------------
graph = StateGraph(AgentState)
graph.add_node("resolver", resolver_node)
graph.add_node("confirmation", confirmation_node)
graph.add_node("escalation", escalation_node)

graph.set_entry_point("resolver")
graph.add_edge("resolver", "confirmation")
graph.add_edge("confirmation", "escalation")
graph.add_edge("escalation", END)
app = graph.compile()


# ----------------------------------------------------------------
# Chat
# ----------------------------------------------------------------
async def main():
    async with client:
        console.print(Panel("[bold cyan]AI Incident Assistant Ready[/bold cyan]\nType 'exit' to quit.", style="bold blue"))
        while True:
            user_query = Prompt.ask("Describe your IT issue")
            if user_query.lower() in ("exit", "quit"):
                console.print("[red]Exiting chat...[/red]")
                break

            state = AgentState(user_query=user_query)
            console.print("\n[bold green]Running agent...[/bold green]\n")
            final_state = await app.ainvoke(state)

            console.print(Panel(f"{final_state['final_response']}", style="bold cyan"))
            console.print("\n" + "-" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
