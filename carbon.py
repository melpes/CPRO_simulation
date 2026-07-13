from __future__ import annotations

EmissionFactor = 1.0


def TotalEmission(energy_kwh):
    return energy_kwh * EmissionFactor
