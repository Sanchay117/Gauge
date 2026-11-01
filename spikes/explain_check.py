"""Ask Spark to explain the Moon law failing on the Earth throw, using the numbers from a real run.

Usage: uv run --env-file .env spikes/explain_check.py
"""
from gauge import agent
from gauge.budget import default_ledger
from gauge.laws import Verdict
from gauge.meta_api import MetaClient

verdict = Verdict(False, "the constants changed between runs",
                  {"a": {"run_1": -1.643, "run_2": -10.317, "difference": 5.28, "agrees": False}}, 0.186, 0.00697, 19)
print(agent.explain_verdict(MetaClient(default_ledger()), {"quantity": "acceleration due to lunar gravity"}, verdict,
                            "An astronaut jumps on the lunar surface",
                            "A ball is tossed upward in front of a marked board"))
