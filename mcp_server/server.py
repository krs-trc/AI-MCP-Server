# ----------------------------------------------------------------
# AI MCP Server for Incident Management 
# ----------------------------------------------------------------
# This server exposes multiple MCP tools that interact with
# the MySQL databases (Knowledge Base + Incident) and simulate
# email functionality for testing.
# ----------------------------------------------------------------

import asyncio
import datetime
import logging
import aiomysql
from fastmcp import FastMCP
import sys
import uuid
from typing import List, Optional, Literal

from rich.console import Console
from rich.table import Table
console = Console()

# ----------------------------------------------------------------
# Setup & Configuration
# ----------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
mcp = FastMCP("db_tools")

DB_HOST = "localhost"
DB_USER = "root"
DB_PASS = "rootpassword"

pool: aiomysql.Pool | None = None

# ----------------------------------------------------------------
# Database Connection
# ----------------------------------------------------------------
async def init_db_pool():
    global pool
    pool = await aiomysql.create_pool(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        autocommit=True,
    )
    logging.info("✅ Database pool initialized.")

async def close_pool():
    """Close database pool on shutdown."""
    global pool
    if pool:
        logging.info("Closing database pool...")
        pool.close()
        await pool.wait_closed()
        logging.info("✅ Pool closed.")


# ----------------------------------------------------------------
# Stopwords for Keyword Filtering
# ----------------------------------------------------------------
STOPWORDS = {"the", "is", "a", "an", "to", "for", "with", "and", "or", "what", "do", "i", "my", "on", "how", "of"}

# ----------------------------------------------------------------
# Knowledge Base Search Tool
# ----------------------------------------------------------------
@mcp.tool()
async def search_knowledge_base(short_description_contains: str = None, limit: int = 10) -> list[dict]:
    """Search Knowledge Base articles using meaningful keywords."""
    where_clauses = []
    params = []

    if short_description_contains:
        # Extract and filter meaningful keywords
        keywords = [
            k.strip().lower()
            for k in short_description_contains.split()
            if k.strip() and k.strip().lower() not in STOPWORDS
        ]
        if keywords:
            keyword_clauses = []
            for kw in keywords:
                keyword_clauses.append("LOWER(short_description) LIKE %s")
                params.append(f"%{kw}%")
            where_clauses.append("(" + " OR ".join(keyword_clauses) + ")")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"""
    SELECT number, version, short_description, author,
           category, workflow, updated
    FROM knowledge_base.knowledge_base
    {where_sql}
    ORDER BY updated DESC
    LIMIT %s
    """
    params.append(limit)

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    return [dict(row) for row in rows]


# ----------------------------------------------------------------
# Incident Search Tool
# ----------------------------------------------------------------
@mcp.tool()
async def search_incidents(short_description_contains: str = None, limit: int = 10) -> list[dict]:
    """Search Incident records using meaningful keywords."""
    where_clauses = []
    params = []

    if short_description_contains:
        keywords = [
            k.strip().lower()
            for k in short_description_contains.split()
            if k.strip() and k.strip().lower() not in STOPWORDS
        ]
        if keywords:
            keyword_clauses = []
            for kw in keywords:
                keyword_clauses.append("LOWER(short_description) LIKE %s")
                params.append(f"%{kw}%")
            where_clauses.append("(" + " OR ".join(keyword_clauses) + ")")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"""
    SELECT number, opened, short_description, description,
           resolution_code, resolution_notes, state, assigned_to
    FROM incident.incidents
    {where_sql}
    ORDER BY opened DESC
    LIMIT %s
    """
    params.append(limit)

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    return [dict(row) for row in rows]


# ----------------------------------------------------------------
# Create Incident Tool
# ----------------------------------------------------------------
@mcp.tool()
async def create_incident(
    number: str,
    opened: str,
    short_description: str,
    description: str,
    state: Literal["New", "In Progress", "On Hold", "Closed"] = "New",
    assigned_to: Optional[str] = None,
) -> dict:
    """Insert a new incident record into the incident database."""
    sql = """
    INSERT INTO incident.incidents 
        (number, opened, short_description, description, state, assigned_to)
    VALUES (%s, %s, %s, %s, %s, %s)
    """

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, (number, opened, short_description, description, state, assigned_to))

    logging.info(f"🆕 Created incident {number} in database.")
    return {"status": "success", "number": number}


# ----------------------------------------------------------------
# Email Mock Tools
# ----------------------------------------------------------------
@mcp.tool()
async def email_send_mock(
    to: List[str],
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None
) -> dict:
    """Simulates sending an email notification (mock only)."""
    message_id = f"MOCK-{uuid.uuid4()}"
    email_data = {
        "status": "ok",
        "message_id": message_id,
        "sent": {
            "to": to,
            "cc": cc or [],
            "bcc": bcc or [],
            "subject": subject,
            "body": body,
        },
        "note": "Mock email only – no actual message sent."
    }

    table = Table(title="Mock Email Sent", show_lines=True)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("To", ", ".join(to))
    table.add_row("Subject", subject)
    table.add_row("Body", body)
    table.add_row("Message ID", message_id)
    table.add_row("Note", email_data["note"])

    console.print(table)

    return email_data

# ----------------------------------------------------------------
# 🚀 Server Entry Point
# ----------------------------------------------------------------
async def main():
    try:
        await init_db_pool()
    except Exception as e:
        print(f"Failed to initialize DB pool: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        await mcp.run_async(transport="http", host="localhost", port=8000)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
