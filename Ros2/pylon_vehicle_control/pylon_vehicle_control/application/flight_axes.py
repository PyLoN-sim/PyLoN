"""Normalized stock input mapping for PyLoN's right-handed base_link axes.

Positive body-axis effort maps to stock pitch=-Y, yaw=-Z, roll=+X.
These are input signs, not a torque magnitude or a guarantee of acceleration.
"""
import math


def stock_inputs_for_body_axes(effort):
    if len(effort) != 3 or any(isinstance(v, bool) or not math.isfinite(v) or abs(v) > 1 for v in effort):
        raise ValueError('body-axis input must contain three finite values in [-1, 1]')
    x, y, z = effort
    return -y, -z, x
