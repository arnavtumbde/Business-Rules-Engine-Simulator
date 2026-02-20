"""
rules_engine.py — Core Business Rules Engine
============================================
Loads YAML rule definitions and evaluates them against input data.
Supports: comparisons, boolean logic, math operations, field mutation,
          append-to-list, conditional branching, and execution logging.
"""

import re
import yaml
import copy
import operator
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional


# ─── SAFE EXPRESSION EVALUATOR ────────────────────────────────────────────────

class SafeEvaluator:
    """
    Evaluates rule condition strings safely without exec/eval abuse.
    Supports: comparisons (>, <, >=, <=, ==, !=), boolean operators
              (and, or, not), string literals, numeric literals, booleans.
    """

    OPS = {
        ">":  operator.gt,
        "<":  operator.lt,
        ">=": operator.ge,
        "<=": operator.le,
        "==": operator.eq,
        "!=": operator.ne,
    }

    def __init__(self, context: Dict[str, Any]):
        self.ctx = context

    def evaluate(self, expression: str) -> bool:
        """Entry point — evaluates the top-level condition."""
        return self._parse_or(expression.strip())

    def _parse_or(self, expr: str) -> bool:
        parts = self._split_on_keyword(expr, " or ")
        if len(parts) > 1:
            return any(self._parse_and(p.strip()) for p in parts)
        return self._parse_and(expr)

    def _parse_and(self, expr: str) -> bool:
        parts = self._split_on_keyword(expr, " and ")
        if len(parts) > 1:
            return all(self._parse_not(p.strip()) for p in parts)
        return self._parse_not(expr)

    def _parse_not(self, expr: str) -> bool:
        if expr.startswith("not "):
            return not self._parse_comparison(expr[4:].strip())
        return self._parse_comparison(expr)

    def _parse_comparison(self, expr: str) -> bool:
        # Strip outer parens
        if expr.startswith("(") and expr.endswith(")"):
            return self.evaluate(expr[1:-1])

        for op_str in (">=", "<=", "!=", "==", ">", "<"):
            idx = expr.find(op_str)
            if idx == -1:
                continue
            left_str = expr[:idx].strip()
            right_str = expr[idx + len(op_str):].strip()
            left = self._resolve_value(left_str)
            right = self._resolve_value(right_str)
            try:
                return self.OPS[op_str](left, right)
            except TypeError:
                return False

        # Bare boolean field
        return bool(self._resolve_value(expr))

    def _resolve_value(self, token: str) -> Any:
        token = token.strip()
        # Boolean literals
        if token == "true":  return True
        if token == "false": return False
        if token == "null":  return None
        # String literal
        if (token.startswith("'") and token.endswith("'")) or \
           (token.startswith('"') and token.endswith('"')):
            return token[1:-1]
        # Numeric
        try:
            return int(token)
        except ValueError:
            pass
        try:
            return float(token)
        except ValueError:
            pass
        # Context lookup (support dot notation)
        parts = token.split(".")
        val = self.ctx
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                return None
        return val

    def _split_on_keyword(self, expr: str, keyword: str) -> List[str]:
        """Split on keyword while respecting quoted strings and parentheses."""
        parts = []
        depth = 0
        current = []
        i = 0
        kw = keyword
        while i < len(expr):
            if expr[i] in "('\"":
                depth += 1
                current.append(expr[i])
                i += 1
            elif expr[i] in ")'\"" and depth > 0:
                depth -= 1
                current.append(expr[i])
                i += 1
            elif depth == 0 and expr[i:i+len(kw)].lower() == kw:
                parts.append("".join(current))
                current = []
                i += len(kw)
            else:
                current.append(expr[i])
                i += 1
        parts.append("".join(current))
        return parts


# ─── RULE EXECUTOR ────────────────────────────────────────────────────────────

class RuleExecutor:
    """Executes a single rule's action list against a mutable context."""

    def execute(self, actions: List[Dict], context: Dict, rule_id: str) -> List[str]:
        logs = []
        for action in actions:
            log_entry = self._execute_action(action, context, rule_id)
            if log_entry:
                logs.append(log_entry)
        return logs

    def _execute_action(self, action: Dict, ctx: Dict, rule_id: str) -> Optional[str]:
        # SET
        if "set" in action:
            field = action["set"]
            value = action.get("value")
            ctx[field] = value
            return f"[{rule_id}] SET {field} = {repr(value)}"

        # MULTIPLY
        if "multiply" in action:
            field = action["multiply"]
            factor = action.get("by", 1)
            ctx[field] = round(float(ctx.get(field, 0)) * float(factor), 4)
            return f"[{rule_id}] MULTIPLY {field} × {factor} → {ctx[field]}"

        # ADD
        if "add" in action:
            field = action["add"]
            amount = action.get("by", 0)
            ctx[field] = round(float(ctx.get(field, 0)) + float(amount), 4)
            return f"[{rule_id}] ADD {field} + {amount} → {ctx[field]}"

        # SUBTRACT
        if "subtract" in action:
            field = action["subtract"]
            amount = action.get("by", 0)
            ctx[field] = round(float(ctx.get(field, 0)) - float(amount), 4)
            return f"[{rule_id}] SUBTRACT {field} - {amount} → {ctx[field]}"

        # DIVIDE
        if "divide" in action:
            field = action["divide"]
            divisor = action.get("by", 1)
            if float(divisor) != 0:
                ctx[field] = round(float(ctx.get(field, 0)) / float(divisor), 4)
            return f"[{rule_id}] DIVIDE {field} / {divisor} → {ctx.get(field)}"

        # APPEND (to a list field)
        if "append" in action:
            field = action["append"]
            value = action.get("value")
            if not isinstance(ctx.get(field), list):
                ctx[field] = []
            ctx[field].append(value)
            return f"[{rule_id}] APPEND {repr(value)} → {field}"

        # LOG (interpolate context values into message)
        if "log" in action:
            message = str(action["log"])
            for key, val in ctx.items():
                message = message.replace("{" + key + "}", str(val))
            return f"[{rule_id}] LOG: {message}"

        return None


# ─── RULES ENGINE ─────────────────────────────────────────────────────────────

class RulesEngine:
    """
    Main engine. Loads a YAML ruleset, validates it, and evaluates
    rules against provided input data.
    """

    def __init__(self, rules_dir: str = "rules"):
        self.rules_dir = rules_dir
        self.executor = RuleExecutor()
        self._cache: Dict[str, Dict] = {}

    def load_ruleset(self, name: str, force_reload: bool = False) -> Dict:
        """Load and cache a ruleset by name (filename without .yaml)."""
        path = os.path.join(self.rules_dir, f"{name}.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Ruleset '{name}' not found at {path}")

        mtime = os.path.getmtime(path)
        cached = self._cache.get(name)
        if not force_reload and cached and cached.get("_mtime") == mtime:
            return cached

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if "ruleset" not in data:
            raise ValueError(f"YAML missing 'ruleset' key in {name}.yaml")
        if "rules" not in data:
            raise ValueError(f"YAML missing 'rules' key in {name}.yaml")

        # Sort by priority ascending (lower number = higher priority = runs first)
        data["rules"].sort(key=lambda r: r.get("priority", 50))
        data["_mtime"] = mtime
        data["_loaded_at"] = datetime.utcnow().isoformat()
        self._cache[name] = data
        return data

    def list_rulesets(self) -> List[Dict]:
        """Return metadata for all available YAML rulesets."""
        rulesets = []
        for fname in os.listdir(self.rules_dir):
            if fname.endswith(".yaml") or fname.endswith(".yml"):
                name = fname.rsplit(".", 1)[0]
                try:
                    data = self.load_ruleset(name)
                    rulesets.append({
                        "id": name,
                        "name": data["ruleset"].get("name", name),
                        "description": data["ruleset"].get("description", ""),
                        "version": data["ruleset"].get("version", "—"),
                        "author": data["ruleset"].get("author", "—"),
                        "rule_count": len(data.get("rules", [])),
                        "priority_mode": data["ruleset"].get("priority_mode", "all"),
                    })
                except Exception as e:
                    rulesets.append({"id": name, "error": str(e)})
        return rulesets

    def evaluate(self, ruleset_name: str, input_data: Dict,
                 force_reload: bool = False) -> Dict:
        """
        Core evaluation method.
        Returns a detailed result dict with:
          - context: final state of all variables
          - rules_fired: list of rule IDs that matched
          - rules_skipped: list of rule IDs that did not match
          - execution_log: detailed step-by-step trace
          - summary: human-readable summary
          - metadata: timing and ruleset info
        """
        started_at = datetime.utcnow()
        ruleset_data = self.load_ruleset(ruleset_name, force_reload)
        ruleset_meta = ruleset_data["ruleset"]
        rules = ruleset_data.get("rules", [])
        priority_mode = ruleset_meta.get("priority_mode", "all")

        # Deep copy context so input is never mutated
        context = copy.deepcopy(input_data)
        context.setdefault("tags", [])

        rules_fired = []
        rules_skipped = []
        execution_log = []

        for rule in rules:
            rule_id = rule.get("id", "???")
            condition = rule.get("condition", "")
            name = rule.get("name", rule_id)

            # Evaluate condition
            try:
                evaluator = SafeEvaluator(context)
                matched = evaluator.evaluate(condition)
            except Exception as ex:
                execution_log.append({
                    "rule_id": rule_id,
                    "name": name,
                    "matched": False,
                    "error": str(ex),
                    "logs": []
                })
                rules_skipped.append(rule_id)
                continue

            if matched:
                actions = rule.get("actions", [])
                action_logs = self.executor.execute(actions, context, rule_id)
                rules_fired.append(rule_id)
                execution_log.append({
                    "rule_id": rule_id,
                    "name": name,
                    "priority": rule.get("priority", 50),
                    "description": rule.get("description", ""),
                    "condition": condition,
                    "matched": True,
                    "actions_executed": len(actions),
                    "logs": action_logs
                })
                # Stop after first match in first_match mode
                if priority_mode == "first_match":
                    break
            else:
                rules_skipped.append(rule_id)
                execution_log.append({
                    "rule_id": rule_id,
                    "name": name,
                    "priority": rule.get("priority", 50),
                    "condition": condition,
                    "matched": False,
                    "logs": []
                })

        elapsed_ms = round((datetime.utcnow() - started_at).total_seconds() * 1000, 2)

        return {
            "context": context,
            "rules_fired": rules_fired,
            "rules_skipped": rules_skipped,
            "rules_fired_count": len(rules_fired),
            "rules_total": len(rules),
            "execution_log": execution_log,
            "metadata": {
                "ruleset": ruleset_name,
                "ruleset_name": ruleset_meta.get("name"),
                "version": ruleset_meta.get("version"),
                "priority_mode": priority_mode,
                "evaluated_at": started_at.isoformat(),
                "elapsed_ms": elapsed_ms,
            }
        }

    def get_ruleset_yaml(self, name: str) -> str:
        """Return raw YAML content for a ruleset."""
        path = os.path.join(self.rules_dir, f"{name}.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Ruleset '{name}' not found")
        with open(path, "r") as f:
            return f.read()

    def save_ruleset_yaml(self, name: str, content: str) -> Dict:
        """Validate and save updated YAML for a ruleset."""
        # Validate YAML parses correctly
        parsed = yaml.safe_load(content)
        if "ruleset" not in parsed:
            raise ValueError("YAML must contain a 'ruleset' key")
        if "rules" not in parsed:
            raise ValueError("YAML must contain a 'rules' key")

        path = os.path.join(self.rules_dir, f"{name}.yaml")
        with open(path, "w") as f:
            f.write(content)

        # Invalidate cache
        if name in self._cache:
            del self._cache[name]

        return {"saved": True, "path": path, "rule_count": len(parsed["rules"])}
