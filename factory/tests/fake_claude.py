"""Stands in for the claude CLI in tests: reads the prompt, acts as FAKE_CLAUDE_ACTION says, prints stream-json."""

import json
import os
import sys
import time
from pathlib import Path

prompt = sys.stdin.read()
action = os.environ.get("FAKE_CLAUDE_ACTION", "")
args = sys.argv[1:]
settings = json.loads(Path(args[args.index("--settings") + 1]).read_text(encoding="utf-8"))
Path(".factory-out").mkdir(exist_ok=True)
Path(".factory-out/args.json").write_text(json.dumps({"args": args, "settings": settings}), encoding="utf-8")

for item in filter(None, action.split(";")):
    verb, _, rest = item.partition(":")
    if verb == "write":
        path, _, source = rest.partition("=")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(Path(source).read_text(encoding="utf-8") if source else "x\n", encoding="utf-8")
    elif verb == "sleep":
        time.sleep(float(rest))

print(json.dumps({"type": "system", "subtype": "init", "model": args[args.index("--model") + 1]}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 7, "result": "Done.",
                  "total_cost_usd": 0.4321,
                  "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 50}}))
