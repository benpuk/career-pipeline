import { spawnSync } from "node:child_process";
import path from "node:path";

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const env = {
  ...process.env,
  PYTHONPYCACHEPREFIX: process.env.PYTHONPYCACHEPREFIX || path.join(process.cwd(), ".pycache"),
};

const files = [
  "app/app.py",
  "app/app_config.py",
  "app/demo_data.py",
  "app/import_tracker.py",
];

const result = spawnSync(python, ["-m", "py_compile", ...files], {
  env,
  stdio: "inherit",
});

process.exit(result.status ?? 1);
