"""Bootstrap helpers — `python -m cara.bootstrap create-admin`."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cara.config import settings
from cara.services import auth as auth_svc


async def create_admin(email: str, password: str | None = None) -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        existing = await auth_svc.get_user_by_email(session, email)
        if existing is not None:
            print(f"[skip] user {email} already exists (id={existing.id})")
            return
        pwd = password or secrets.token_urlsafe(16)
        user = await auth_svc.create_user(
            session, email=email, password=pwd, full_name="Admin", is_admin=True
        )
        await session.commit()
        print(f"[ok] admin created: id={user.id} email={user.email}")
        if password is None:
            print(f"[pwd] {pwd}   <- save this, it will not be shown again")
    await engine.dispose()


def _usage() -> None:
    print("usage: python -m cara.bootstrap create-admin <email> [password]")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "create-admin":
        _usage()
    email = sys.argv[2]
    password = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("CARA_ADMIN_PASSWORD")
    asyncio.run(create_admin(email, password))


if __name__ == "__main__":
    main()
