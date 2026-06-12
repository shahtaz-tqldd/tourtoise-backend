# CI/CD setup

This repository deploys from the `prod` branch through GitHub Actions.

## Workflow

The workflow is defined in `.github/workflows/prod-ci-cd.yml`.

- Pull requests into `prod`: install dependencies, run Django checks, check migrations, run tests, and build the production Docker image.
- Pushes to `prod`: run the same CI job, then deploy to the production server after CI succeeds.
- Manual runs: available from the GitHub Actions tab through `workflow_dispatch`.

## Required GitHub secrets

Add these in GitHub under `Settings` -> `Secrets and variables` -> `Actions`.

| Secret | Required | Description |
| --- | --- | --- |
| `PROD_HOST` | Yes | Production server hostname or IP address. |
| `PROD_USER` | Yes | SSH user used for deployment. |
| `PROD_SSH_KEY` | Yes | Private SSH key with access to the production server. |
| `PROD_PORT` | No | SSH port. Defaults to `22`. |
| `PROD_APP_DIR` | No | Repository path on the production server. Defaults to `/var/www/tourtoise-core`. |

## Production server requirements

The production server must have:

- Git
- Docker with the Compose plugin
- A checked-out copy of this repository at `PROD_APP_DIR`
- A production `.env` file in `PROD_APP_DIR`
- The deploy SSH key added to the server user's `~/.ssh/authorized_keys`

The workflow deploy step runs:

```bash
git fetch origin prod
git checkout prod
git pull --ff-only origin prod
docker compose -p tourtoise-core-prod --env-file .env -f docker/compose.prod.yml up --build -d
docker image prune -f
```

Keep production-only values in the server `.env` file, not in the repository.
