- **CI: měření pokrytí kódu testy** – job „Testy (ubuntu-latest, Python 3.12)“ spouští `pytest` s
  `--cov=envocad --cov-report=xml --cov-report=term`: přehled pokrytí po modulech je v logu jobu a `coverage.xml`
  jako artefakt `coverage-ubuntu-latest-3.12`. Bez prahu – CI kvůli pokrytí nepadá; ostatní joby běží beze změny.
  `.github/workflows/ci.yml`.
