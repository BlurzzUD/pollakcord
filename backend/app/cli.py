import argparse
import asyncio
import sys

from sqlalchemy import select

from .config import get_settings
from .crypto.keyring import generate_key_text
from .db.session import build_engine, build_session_factory
from .models import User
from .models.enums import PlatformRole
from .seed import ensure_school_classes


async def grant_role(username: str, role: str) -> int:
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    async with factory() as db:
        user = (await db.execute(select(User).where(User.username_lower == username.strip().lower()))).scalar_one_or_none()
        if user is None:
            print("user not found", file=sys.stderr)
            return 1
        if role == PlatformRole.DOK_REPRESENTATIVE.value and user.school_class_id is None:
            print("user has no class", file=sys.stderr)
            return 1
        user.platform_role = role
        await db.commit()
    await engine.dispose()
    print(f"{username} is now {role}")
    return 0


async def seed() -> int:
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    async with factory() as db:
        await ensure_school_classes(db)
    await engine.dispose()
    print("school classes ensured")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pollakcord")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-key")
    sub.add_parser("seed")
    grant = sub.add_parser("grant-role")
    grant.add_argument("username")
    grant.add_argument("role", choices=[r.value for r in PlatformRole])
    args = parser.parse_args()
    if args.command == "generate-key":
        print(generate_key_text())
        return 0
    if args.command == "seed":
        return asyncio.run(seed())
    return asyncio.run(grant_role(args.username, args.role))


if __name__ == "__main__":
    raise SystemExit(main())
