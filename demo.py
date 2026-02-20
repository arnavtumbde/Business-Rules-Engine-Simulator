#!/usr/bin/env python3
"""
demo.py — Standalone CLI demo of the Business Rules Engine
=========================================================
Run without Flask to see the engine in action:
  python demo.py
"""

import json
from rules_engine import RulesEngine

engine = RulesEngine(rules_dir="rules")

DIVIDER = "─" * 60

def print_header(title):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")

def print_result(result):
    meta = result['metadata']
    ctx = result['context']
    fired = result['rules_fired']

    print(f"\n  📋 Ruleset : {meta['ruleset_name']} v{meta['version']}")
    print(f"  ⏱  Elapsed : {meta['elapsed_ms']}ms")
    print(f"  ⚡ Fired   : {result['rules_fired_count']} / {result['rules_total']} rules")
    print(f"\n  {DIVIDER}")
    print("  OUTPUT CONTEXT:")
    for k, v in ctx.items():
        print(f"    {k:<24} = {json.dumps(v)}")

    print(f"\n  {DIVIDER}")
    print("  EXECUTION TRACE:")
    for entry in result['execution_log']:
        icon = "✅" if entry['matched'] else "⬜"
        print(f"    {icon} [{entry['rule_id']}] {entry['name']}")
        for log in entry.get('logs', []):
            print(f"          ↳ {log}")

def run_demo():
    # ── DEMO 1: Insurance ──────────────────────────────────────────────────────
    print_header("DEMO 1: Insurance — Senior Healthy Non-Smoker")
    result = engine.evaluate("insurance", {
        "age": 67, "bmi": 23.5, "smoker": False,
        "region": "south", "accidents": 0, "base_premium": 400.0
    })
    print_result(result)

    print_header("DEMO 2: Insurance — Young Smoker, Multiple Accidents")
    result = engine.evaluate("insurance", {
        "age": 23, "bmi": 27.0, "smoker": True,
        "region": "north", "accidents": 4, "base_premium": 500.0
    })
    print_result(result)

    print_header("DEMO 3: Insurance — Extreme Risk (Should Be DENIED)")
    result = engine.evaluate("insurance", {
        "age": 73, "bmi": 42.0, "smoker": True,
        "region": "west", "accidents": 2, "base_premium": 600.0
    })
    print_result(result)

    # ── DEMO 4: E-Commerce ─────────────────────────────────────────────────────
    print_header("DEMO 4: E-Commerce — Platinum VIP with Coupon")
    result = engine.evaluate("ecommerce", {
        "cart_total": 320.0, "customer_tier": "platinum",
        "item_count": 6, "is_first_purchase": False,
        "coupon_code": "SAVE20", "days_since_last_order": 10
    })
    print_result(result)

    # ── DEMO 5: Loans ──────────────────────────────────────────────────────────
    print_header("DEMO 5: Loan — Prime Borrower")
    result = engine.evaluate("loans", {
        "credit_score": 790, "annual_income": 180000,
        "debt_to_income": 0.18, "employment_years": 10,
        "loan_amount": 75000, "loan_purpose": "home", "base_rate": 6.0
    })
    print_result(result)

    print_header("DEMO 6: Loan — Denied (High DTI)")
    result = engine.evaluate("loans", {
        "credit_score": 680, "annual_income": 45000,
        "debt_to_income": 0.62, "employment_years": 2,
        "loan_amount": 25000, "loan_purpose": "personal", "base_rate": 8.5
    })
    print_result(result)

    # ── LIVE RULE CHANGE DEMO ──────────────────────────────────────────────────
    print_header("DEMO 7: Hot-Reload — Change Rule Threshold On The Fly")
    print("""
  This demonstrates the core value: change rules WITHOUT touching Python code.

  Using the API (no demo needed, just show concept):

    # Original: Senior discount at age > 60
    # Change to: age > 55 by editing insurance.yaml

    curl -X PUT http://localhost:5000/api/rulesets/insurance/yaml \\
         --data-binary @rules/insurance.yaml

    # That's it. Next evaluation picks up the new threshold.
    # No server restart. No code changes. Instant hot-reload.
  """)

    print(f"\n{'═'*60}")
    print("  All demos complete!")
    print(f"  Start the API with: python app.py")
    print(f"  Dashboard at:       http://localhost:5000")
    print(f"{'═'*60}\n")

if __name__ == "__main__":
    run_demo()
