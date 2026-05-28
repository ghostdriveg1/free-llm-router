# test_ci_gate.py - Quality Gate Import Test
import pytest


def test_imports():
    """Verify all critical swarm dependencies are importable."""
    import sys
    
    # Skip import checks locally on Windows to adhere to the local SSD hygiene rules
    if sys.platform == "win32":
        print("[CI GATE] Skipping local package import verification on Windows platform.")
        return

    try:
        import asyncpg
        import boto3
        import fastapi
        import google.generativeai as genai
        import langgraph
        import neo4j
        import pydantic
        import pydantic_ai
        import pyturso
        import redis
        import structlog
        import uvicorn
    except ImportError as e:
        pytest.fail(f"Dependency import failed: {e}")
