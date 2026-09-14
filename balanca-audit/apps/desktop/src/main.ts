import path from "node:path";
import { app, BrowserWindow, shell } from "electron";

const webUrl = process.env.BALANCA_WEB_URL;

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: "Gerenciamento Agricola",
    backgroundColor: "#f5f6f8",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (webUrl || !app.isPackaged) {
    window.loadURL(webUrl ?? "http://localhost:8873");
  } else {
    window.loadFile(path.resolve(import.meta.dirname, "../../web/dist/index.html"));
  }

  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
