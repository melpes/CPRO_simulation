# -*- coding: utf-8 -*-
from __future__ import annotations


EMISSION_FACTOR_KWH = 1.0


def from_energy(energy_kwh: float) -> float:
    return energy_kwh * EMISSION_FACTOR_KWH


def total(energy_kwh: float) -> float:
    return from_energy(energy_kwh)
