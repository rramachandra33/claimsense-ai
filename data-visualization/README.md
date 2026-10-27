# ClaimSense Case Explorer

An interactive viewer for the 150 evaluation cases. Pick a case to follow it from the request, through the access check, the facts computed by code, the documents, clause retrieval and the model's draft, to adjuster confirmation and the eval gate checks.

Hosted copy (private until shared): https://claude.ai/artifact/P6RGcFMzXRjZuTnyBMcX3P

| File | Purpose |
|---|---|
| `claim-explorer.html` | The page (React 18 + htm, loaded from CDNs; no build step) |
| `data.json` | Data bundle the page loads, generated from `data/synthetic/` and `evals/` |
| `build_data.py` | Rebuilds `data.json` |

## Refresh after changing the data

```bash
python3 scripts/generate_synthetic_data.py   # if you changed the generator
python3 data-visualization/build_data.py
```

To update the hosted copy, ask Claude to republish `data-visualization/claim-explorer.html` with `data.json` to the URL above.

## View locally

Browsers block `fetch()` from `file://`, so serve the folder:

```bash
python3 -m http.server 8000 --directory data-visualization
# open http://localhost:8000/claim-explorer.html
```

The HTML has no `<!doctype>` or `<head>` because the artifact host adds them when it publishes. Browsers render it fine locally without them.
