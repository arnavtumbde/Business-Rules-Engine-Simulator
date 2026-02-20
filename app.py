"""
app.py — Flask REST API for the Business Rules Engine
======================================================
Endpoints:
  GET  /api/rulesets                         List all available rulesets
  GET  /api/rulesets/<name>                  Get ruleset metadata + rules
  GET  /api/rulesets/<name>/yaml             Get raw YAML source
  PUT  /api/rulesets/<name>/yaml             Update YAML (live hot-reload)
  POST /api/evaluate/<name>                  Evaluate rules against input JSON
  POST /api/evaluate/<name>?debug=true       Same but includes full execution trace
  GET  /api/health                           Health check
  GET  /                                     Serve dashboard UI
"""

import os
import json
from flask import Flask, request, jsonify, send_from_directory
from rules_engine import RulesEngine

app = Flask(__name__, static_folder="static")
engine = RulesEngine(rules_dir=os.path.join(os.path.dirname(__file__), "rules"))


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def ok(data, status=200):
    return jsonify({"status": "ok", **data}), status

def err(message, status=400, details=None):
    payload = {"status": "error", "message": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status


# ─── HEALTH ───────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return ok({"engine": "running", "rulesets_loaded": len(engine.list_rulesets())})


# ─── RULESETS ─────────────────────────────────────────────────────────────────

@app.route("/api/rulesets", methods=["GET"])
def list_rulesets():
    """List all available rulesets with their metadata."""
    try:
        rulesets = engine.list_rulesets()
        return ok({"rulesets": rulesets, "count": len(rulesets)})
    except Exception as e:
        return err(str(e), 500)


@app.route("/api/rulesets/<name>", methods=["GET"])
def get_ruleset(name):
    """Get full ruleset detail including all rules."""
    try:
        data = engine.load_ruleset(name, force_reload=True)
        # Remove internal cache keys
        return ok({
            "ruleset": data["ruleset"],
            "rules": data["rules"],
            "context": data.get("context", []),
            "rule_count": len(data["rules"]),
        })
    except FileNotFoundError:
        return err(f"Ruleset '{name}' not found", 404)
    except Exception as e:
        return err(str(e), 500)


@app.route("/api/rulesets/<name>/yaml", methods=["GET"])
def get_ruleset_yaml(name):
    """Get the raw YAML source of a ruleset."""
    try:
        content = engine.get_ruleset_yaml(name)
        return app.response_class(content, mimetype="text/plain; charset=utf-8")
    except FileNotFoundError:
        return err(f"Ruleset '{name}' not found", 404)
    except Exception as e:
        return err(str(e), 500)


@app.route("/api/rulesets/<name>/yaml", methods=["PUT"])
def update_ruleset_yaml(name):
    """
    Update a ruleset's YAML — this is the hot-reload endpoint.
    Send the new YAML as plain text in the request body.
    Rules engine picks up changes immediately, no restart needed.
    """
    content = request.get_data(as_text=True)
    if not content.strip():
        return err("Request body cannot be empty")
    try:
        result = engine.save_ruleset_yaml(name, content)
        return ok(result)
    except FileNotFoundError:
        return err(f"Ruleset '{name}' not found", 404)
    except ValueError as e:
        return err("Invalid YAML structure", 400, str(e))
    except Exception as e:
        return err(str(e), 500)


# ─── EVALUATE ─────────────────────────────────────────────────────────────────

@app.route("/api/evaluate/<name>", methods=["POST"])
def evaluate(name):
    """
    Evaluate rules against provided input data.

    Request body (JSON):
    {
      "age": 65,
      "smoker": false,
      "bmi": 24.5,
      "region": "south",
      "accidents": 0,
      "base_premium": 400.00
    }

    Query params:
      ?debug=true   Include full execution trace in response
      ?reload=true  Force re-read of YAML file (bypass cache)
    """
    try:
        input_data = request.get_json(force=True, silent=True) or {}
    except Exception:
        return err("Invalid JSON in request body")

    debug = request.args.get("debug", "false").lower() == "true"
    force_reload = request.args.get("reload", "false").lower() == "true"

    try:
        result = engine.evaluate(name, input_data, force_reload=force_reload)
    except FileNotFoundError:
        return err(f"Ruleset '{name}' not found", 404)
    except Exception as e:
        return err("Evaluation error", 500, str(e))

    response = {
        "input": input_data,
        "output": result["context"],
        "rules_fired": result["rules_fired"],
        "rules_fired_count": result["rules_fired_count"],
        "rules_total": result["rules_total"],
        "metadata": result["metadata"],
    }

    if debug:
        response["execution_trace"] = result["execution_log"]

    return ok(response)


# ─── BATCH EVALUATE ───────────────────────────────────────────────────────────

@app.route("/api/evaluate/<name>/batch", methods=["POST"])
def batch_evaluate(name):
    """
    Evaluate rules against multiple input records at once.

    Request body: {"records": [{...}, {...}]}
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
        records = body.get("records", [])
        if not isinstance(records, list):
            return err("'records' must be a list")
    except Exception:
        return err("Invalid JSON in request body")

    results = []
    for i, record in enumerate(records):
        try:
            r = engine.evaluate(name, record)
            results.append({
                "index": i,
                "input": record,
                "output": r["context"],
                "rules_fired": r["rules_fired"],
                "elapsed_ms": r["metadata"]["elapsed_ms"],
            })
        except Exception as e:
            results.append({"index": i, "input": record, "error": str(e)})

    return ok({
        "results": results,
        "total_records": len(records),
        "ruleset": name,
    })


# ─── SERVE UI ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "dashboard.html")


if __name__ == "__main__":
    print("\n╔══════════════════════════════════════════════════╗")
    print("║     Business Rules Engine — REST API Server      ║")
    print("╠══════════════════════════════════════════════════╣")
    print("║  Dashboard:  http://localhost:5000/              ║")
    print("║  API Base:   http://localhost:5000/api           ║")
    print("║  Health:     http://localhost:5000/api/health    ║")
    print("╚══════════════════════════════════════════════════╝\n")
    app.run(debug=True, port=5000)
