"""Small admin CLI:  python -m apps.api create-user <email> [--admin] [--password X]"""

from __future__ import annotations

import argparse
import getpass
import sys

from database.session import session_scope
from database.types import Role


def _create_user(args: argparse.Namespace) -> int:
    from database.repositories import UserRepository

    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("password required", file=sys.stderr)
        return 2
    with session_scope() as session:
        repo = UserRepository(session)
        if repo.get_by_email(args.email):
            print(f"user {args.email} already exists", file=sys.stderr)
            return 1
        user = repo.create(
            email=args.email,
            display_name=args.name,
            role=Role.ADMIN if args.admin else Role.ANALYST,
            password=password,
        )
        session.commit()
        print(f"created {user.email} ({user.role}) id={user.id}")
    return 0


def _set_password(args: argparse.Namespace) -> int:
    from database.repositories import UserRepository

    password = args.password or getpass.getpass("New password: ")
    with session_scope() as session:
        repo = UserRepository(session)
        user = repo.get_by_email(args.email)
        if user is None:
            print("no such user", file=sys.stderr)
            return 1
        repo.set_password(user, password)
        session.commit()
        print(f"password updated for {user.email}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.api")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-user")
    c.add_argument("email")
    c.add_argument("--name", default=None)
    c.add_argument("--admin", action="store_true")
    c.add_argument("--password", default=None)
    c.set_defaults(func=_create_user)

    s = sub.add_parser("set-password")
    s.add_argument("email")
    s.add_argument("--password", default=None)
    s.set_defaults(func=_set_password)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
