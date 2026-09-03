"""Shared pytest fixtures.

Tests that touch matplotlib should set the Agg backend themselves so this
file stays neutral for the existing solver tests.
"""

from __future__ import annotations
