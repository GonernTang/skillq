"""Regression test for Task #10 — env-driven default for editor_model.

Bug (2026-06-25 full run):
    MethodConfig.editor_model defaulted to "openai/gpt-4o" even though
    the host has no OPENAI_API_KEY. Every trial end called Layer 3
    Edit → litellm raised InternalServerError("Missing credentials")
    → the bridge swallowed the error. Layer 4 (batched extract on
    failure) never got a chance to run, so the agent never created
    any skills during the run.

Fix:
    Default `editor_model` and `attribution_model` to
    `anthropic/${ANTHROPIC_MODEL}` so the litellm path uses the same
    Anthropic-compatible endpoint the rest of the pipeline already
    uses. Hard-coded openai/ defaults are no longer silently wrong.

This test asserts:
    1. EditRefiner() with no model arg defaults to
       `anthropic/<ANTHROPIC_MODEL>`.
    2. MethodConfig() with no editor_model / attribution_model fields
       likewise defaults to `anthropic/<ANTHROPIC_MODEL>`.
    3. Explicit overrides still win.
"""
from __future__ import annotations

import os

import pytest


def test_edit_refiner_default_uses_anthropic_prefix(monkeypatch):
    """EditRefiner() with no model arg → anthropic/<ANTHROPIC_MODEL>."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-flash")
    from skillq.layers.l3_attribution.edit import EditRefiner, StubEditBackend

    refiner = EditRefiner(backend=StubEditBackend())
    assert refiner.model == "anthropic/deepseek-v4-flash"


def test_method_config_default_editor_model(monkeypatch):
    """MethodConfig() with no editor_model → anthropic/<ANTHROPIC_MODEL>."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-flash")
    from skillq.config import MethodConfig

    cfg = MethodConfig()
    assert cfg.editor_model == "anthropic/deepseek-v4-flash"
    assert cfg.attribution_model == "anthropic/deepseek-v4-flash"


def test_explicit_override_still_wins(monkeypatch):
    """Pass editor_model explicitly → override beats env-driven default."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-flash")
    from skillq.config import MethodConfig

    cfg = MethodConfig(editor_model="openai/gpt-4o-mini")
    assert cfg.editor_model == "openai/gpt-4o-mini"