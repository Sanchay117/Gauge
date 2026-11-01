"""List the model ids this Model API key can call. Prints ids only.

Usage: uv run --env-file .env spikes/models.py
"""
import json
import os
import urllib.error
import urllib.request

request = urllib.request.Request("https://api.meta.ai/v1/models",
                                 headers={"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}"})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    for model in body.get("data", body if isinstance(body, list) else []):
        print(model.get("id"))
except urllib.error.HTTPError as err:
    print("status", err.code)
