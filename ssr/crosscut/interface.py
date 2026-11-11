"""Native Rat query wrapper for exact idle-wire information boundaries."""

from __future__ import annotations

from pathlib import Path

from ssr.crosscut import information_boundary as boundary
from ssr.crosscut import rule as _rule
from ssr.qhdl import bitsim as _bitsim
from ssr.qhdl import cheap_function as _cheap_function
from ssr.rat import interface as base


class Rat(base.Rat):
    @classmethod
    def core_fingerprints(cls):
        return {**super().core_fingerprints(), **{
            str(Path(path).resolve()): base.old_sha(path)
            for path in (__file__, boundary.__file__, _rule.__file__,
                         _bitsim.__file__, _cheap_function.__file__)}}

    def observe(self):
        result = super().observe()
        result["queries"] = list(result.get("queries", [])) + ["information_boundary"]
        result["information_boundary_scope"] = "exact all legal invsqrt x under fixed zero HMR outcomes"
        return result

    def query(self, request, expected):
        if not isinstance(request, dict) or request.get("type") != "information_boundary":
            return super().query(request, expected)
        self._expected(expected)
        if set(request) != {"type", "wire", "start", "stop"}:
            raise ValueError("information_boundary requires wire, start and stop")
        if any(type(request[name]) is not int for name in ("wire", "start", "stop")):
            raise ValueError("information_boundary boundaries must be integers")
        if self._count("investigation_started") >= 12:
            raise ValueError("query budget exhausted")
        state = self.current
        self._event("investigation_started", {"state_sha256": state, "request": request})
        result = boundary.locate(self._path(state), request["wire"], request["start"], request["stop"])
        result = {"status": result["status"], "state_sha256": state,
                  "query": "information_boundary", "result": result}
        self._event("information_boundary", {"state_sha256": state, "result": result})
        return result
