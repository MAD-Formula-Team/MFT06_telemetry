"""Núcleo de ROBOWIN 2.

Regla de oro: este paquete NUNCA importa Qt. Toda la lógica es testeable
headless; la UI consume snapshots a través de interfaces thread-safe.
"""
