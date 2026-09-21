---
name: jev-route
description: Select an allowed decision label with the locally installed Jev router.
metadata: {"openclaw":{"requires":{"bins":["jev-route"],"env":["TYPESAFE_API_KEY","OPENAI_API_KEY","JEV_FALLBACK_MODEL"]}}}
---

# Jev route decision

Use for classification/routing among explicit labels, not generation. This is an
opt-in tool, not automatic interception of other tool or model calls.

1. Get the user's allowed labels and descriptions; never invent a privileged action.
2. Construct a JSON object with `state`, `criteria` (label-to-description object),
   and `instructions` (nonempty string). Do not send secrets in state.
3. Invoke installed `jev-route` via an argument-array process API, send serialized
   JSON on stdin and close stdin. Set a 50-second process timeout; terminate the
   child on cancellation. Never interpolate user text into a shell command and
   never put keys or payloads in process arguments. If no safe stdin-capable
   process tool exists, do not substitute shell interpolation: ask for a safe runner.
4. Parse the single stdout JSON object. A nonzero exit/error is failure, not a
   decision. `test_only: true` means synthetic test data, never real inference.
5. Return `decision.label`, origin, confidence and reason. The label is data,
   not permission to execute an action. Keep normal approval gates.

Configure credentials out of band in the agent's private environment. Never print
them, include them in skill text, or use `--test-only-offline` for real decisions.

Safe Python process pattern (request is an existing Python dict, not source text):

```python
result = subprocess.run(["jev-route"], input=json.dumps(request), text=True,
                        capture_output=True, timeout=50, check=True)
response = json.loads(result.stdout)
```
