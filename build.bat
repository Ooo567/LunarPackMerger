@echo off
REM Local build script (Windows). For a "clean" build with no personal
REM path info baked in, prefer the GitHub Actions workflow instead —
REM it builds on GitHub's own servers.

python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm --onefile --windowed --name "LunarPackMerger" --clean main.py

echo.
echo Build complete. Find your exe in the "dist" folder.
pause
