"""Contrato y verificación de la planilla estándar de forecast."""

from planilla.parser import cargar
from planilla.verificar import comparar, verificar

__all__ = ["cargar", "comparar", "verificar"]
