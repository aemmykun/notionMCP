#!/bin/bash
# Verify packaging tool versions to confirm CVE mitigations

echo "=== Packaging Tool Versions ==="
echo -n "pip: "
python -m pip --version | awk '{print $2}'

echo -n "setuptools: "
python -c "import setuptools; print(setuptools.__version__)"

echo -n "wheel (vendored in setuptools): "
python -c "import setuptools._vendor.wheel as w; print(w.__version__)" 2>/dev/null || echo "N/A"

echo -n "wheel (installed): "
python -c "import wheel; print(wheel.__version__)" 2>/dev/null || echo "Not installed"

echo ""
echo "=== Expected Versions ==="
echo "pip: 26.0.1"
echo "setuptools: 82.0.1"
echo "wheel (vendored): Should be >= 0.46.2"
echo ""
echo "=== Python Version ==="
python --version
