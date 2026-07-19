from decimal import Decimal

# USD per million tokens, Gemini Flash tier. Verify against current pricing
# before quoting costs externally; used for internal spend visibility only.
GEMINI_INPUT_COST_PER_MILLION = Decimal("0.10")
GEMINI_OUTPUT_COST_PER_MILLION = Decimal("0.40")

_MILLION = Decimal("1000000")


def estimate_mock_cost() -> Decimal:
    return Decimal("0")


def estimate_gemini_cost(*, input_tokens: int, output_tokens: int) -> Decimal:
    input_cost = Decimal(input_tokens) * GEMINI_INPUT_COST_PER_MILLION / _MILLION
    output_cost = Decimal(output_tokens) * GEMINI_OUTPUT_COST_PER_MILLION / _MILLION
    return input_cost + output_cost
