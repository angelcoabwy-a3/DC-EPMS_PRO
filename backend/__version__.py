"""
backend/__version__.py
======================
Canonical version string for DC-EPMS PRO.

This file is the **single source of truth** for the application's
version across the stack:

* ``backend/main.py`` imports ``__version__`` and uses it both as the
  ``FastAPI(..., version=...)`` arg (drives the OpenAPI doc + Swagger
  banner) and as the ``version`` field of ``GET /api/health``. The
  boot log emits ``[BUILD] DC-EPMS_PRO=v<__version__>`` so a
  ``tail -f logs/epms_pro.log`` line confirms the deployed code
  matches what the operator expects.

* ``package.json`` mirrors this number for the Node-side test harness
  (Vitest). Bumping ``__version__`` here MUST be paired with the same
  bump in ``package.json``.

* ``frontend/assets/js/core/version.js`` mirrors it for the HMI
  footer stamp + the bootstrap console banner. Same bump rule.

* ``frontend/index.html`` carries a fallback ``v<x.y.z>`` literal in
  the footer + the sidebar header; the bootstrap code overwrites it
  on load using the JS mirror, so the HTML literal is only visible
  during the brief boot-script window.

Release flow:

  1. Bump ``__version__`` here.
  2. Bump ``package.json``.
  3. Bump ``APP_VERSION`` in ``frontend/assets/js/core/version.js``.
  4. Update the literal in ``frontend/index.html`` (footer + sidebar).
  5. Tag the repo: ``git tag -a v<x.y.z> -m "..."``.
"""

__version__ = "0.17.0"
