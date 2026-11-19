"""Annotate the AWS deployment screenshots: a title, what the screenshot shows, and numbered boxes.

    python3 docs/screenshots/annotate.py       (needs Pillow)

Reads raw/*.jpg (captured in the AWS console on 19 Nov 2026) and raw/*.txt (real psql output from
the instance), writes NN-name.png next to this file. Box coordinates are in the raw image's pixels.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
MONO = "/System/Library/Fonts/Menlo.ttc"
RED = "#e8312f"
INK, MUTED, PAPER = "#111827", "#4b5563", "#ffffff"


def font(size, path=FONT):
    return ImageFont.truetype(path, size)


# Each screenshot: (file, title, caption lines, [(x0, y0, x1, y1, label), ...])
SHOTS = [
    ("01-ec2-instance", "EC2 instance running the ClaimSense stack",
     ["t3.small i-0e0137af99bf21cc7 (tag Name=claimsense) in us-east-1. It runs the console (:3100), the data API,",
      "the MCP server, the runner and PostgreSQL 16 under Docker Compose, with images pulled from ECR.",
      "The instance profile claimsense-ec2 gives it ECR and Bedrock access, so no keys are on the box."],
     [(668, 250, 780, 290, "1 Running"), (266, 405, 345, 442, "2 t3.small"),
      (1078, 465, 1445, 520, "3 instance role")]),
    ("02-agentcore-runtime", "The four agents on Amazon Bedrock AgentCore Runtime",
     ["Runtime claimsense_runner (Reader, Coverage, Risk, Drafter on Claude Haiku 4.5 / Sonnet 4.5), status Active.",
      "Last 24 hours: 10 sessions, 5 errors. The errors are the incident drill of 19 Nov (an invalid model id,",
      "4 runs) and the smoke test's deliberate failure; see docs/INCIDENT-2026-11-19-drill.md."],
     [(286, 104, 880, 170, "1 Active"), (612, 368, 885, 440, "2 drill errors"),
      (322, 368, 590, 440, "3 sessions")]),
    ("03-lambda-api", "The Claims API as a Lambda function",
     ["claimsense-api: the data API the agents call through the MCP server (claimsense-mcp). Every route checks the",
      "token and the access rule, then writes an audit row (allow or deny). Python 3.12, 512 MB, in the VPC.",
      "(The function list page needs lambda:ListFunctions, which the deploy user does not have.)"],
     [(20, 100, 1230, 392, "1 claimsense-api")]),
    ("04-cognito-groups", "Sign-in: Amazon Cognito user pool and the four roles",
     ["Pool claimsense-users: people sign in with a password checked by Cognito; the API verifies the RS256 access",
      "token. The group in the token must match the role in claimsense.users. MFA is off in the pilot (a known gap).",
      "(The red banner is a console feature the deploy user has no permission for, not an error in ClaimSense.)"],
     [(306, 355, 1485, 505, "1 adjuster · fraud-investigator · senior-adjuster · total-loss-appraiser")]),
    ("05-alarms-list", "CloudWatch alarms",
     ["ClaimSense-BadRuns: more than 25% of runs in an hour failed, fell back to code's decision, or had an agent",
      "that could not finish. In alarm since 14:24:29 UTC: the incident drill (it fired 1 min 46 s after the bad",
      "build went live). ClaimSense-SlowRuns: p95 run time over 2 minutes, OK."],
     [(305, 278, 1075, 314, "1 BadRuns: In alarm (drill)"), (305, 326, 1075, 362, "2 SlowRuns: OK"),
      (1078, 278, 1225, 314, "3 14:24:29")]),
    ("06-alarm-badruns-drill", "The BadRuns alarm during the incident drill",
     ["The hourly bad-run rate at 14:00 UTC: 55.6% (5 of 9 runs: the 4 drill runs that ended as agent failures and",
      "one smoke test that was refused on purpose), against the 25% threshold.",
      "(The timeline panel needs cloudwatch:DescribeAlarmHistory, which the deploy user does not have.)"],
     [(1265, 280, 1315, 312, "1 55.6%"), (620, 398, 1065, 418, "2 threshold 25%"),
      (1390, 198, 1475, 222, "3 In alarm")]),
    ("07-dashboard-experience", "Dashboard: experience (call volume, failures, p95 latency)",
     ["ClaimSense-Experience, last 3 hours: run duration p50 and p95 (the SlowRuns alarm line is at 2 minutes),",
      "runs and failed runs per 5 minutes, and the Lambda functions' p95 duration, errors and throttles.",
      "Activity at 14:05-14:45 UTC is the drill: baseline, 4 failing runs, rollback and the checks after it."],
     [(8, 285, 752, 547, "1 p95 latency"), (760, 285, 1502, 547, "2 call volume and failures"),
      (760, 557, 1502, 750, "3 Lambda errors")]),
    ("08-dashboard-quality", "Dashboard: quality (evaluation and live error rates)",
     ["Evaluation pass rate: the CI gate's 150 cases at 100% (published by CI on main).",
      "Live rates for the hour: agent failure 44% (the drill's 4 of 9 runs), failure 11% (the refused smoke test),",
      "fallback 0%. Decisions by outcome. (The date box's \"1970-01-01\" is a display glitch of the range picker.)"],
     [(8, 285, 752, 547, "1 CI gate 100%"), (760, 285, 1502, 547, "2 error rates vs 25% alarm"),
      (8, 557, 1502, 750, "3 decisions by outcome")]),
    ("09-dashboard-economics", "Dashboard: economics (model cost per decision)",
     ["Last 24 hours: $0.341 model cost (Claude on Bedrock), 8 resolutions (runs that wrote a note), $0.0427 per",
      "resolution. A full assessment costs about $0.07; the drill's failed runs cost almost nothing, so the",
      "average is lower today. Tokens and cost per hour below."],
     [(8, 285, 502, 502, "1 cost per resolution"), (510, 285, 1502, 502, "2 hourly"),
      (760, 512, 1502, 750, "3 tokens")]),
    ("10-ecr-repositories", "Container registry: the four ClaimSense repositories in ECR",
     ["claimsense-api, -runner (also the MCP server and, as arm64, the AgentCore image), -seed and -web.",
      "CI pushes them only when every test and the evaluation gate pass (GitHub Actions, OIDC role, no keys)."],
     [(290, 215, 1500, 505, "1 four repositories")]),
    ("11-ecr-runner-images", "Images tagged by commit: what made the rollback one command",
     ["claimsense-runner: arm64-96c07fd... (now also arm64-latest) is the build on AgentCore; d08d6f0... is the",
      "drill's revert. Each CI build is tagged with its git commit, so `TAG=<sha> deploy/agentcore/deploy.sh`",
      "puts any earlier build back."],
     [(362, 285, 520, 365, "1 96c07fd (live)"), (362, 565, 520, 625, "2 d08d6f0"),
      (740, 300, 870, 340, "3 pushed by CI")]),
    ("12-logs-lambda-api", "Logs: the Claims API's requests during the incident drill",
     ["/aws/lambda/claimsense-api, 14:22:30-14:27:00 UTC, filtered to REPORT lines: one per request, with its",
      "duration. Each agent tool call (claim, documents, clause search) is one request; the X-Ray trace id in",
      "each REPORT line links it to the run's trace."],
     [(22, 225, 1490, 750, "1 one line per API request")]),
    ("13-batch-schedule-disabled", "Scheduled batch: built and deployed, deliberately disabled",
     ["EventBridge Scheduler claimsense-batch-every-4h (rate 4 hours) → Lambda claimsense-batch → AgentCore.",
      "Disabled by decision (DECISIONS.md, 2026-11-19): the console assessment covers the same pipeline, and a batch",
      "run assesses every open claim. `deploy/batch/deploy.sh` switches it on."],
     [(606, 195, 700, 232, "1 Disabled"), (310, 565, 575, 625, "2 every 4 hours")]),
    ("15-ci-run", "CI run on the submitted commit",
     ["GitHub Actions, commit 96c07fd on main: test-and-eval (every test suite and the 150-case evaluation gate)",
      "then push-images, which runs only if the first job passed. The gate's results file is kept as an artifact.",
      "The images it pushed are the ones running on EC2 and AgentCore (screenshot 11)."],
     [(350, 205, 960, 262, "1 96c07fd · Success"), (350, 398, 886, 444, "2 gate, then push"),
      (350, 660, 1455, 702, "3 eval results kept")]),
    ("16-ci-eval-gate", "The evaluation gate in CI: 150/150",
     ["The gate step's scorecard: every family, including the adversarial ones (prompt injection, cross-record",
      "leakage, forced auto-decision), on the mock brain. Below 90% the job fails and no image is pushed.",
      "On Claude the same 150 cases scored 148/150 on 19 Nov; the two case-design fixes then passed 4/4."],
     [(405, 232, 605, 397, "1 every family"), (405, 765, 750, 786, "2 150/150 passed")]),
    ("17-console-queue", "The running console: an adjuster's queue",
     ["Signed in as alice (adjuster) through Cognito on the EC2 console. The queue comes from the data API, which",
      "applies the access rule in code: alice sees the 6 claims assigned to her, and nothing else."],
     [(258, 96, 860, 128, "1 access rule applied by the API"), (244, 140, 1456, 490, "2 only her claims")]),
    ("18-console-claim-notes", "A claim's notes: model drafts, code checks, adjuster decides",
     ["CLM-2024-2165. Note 21: APPROVE drafted by the agents, checked by code, citing only clauses retrieved in the",
      "run; it waits for alice to confirm or reject. Note 19: the incident drill's agent failure (invalid model id),",
      "a DENY for an adjuster to assess. Both runs used the batch account from the instance, not the schedule."],
     [(275, 226, 728, 250, "1 drafted by agents, checked by code"), (275, 323, 582, 347, ">2 cited clauses"),
      (275, 353, 590, 379, ">3 the adjuster decides"), (275, 442, 852, 466, "4 drill: agent failure")]),
    ("19-console-how-reached", "Attribution: code's facts beside the model's judgement",
     ["\"How this was reached\" on note 21. Left: what code computed (cover in force, deductible, net payable,",
      "repair-to-ACV ratio) and the signals it found. Right: each agent's typed output, then the model usage:",
      "Haiku 4.5 for reader and risk, Sonnet 4.5 for coverage and drafter, $0.0702 for the run."],
     [(270, 138, 702, 302, "1 computed by code"), (850, 138, 1416, 427, "2 model judgement"),
      (850, 438, 1416, 572, "3 tokens and cost per agent")]),
    ("20-console-refusal", "Refusal on entitlement",
     ["alice opens CLM-2024-1873 (assigned to carol): \"not available\", with no claim data. The same answer is given",
      "for a claim that does not exist. The refusal is in the audit log with the reason (screenshot 14)."],
     [(244, 82, 1456, 160, "1 403, no claim data")]),
    ("21-console-policy-manual", "The policy manual: the corpus the agents search",
     ["Clause CLS-FRD-007 opened by its id (the link on a note). Only clauses that passed the load-time guardrail",
      "are searchable; an injected clause (CLS-ADM-013) is quarantined and can never be retrieved or cited."],
     [(244, 218, 1456, 357, "1 the cited clause")]),
]

AUDIT = ("14-audit-log", "Audit records: every call, granted or refused, with user, action and resource",
         ["claimsense.audit_log in PostgreSQL on the instance (real output of psql over SSH, 19 Nov 2026).",
          "Top: one run (CLM-2024-2165 at 14:25, after the rollback): code's reads, then each agent under its own",
          "OBO token. Bottom: the latest refusals: decided claim for the batch account, another adjuster's claim,",
          "a suspended user, forged and development tokens. 1,028 allowed and 14 denied rows in total."],
         ["audit_agents.txt", "audit_denies.txt"])


def header(width, title, lines):
    """The white band above a screenshot: the title and the caption."""
    height = 30 + 40 + 26 * len(lines) + 20
    band = Image.new("RGB", (width, height), PAPER)
    d = ImageDraw.Draw(band)
    d.text((28, 22), title, font=font(30, BOLD), fill=INK)
    for i, line in enumerate(lines):
        d.text((28, 70 + 26 * i), line, font=font(19), fill=MUTED)
    return band


def boxes(image, marks):
    d = ImageDraw.Draw(image)
    label_font = font(17, BOLD)
    for x0, y0, x1, y1, label in marks:
        d.rectangle((x0, y0, x1, y1), outline=RED, width=4)
        tw = d.textlength(label.lstrip(">"), font=label_font)
        if label.startswith(">"):                 # to the right of the box, not above it
            lx, ly = x1 + 6, (y0 + y1) // 2 - 12
        else:
            lx, ly = x0, (y0 - 26 if y0 > 30 else y1 + 4)
        d.rectangle((lx, ly, lx + tw + 14, ly + 24), fill=RED)
        d.text((lx + 7, ly + 3), label.lstrip(">"), font=label_font, fill="white")
    return image


def terminal(texts, width=1525):
    """Real query output, drawn as a terminal window."""
    mono = font(17, MONO)
    lines = []
    for name in texts:
        lines += ["$ psql (on the instance) -- " + name.replace(".txt", "").replace("_", " "), ""]
        lines += (RAW / name).read_text().rstrip().splitlines() + [""]
    height = 50 + 24 * len(lines) + 20
    img = Image.new("RGB", (width, height), "#0f172a")
    d = ImageDraw.Draw(img)
    for i, colour in enumerate(("#ef4444", "#f59e0b", "#22c55e")):
        d.ellipse((18 + 24 * i, 16, 32 + 24 * i, 30), fill=colour)
    d.text((110, 12), "ec2-user@claimsense:/opt/claimsense", font=font(17), fill="#94a3b8")
    for i, line in enumerate(lines):
        colour = "#7dd3fc" if line.startswith("$") else ("#fca5a5" if "| deny" in line else "#e2e8f0")
        d.text((22, 50 + 24 * i), line, font=mono, fill=colour)
    return img


def save(name, title, lines, body):
    band = header(body.width, title, lines)
    out = Image.new("RGB", (body.width, band.height + body.height + 6), RED)
    out.paste(band, (0, 0))
    out.paste(body, (0, band.height + 6))
    out.save(HERE / f"{name}.png", optimize=True)
    print("wrote", f"{name}.png")


for name, title, lines, marks in SHOTS:
    save(name, title, lines, boxes(Image.open(RAW / f"{name}.jpg").convert("RGB"), marks))

name, title, lines, texts = AUDIT
save(name, title, lines, terminal(texts))
