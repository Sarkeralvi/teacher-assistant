# Frontend runtime repair

If the frontend starts returning stale or broken runtime output after a rebuild/recreate, use the repo-local repair path:

```bash
rm -rf apps/web/.next
cd apps/web && npm run build
make frontend-health
```

Current setup notes:

- The frontend container bind-mounts `./apps/web` for live edits.
- The container keeps `node_modules` in a named volume.
- The container keeps `.next` in a named volume so host-side build artifacts do not get mixed into the running container.
- Frontend health is checked at `GET /health`.

If the container still behaves badly after a repair, recreate only the frontend service:

```bash
docker compose up -d --no-deps --force-recreate frontend
```

Do not delete database volumes or uploaded data to fix a frontend build artifact problem.
