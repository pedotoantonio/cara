"""Bootstrap helpers — `python -m cara.bootstrap <subcommand>`.

Subcommands:
- `create-admin <email> [password]` — promote / create an admin user.
- `restart-self`                    — exit with code 42, the
                                       supervisor convention for
                                       'intentional restart'. With
                                       `restart: unless-stopped` in
                                       docker-compose, the container
                                       comes back in ~5s. Used by the
                                       /admin/restart-backend endpoint
                                       and for manual invocation in
                                       diagnostics.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cara.config import settings
from cara.services import auth as auth_svc


# Exit codes:
# - 0  : clean shutdown (docker won't restart with `on-failure`, will
#        with `unless-stopped`).
# - 1  : crash (uncaught exception).
# - 42 : intentional restart requested by an operator (Lumo convention,
#        adopted here for log filtering: `journalctl -u docker | grep
#        "exited with code 42"` shows every operator-triggered restart).
EXIT_CODE_RESTART = 42


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


def restart_self(reason: str | None = None) -> None:
    """Exit the current process with EXIT_CODE_RESTART (42).

    Hard exit via `os._exit` so we don't run any atexit / uvicorn
    shutdown hooks — those would try to drain in-flight requests,
    which is the opposite of what we want. The whole point of this
    is a fast operator-triggered bounce; docker's `restart:
    unless-stopped` brings us back in ~5s.

    The caller is expected to have already:
    - emitted a structlog event (so the audit trail records the actor),
    - given the HTTP response a chance to flush (via BackgroundTasks
      or a short asyncio.sleep before calling).
    """
    print(
        f"[restart-self] exiting with code {EXIT_CODE_RESTART}"
        + (f" reason={reason!r}" if reason else ""),
        flush=True,
    )
    os._exit(EXIT_CODE_RESTART)


def _usage() -> None:
    print(
        "usage: python -m cara.bootstrap <subcommand>\n"
        "  create-admin <email> [password]\n"
        "  restart-self [reason]"
    )
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    if cmd == "create-admin":
        if len(sys.argv) < 3:
            _usage()
        email = sys.argv[2]
        password = (
            sys.argv[3] if len(sys.argv) > 3
            else os.environ.get("CARA_ADMIN_PASSWORD")
        )
        asyncio.run(create_admin(email, password))
    elif cmd == "restart-self":
        reason = sys.argv[2] if len(sys.argv) > 2 else "cli"
        restart_self(reason)
    else:
        _usage()


if __name__ == "__main__":
    main()
