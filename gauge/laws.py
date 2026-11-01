"""Candidate physical laws, model selection, and held-out verification.

Each law splits parameters into `law` constants, which must survive a new run, and `nuisance`
values such as start position, which legitimately differ between runs.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import curve_fit


@dataclass(frozen=True)
class Law:
    name: str
    description: str
    params: tuple[str, ...]
    law_params: tuple[str, ...]
    func: object
    guess: object


def _quadratic(t, a, v0, s0):
    return 0.5 * a * t**2 + v0 * t + s0


def _linear(t, v, s0):
    return v * t + s0


def _damped(t, omega, gamma, amp, phase, offset):
    return amp * np.exp(-gamma * t) * np.cos(omega * t + phase) + offset


def _relax(t, tau, amp, final):
    return amp * np.exp(-t / tau) + final


def _guess_quadratic(t, y):
    a, v0, s0 = np.polyfit(t, y, 2)
    return [2 * a, v0, s0]


def _guess_linear(t, y):
    return list(np.polyfit(t, y, 1))


def _guess_damped(t, y):
    centred = y - y.mean()
    grid = np.linspace(t[0], t[-1], 512)
    spectrum = np.abs(np.fft.rfft(np.interp(grid, t, centred)))
    freqs = np.fft.rfftfreq(len(grid), grid[1] - grid[0])
    peak = int(np.argmax(spectrum[1:])) + 1
    return [2 * np.pi * freqs[peak], 0.1, float(np.ptp(y) / 2), 0.0, float(y.mean())]


def _guess_relax(t, y):
    return [float(np.ptp(t) / 3), float(y[0] - y[-1]), float(y[-1])]


LAWS = {
    "constant_velocity": Law("constant_velocity", "s = v t + s0", ("v", "s0"), ("v",), _linear, _guess_linear),
    "constant_acceleration": Law("constant_acceleration", "s = a t^2 / 2 + v0 t + s0",
                                 ("a", "v0", "s0"), ("a",), _quadratic, _guess_quadratic),
    "damped_oscillation": Law("damped_oscillation", "s = A exp(-gamma t) cos(omega t + phi) + c",
                              ("omega", "gamma", "amp", "phase", "offset"), ("omega", "gamma"),
                              _damped, _guess_damped),
    "exponential_relaxation": Law("exponential_relaxation", "s = A exp(-t / tau) + c",
                                  ("tau", "amp", "final"), ("tau",), _relax, _guess_relax),
}


@dataclass
class Fit:
    law: str
    values: dict[str, float]
    errors: dict[str, float]
    rms: float
    aicc: float
    r2: float
    n: int
    derived: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"law": self.law, "equation": LAWS[self.law].description, "values": self.values,
                "errors": self.errors, "rms_m": self.rms, "aicc": self.aicc, "r2": self.r2,
                "n": self.n, "derived": self.derived}


def _aicc(residual: np.ndarray, k: int) -> float:
    n = len(residual)
    rss = max(float(np.sum(residual**2)), 1e-18)
    aic = n * np.log(rss / n) + 2 * k
    return aic + (2 * k * (k + 1) / (n - k - 1) if n > k + 1 else np.inf)


def fit_law(name: str, t: np.ndarray, y: np.ndarray) -> Fit:
    law = LAWS[name]
    if len(t) <= len(law.params):
        raise ValueError(f"{name} needs more than {len(law.params)} samples")
    popt, pcov = curve_fit(law.func, t, y, p0=law.guess(t, y), maxfev=20000)
    residual = y - law.func(t, *popt)
    errors = np.sqrt(np.clip(np.diag(pcov), 0, None))
    total = float(np.sum((y - y.mean()) ** 2)) or 1e-18
    derived = {}
    if name == "damped_oscillation":
        popt[0] = abs(popt[0])
        derived["period_s"] = 2 * np.pi / popt[0]
    return Fit(name, dict(zip(law.params, map(float, popt))), dict(zip(law.params, map(float, errors))),
               float(np.sqrt(np.mean(residual**2))), float(_aicc(residual, len(popt))),
               1 - float(np.sum(residual**2)) / total, len(t), derived)


def select_law(t: np.ndarray, y: np.ndarray, names: list[str] | None = None) -> list[Fit]:
    """Rank candidates by AICc, which penalises extra parameters."""
    fits = []
    for name in names or list(LAWS):
        try:
            fits.append(fit_law(name, t, y))
        except (RuntimeError, ValueError):
            continue
    return sorted(fits, key=lambda f: f.aicc)


@dataclass
class Verdict:
    passed: bool
    reason: str
    constants: dict[str, dict]
    held_rms: float
    free_rms: float
    n: int

    def to_dict(self) -> dict:
        return vars(self)


def verify(fit: Fit, t: np.ndarray, y: np.ndarray, tolerance: float = 0.08) -> Verdict:
    """Freeze the law's constants, refit only nuisance values on a new run, and score the prediction."""
    law = LAWS[fit.law]
    frozen = {p: fit.values[p] for p in law.law_params}
    free = [p for p in law.params if p not in frozen]

    def predict(t_, *nuisance):
        values = {**frozen, **dict(zip(free, nuisance))}
        return law.func(t_, *[values[p] for p in law.params])

    start = fit_law(fit.law, t, y)
    p0 = [start.values[p] for p in free]
    nuisance, _ = curve_fit(predict, t, y, p0=p0, maxfev=20000)
    held_rms = float(np.sqrt(np.mean((y - predict(t, *nuisance)) ** 2)))

    constants, agree = {}, True
    for p in law.law_params:
        before, after = fit.values[p], start.values[p]
        spread = abs(after - before) / max(abs(before), 1e-12)
        sigma = np.hypot(fit.errors[p], start.errors[p])
        ok = spread <= tolerance or abs(after - before) <= 3 * sigma
        agree &= bool(ok)
        constants[p] = {"run_1": before, "run_2": after, "difference": spread, "agrees": bool(ok)}

    # Freezing a true law should cost little, so a big rise in error means it failed to predict.
    fits_well = held_rms <= 2 * start.rms + 1e-3
    passed = agree and fits_well
    if passed:
        reason = "the law from run 1 predicted run 2"
    elif not agree:
        reason = "the constants changed between runs"
    else:
        reason = "the law from run 1 did not fit run 2"
    return Verdict(passed, reason, constants, held_rms, start.rms, len(t))
