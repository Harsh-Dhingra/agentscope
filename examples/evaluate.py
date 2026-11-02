"""Generate a fresh measured report from the local API."""

import argparse
import json
import os
from pathlib import Path
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="data/experiment.json")
args = parser.parse_args()
with httpx.Client(timeout=60, trust_env=False) as client:
    response = client.post("http://127.0.0.1:8765/api/experiments", headers={"Authorization": f"Bearer {os.environ['AGENTSCOPE_API_KEY']}"})
    response.raise_for_status()
report = response.json()
path = Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report["summary"], indent=2))
print(f"Wrote {path}")
