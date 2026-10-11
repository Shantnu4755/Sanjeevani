"""Service catalog: python -m app.cli <command>

  add-service --name kavach --container kavach --url http://kavach:8000/health [--max-restarts 3]
  list-services
  disable-service --name NAME | enable-service --name NAME

add-service updates an existing service, so the setup commands can be run again safely.
"""

import argparse
import sys

from pydantic import ValidationError as PydanticValidationError

from .config import Config
from .exceptions import AppError
from .extensions import db
from .logging_setup import setup_logging
from .schemas.status import ServiceCreate
from .services.catalog_service import CatalogService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Sanjeevani service catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-service", help="watch a service (or update it)")
    add.add_argument("--name", required=True)
    add.add_argument("--container", required=True, help="Docker container name to restart")
    add.add_argument("--url", required=True, help="health URL that must return 200")
    add.add_argument("--max-restarts", type=int, default=3, help="automatic restarts per hour")
    commands.add_parser("list-services", help="list watched services")
    for verb in ("disable-service", "enable-service"):
        commands.add_parser(verb).add_argument("--name", required=True)
    args = parser.parse_args(argv)

    config = Config.from_env()
    setup_logging("WARNING")
    db.init_app(config.database_url)
    catalog = CatalogService()
    try:
        if args.command == "add-service":
            data = ServiceCreate(
                name=args.name,
                container_name=args.container,
                health_url=args.url,
                max_restarts_per_hour=args.max_restarts,
            )
            created = catalog.upsert(data)
            sys.stdout.write(f"{'added' if created else 'updated'} {data.name} -> {data.health_url}\n")
        elif args.command == "list-services":
            for svc in catalog.all():
                state = "enabled" if svc.enabled else "disabled"
                sys.stdout.write(
                    f"{svc.name}\t{state}\tcontainer={svc.container_name}\turl={svc.health_url}"
                    f"\tmax_restarts_per_hour={svc.max_restarts_per_hour}\n"
                )
        else:
            catalog.set_enabled(args.name, args.command == "enable-service")
            sys.stdout.write(f"{args.command.split('-')[0]}d {args.name}\n")
    except PydanticValidationError as exc:
        sys.stderr.write(f"Invalid arguments: {exc.errors(include_url=False)}\n")
        return 2
    except AppError as exc:
        sys.stderr.write(f"{exc.message}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
