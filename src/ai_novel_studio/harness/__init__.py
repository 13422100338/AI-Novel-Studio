"""Harness orchestration layer (design v0.3).

The Harness owns run lifecycle, model role binding, tool and skill dispatch,
approval waits, and recovery. Backend owns domain truth; this package never
stores novel facts, plans, or states, and backend domain modules must never
import it (contract §3).
"""
