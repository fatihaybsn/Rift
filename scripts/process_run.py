#!/usr/bin/env python3
"""Internal CLI tool to trigger processing of a pending run.
Useful for demo scripts and testing without a background worker."""

import argparse
import sys
import uuid

from app.db.session import get_session_factory
from app.services.run_orchestration import RunOrchestrationService
from app.core.config import get_settings
from app.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a pending analysis run.")
    parser.add_argument("run_id", type=uuid.UUID, help="The UUID of the run to process.")
    args = parser.parse_args()

    # Load config and setup logging so we can see what's happening
    settings = get_settings()
    configure_logging(log_level=settings.log_level)

    session_factory = get_session_factory()
    with session_factory() as session:
        print(f"Processing run {args.run_id}...")
        try:
            run = RunOrchestrationService().process_run(db=session, run_id=args.run_id)
            print(f"Run {args.run_id} processed. Final status: {run.status}")
        except Exception as e:
            print(f"Failed to process run {args.run_id}: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
