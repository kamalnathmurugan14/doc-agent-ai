# Contributing

1. Fork, create a branch, make your change.
2. Backend: `cd backend && pip install -r requirements-dev.txt && ruff check . && black --check . && pytest`
3. Frontend: `cd frontend && npm install && npm run test:all`
4. Use conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
5. Never commit `.env` files or real documents.
