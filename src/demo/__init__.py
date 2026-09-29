"""Demo package: synthetic sample documents + offline demo run."""

from .runner import run_demo
from .samples import generate_demo_documents

__all__ = ["generate_demo_documents", "run_demo"]
