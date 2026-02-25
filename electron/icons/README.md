# App Icon

Place `app.png` here to set the application icon in the taskbar and window decorations.

- **Format:** PNG with transparency recommended
- **Size:** 256×256 or 512×512 px (larger is better; Electron scales down as needed)
- **Activation:** automatic — `electron/main.js` checks for this file at startup

The app runs without an icon if this file is absent — no error, no crash.

## Quick option

Any existing sprite PNG from `frontend/static/assets/spritesheets/` will work as a
placeholder (they're 32×32, so quality will be low, but it gets something in the taskbar):

```bash
cp frontend/static/assets/spritesheets/<any>.png electron/icons/app.png
```
