"""Command line: run one assessment, or list the claims a user can see.

    claimsense-agent run --claim CLM-2024-1800 --user alice
    claimsense-agent claims --user alice

--user signs in through the API's development login (start the API with CLAIMSENSE_DEV_LOGIN=1).
Without --user, the adjuster's token is read from CLAIMSENSE_USER_TOKEN.
"""
import argparse
import asyncio
import json
import os

from .api import ApiClient, ApiError, api_url, dev_login
from .brain import BRAINS
from .pipeline import run_assessment
from .trace import BOLD, GREEN, GREY, RED, RESET, YELLOW, Tracer


def build_parser():
    parser = argparse.ArgumentParser(prog="claimsense-agent",
                                     description="ClaimSense assessment pipeline (four agents).")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="assess one claim and write the draft note")
    run.add_argument("--claim", required=True, help="claim id, e.g. CLM-2024-1800")
    run.add_argument("--user", help="sign in as this user (development login)")
    run.add_argument("--brain", choices=BRAINS, default="mock", help="mock (default) or bedrock")
    run.add_argument("--demo-bad-draft", action="store_true",
                     help="make the drafter return a bad draft, to show the code checks replace it")

    claims = sub.add_parser("claims", help="list the claims this user may read")
    claims.add_argument("--user", help="sign in as this user (development login)")
    return parser


def client_for(user):
    if user:
        return ApiClient(dev_login(user))
    token = os.environ.get("CLAIMSENSE_USER_TOKEN")
    if not token:
        raise SystemExit("Pass --user <id> or set CLAIMSENSE_USER_TOKEN.")
    return ApiClient(token)


def run_command(args):
    client = client_for(args.user)
    me = client.me()
    tracer = Tracer()
    tracer.banner(f"ClaimSense assessment — {args.claim}",
                  f"as {me['user_id']} ({me['group']}) · brain: {args.brain} · API: {api_url()}")
    result = asyncio.run(run_assessment(client, args.claim, brain=args.brain, tracer=tracer,
                                        demo_bad_draft=args.demo_bad_draft))
    if result.status == "failed":
        print(f"\n{RED}{BOLD}run failed{RESET}")
        for problem in result.problems:
            print(f"  {problem}")
        return 1
    colour = {"APPROVE": GREEN, "DENY": RED}.get(result.outcome, YELLOW)
    print(f"\n{BOLD}outcome: {colour}{result.outcome}{RESET}  ({result.decision_source}; "
          f"cites {', '.join(result.cited_clauses) or 'none'})")
    print(f"{GREY}note {result.note_id} {result.status} · run_id={result.run_id} · "
          f"{tracer.total_ms():.0f} ms{RESET}")
    print(json.dumps(result.model_dump(), indent=2))
    return 0


def claims_command(args):
    client = client_for(args.user)
    for claim in client.get("/api/v1/claims")["claims"]:
        print(f"{claim['claim_id']}  {claim['claim_status']:<14} {claim['incident_type']}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return run_command(args)
        return claims_command(args)
    except ApiError as e:
        print(f"{RED}API refused: {e}{RESET}")
        return 1
    except NotImplementedError as e:
        print(f"{YELLOW}{e}{RESET}")
        return 1
