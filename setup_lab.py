#!/usr/bin/env python3
"""Atalho de compatibilidade para ``infra/setup_lab.py``.

A implementação da orquestração (Milestone 2) fica em ``infra/setup_lab.py``.
Este arquivo existe apenas para preservar o comando histórico ``setup_lab.py``
usado no Milestone 1.
"""

from infra.setup_lab import main

if __name__ == "__main__":
    raise SystemExit(main())
