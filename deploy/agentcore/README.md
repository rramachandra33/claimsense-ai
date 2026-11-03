# The runner on Amazon Bedrock AgentCore Runtime

The runner (four agents, one claim per invocation) runs on AgentCore Runtime as `claimsense_runner`,
from the arm64 runner image CI pushes (`claimsense-runner:arm64-<commit>`, `arm64-latest`). It
speaks the AgentCore contract on port 8080 (`GET /ping`, `POST /invocations`, see agent/README.md).

```
console ──> runner on EC2 (/runs, forwards) ──InvokeAgentRuntime (SigV4)──> AgentCore: claimsense_runner
                                                                               │  Claude on Bedrock
                                       claimsense-mcp (registry + tools) <─────┤
                                       claimsense-api (Claims API) <───────────┘
```

- The adjuster's token travels in the payload (`user_token`): the SigV4 signature uses the
  Authorization header. The access rules are unchanged: the Claims API decides.
- The runtime finds the MCP server in the registry (`claimsense-mcp` /registry/v0/servers) and calls
  the Claims API, both over HTTPS Function URLs. Network mode PUBLIC: no VPC, no NAT.
- Each update is a new immutable version; the DEFAULT endpoint points at the latest.
- Logs: CloudWatch `/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`.

## Deploy

```bash
AWS_PROFILE=claimsense deploy/lambda/deploy.sh       # first: the two functions
AWS_PROFILE=claimsense deploy/agentcore/deploy.sh    # create/update the runtime, switch the console to it
```

`BRAIN=mock` deploys with the mock agents; `TAG=<commit>` a specific CI build.

## One-time IAM set-up (as root, in the console; `ACCOUNT` = account id)

1. Role `claimsense-agentcore`: Create role → Custom trust policy `iam/runtime-role-trust.json`
   (only AgentCore in this account may use it) → inline policy `iam/runtime-role-policy.json`:
   pull `claimsense-runner`, the two Claude models, its logs, traces and metrics.
2. Managed policy `ClaimSenseAgentCoreDeploy` from `iam/deployer-policy.json`, attached to the IAM
   user: manage runtimes, pass only `claimsense-agentcore`, read the runtime logs.
3. The instance role's inline policy `ClaimSenseInstance` gains `InvokeAgentRuntime` on
   `runtime/claimsense_runner-*` (`deploy/ec2/iam/instance-role-policy.json`), so the runner on the
   instance can forward runs.
