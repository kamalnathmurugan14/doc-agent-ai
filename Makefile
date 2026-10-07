.PHONY: test backend-test frontend-test lint

test: backend-test frontend-test

backend-test:
	cd backend && ruff check . && black --check . && pytest --cov=app

frontend-test:
	cd frontend && npm run test:all
