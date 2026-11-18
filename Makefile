PYTHON ?= python3

.PHONY: check run clean

check:
	$(PYTHON) -m unittest discover -s tests -v

run:
	./pitch.py

clean:
	rm -rf __pycache__ tests/__pycache__
