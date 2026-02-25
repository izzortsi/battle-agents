'use strict';

const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const net = require('net');
const path = require('path');
const fs = require('fs');

// Project root is one level up from electron/
const APP_ROOT = path.join(__dirname, '..');

let pythonProcess = null;
let mainWindow = null;

// ---------------------------------------------------------------------------
// Port discovery — ask the OS for a free ephemeral port
// ---------------------------------------------------------------------------
function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

// ---------------------------------------------------------------------------
// Poll until the FastAPI server responds (or timeout)
// ---------------------------------------------------------------------------
function waitForServer(url, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const poll = () => {
      http.get(url, (res) => {
        res.resume(); // drain response so the socket closes cleanly
        resolve();
      }).on('error', () => {
        if (Date.now() >= deadline) {
          return reject(new Error(`Server did not start within ${timeoutMs / 1000}s`));
        }
        setTimeout(poll, 250);
      });
    };
    poll();
  });
}

// ---------------------------------------------------------------------------
// Spawn the Python FastAPI server
// ---------------------------------------------------------------------------
function startPythonServer(port) {
  // Prefer the project's own venv; fall back to system python3 / python
  const venvPy = path.join(APP_ROOT, '.venv', 'bin', 'python');
  const pythonExe = fs.existsSync(venvPy)
    ? venvPy
    : (process.platform === 'win32' ? 'python' : 'python3');

  const serverScript = path.join(APP_ROOT, 'frontend', 'server', 'app.py');

  console.log(`[electron] Starting Python server on port ${port}`);
  console.log(`[electron] Python:  ${pythonExe}`);
  console.log(`[electron] Script:  ${serverScript}`);

  pythonProcess = spawn(
    pythonExe,
    [serverScript, '--port', String(port)],
    {
      cwd: APP_ROOT,
      env: { ...process.env, PYTHONPATH: APP_ROOT },
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );

  pythonProcess.stdout.on('data', (d) => process.stdout.write(`[python] ${d}`));
  pythonProcess.stderr.on('data', (d) => process.stderr.write(`[python] ${d}`));

  pythonProcess.on('exit', (code, signal) => {
    console.log(`[electron] Python exited (code=${code}, signal=${signal})`);
    pythonProcess = null;
    // If the server crashes, close the window too
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.close();
    }
  });
}

// ---------------------------------------------------------------------------
// Terminate the Python process gracefully
// ---------------------------------------------------------------------------
function stopPythonServer() {
  if (!pythonProcess) return;
  console.log('[electron] Stopping Python server...');
  pythonProcess.kill('SIGTERM');
  pythonProcess = null;
}

// ---------------------------------------------------------------------------
// Hot reload — dev only, disabled in packaged builds
// ---------------------------------------------------------------------------
function setupHotReload(win) {
  if (app.isPackaged) return;

  const watchDir = path.join(APP_ROOT, 'frontend', 'static');
  const watchers = [];
  let debounceTimer = null;

  const scheduleReload = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (win && !win.isDestroyed()) {
        console.log('[electron] Hot reload triggered');
        win.webContents.reloadIgnoringCache();
      }
    }, 300);
  };

  // Walk the directory tree and register fs.watch() on each subdirectory.
  // The {recursive: true} flag is only reliable on macOS/Windows; on Linux
  // we enumerate manually for cross-platform consistency.
  function watchRecursive(dir) {
    try {
      const watcher = fs.watch(dir, (eventType, filename) => {
        if (filename) scheduleReload();
      });
      watcher.on('error', () => {}); // suppress stale-handle errors
      watchers.push(watcher);
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
          watchRecursive(path.join(dir, entry.name));
        }
      }
    } catch {
      // Unreadable directory — skip silently
    }
  }

  watchRecursive(watchDir);
  console.log(`[electron] Hot reload: watching ${watchDir}`);

  win.on('closed', () => {
    clearTimeout(debounceTimer);
    for (const w of watchers) w.close();
  });
}

// ---------------------------------------------------------------------------
// Create the main BrowserWindow
// ---------------------------------------------------------------------------
function createWindow(url) {
  const iconPath = path.join(__dirname, 'icons', 'app.png');

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#1a1a2e', // --bg-primary from layout.css — prevents white flash
    show: false,                 // reveal only after content is ready
    title: 'Battle-Agents',
    ...(fs.existsSync(iconPath) && { icon: iconPath }),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(url);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  setupHotReload(mainWindow);

  mainWindow.on('closed', () => {
    mainWindow = null;
    stopPythonServer();
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  try {
    const port = await findFreePort();
    startPythonServer(port);

    const serverUrl = `http://127.0.0.1:${port}`;
    await waitForServer(serverUrl);

    createWindow(serverUrl);
  } catch (err) {
    console.error('[electron] Startup failed:', err);
    dialog.showErrorBox(
      'Battle-Agents — startup error',
      `Could not launch the Python server:\n\n${err.message}`
    );
    stopPythonServer();
    app.quit();
  }
});

app.on('window-all-closed', () => {
  stopPythonServer();
  app.quit();
});

// Ensure Python is killed if Electron is terminated abnormally
process.on('exit',   () => stopPythonServer());
process.on('SIGTERM', () => { stopPythonServer(); process.exit(0); });
process.on('SIGINT',  () => { stopPythonServer(); process.exit(0); });
