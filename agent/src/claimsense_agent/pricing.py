"""What a run costs: tokens per agent, priced per model.

Prices are USD per million tokens, on-demand, us-east-1, from the AWS Price List API
(service AmazonBedrockFoundationModels), checked 2026-10-28. The `us.` inference profiles we use
bill at the "Regional" rate, 10% above the `global.` profiles (Haiku 4.5: $1.00 / $5.00, Sonnet 4.5:
$3.00 / $15.00), which route requests to any region worldwide.
"""
PRICES = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": {"input": 1.10, "output": 5.50},
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": {"input": 3.30, "output": 16.50},
}


def price_for(model):
    """The price entry for a model id such as 'bedrock/converse/us.anthropic.claude-haiku-…'."""
    for model_id, price in PRICES.items():
        if model.endswith(model_id):
            return price
    return None


def cost_usd(model, input_tokens, output_tokens):
    """The cost of one agent's tokens, or None if the model is not in the price table."""
    price = price_for(model)
    if price is None:
        return None
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


def usage_summary(per_agent):
    """Totals for a run from each agent's usage: {"agent": {"model", "input_tokens", ...}}."""
    input_tokens = sum(u["input_tokens"] for u in per_agent.values())
    output_tokens = sum(u["output_tokens"] for u in per_agent.values())
    costs = [u["cost_usd"] for u in per_agent.values()]
    total = None if None in costs else round(sum(costs), 4)
    return {"agents": per_agent, "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_usd": total}
