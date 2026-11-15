"""The state cursor: a pointer into the graph of hashed circuit states, with a separate incumbent (the best valid
state), guarded steps, rollback and an append-only journal, evaluated locally with BitSim. `ssr.rat` drives the same
kind of walk on the native engine."""


def __getattr__(name):   # lazy: importing ssr.cursor does not import kickmix
    if name in ("StateCursor", "CircuitMouse"):
        from ssr.cursor import environment
        return getattr(environment, name)
    raise AttributeError(name)
