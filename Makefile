PYTHON ?= ./.venv/bin/python
PYTHONPATH_ENV = PYTHONPATH=src

.PHONY: test api-local smoke-local install-global prune-reports-dry prune-reports-apply

test:
	$(PYTHONPATH_ENV) $(PYTHON) -m unittest discover -s tests

api-local:
	$(PYTHON) scripts/run_anchor_api.py --host 127.0.0.1 --port 8080 --mode local

smoke-local:
	curl -sS -X POST http://127.0.0.1:8080/anchor/update -H 'Content-Type: application/json' -d '{"conversation_id":"default:make-smoke-001","latest_turns":["Goal: smoke","Decision: continuity enabled"],"force":true}'
	curl -sS -X POST http://127.0.0.1:8080/anchor/render-context -H 'Content-Type: application/json' -d '{"conversation_id":"default:make-smoke-001","user_query":"what is the decision?"}'
	curl -sS -X POST http://127.0.0.1:8080/anchor/ack-response -H 'Content-Type: application/json' -d '{"conversation_id":"default:make-smoke-001","response_text":"Decision: continuity enabled.","turn_id":1}'
	curl -sS "http://127.0.0.1:8080/anchor/latest?conversation_id=default:make-smoke-001"

install-global:
	bash scripts/install_global_continuity.sh

prune-reports-dry:
	$(PYTHON) scripts/prune_reports.py

prune-reports-apply:
	$(PYTHON) scripts/prune_reports.py --apply
