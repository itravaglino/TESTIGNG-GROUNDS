"""Planilla estándar de forecast para probar salidas de otros modelos."""

from planilla.sheet import load
from planilla.verify import compare, verify

__all__ = ["compare", "load", "verify"]
