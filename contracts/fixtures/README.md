# UI fixtures

After the local official-data sync, run:

```powershell
uv run nycp fixtures export
```

Generated JSON is intentionally not committed. It reflects the current local
SQLite data version and generated OpenAPI contract.
