# Build Hornet GUI into a macOS .app and DMG

This uses PyInstaller to create a one-file app bundle and hdiutil to package it into a DMG.

Requirements
- Python 3.10+
- PyInstaller
- openai, python-dotenv (for LLM features)

Build steps
```bash path=null start=null
python -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install pyinstaller openai python-dotenv

# Build .app (non-windowed console=False because we want a windowed app)
pyinstaller \
  --name Hornet \
  --windowed \
  --noconfirm \
  --osx-bundle-identifier com.example.hornet \
  hornet_gui.py

# Create DMG
APP_PATH="dist/Hornet.app"
DMG_PATH="dist/Hornet.dmg"
[ -d "$APP_PATH" ] || { echo "App not found at $APP_PATH"; exit 1; }
hdiutil create -volname "Hornet" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"

# IMPORTANT: Do not bundle secrets
# Do NOT bake your OPENAI_API_KEY into the app. Instead, set it per-user in ~/.hornet/.env. See OPENAI.md.

# Output path
echo "DMG created at: $DMG_PATH"
```

Notes
- The app stores test runners and logs in ~/.hornet/<repo-name>.
- The selected target path is exposed to runners via HORNET_TARGET_REPO_PATH.
