## OpenHaC LaTeX report

This folder contains a **hand-maintained** LaTeX report describing OpenHaC.

### Build the PDF

Preferred (LuaLaTeX if available, otherwise pdfLaTeX):

```bash
python3 scripts/build_latex_report.py
```

Manual build (LuaLaTeX):

```bash
mkdir -p docs/internal/report/build
lualatex -interaction=nonstopmode -halt-on-error -output-directory docs/internal/report/build docs/internal/report/openhac_report.tex
lualatex -interaction=nonstopmode -halt-on-error -output-directory docs/internal/report/build docs/internal/report/openhac_report.tex
```

The output PDF is written to `docs/internal/report/build/openhac_report.pdf`.

