from __future__ import annotations

import asyncio

from agent.executor import TaskExecutor
from agent.planner import PlannerAgent
from app.db import create_db_and_tables, seed_data
from app.models import UserRole
from sqlmodel import Session
from app.db import engine


async def main() -> None:
    create_db_and_tables()
    seed_data()
    planner = PlannerAgent()
    executor = TaskExecutor()
    request = input("DecaDesk request: ").strip()
    plan = await planner.plan(request, UserRole.IT_SUPPORT)
    with Session(engine) as session:
        result = await executor.execute(plan, session, UserRole.IT_SUPPORT)
    print(result["summary"])
    for line in result["logs"]:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())

