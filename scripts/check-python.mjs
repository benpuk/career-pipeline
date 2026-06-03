import { spawnSync } from "node:child_process";
import path from "node:path";

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const env = {
  ...process.env,
  PYTHONPYCACHEPREFIX: process.env.PYTHONPYCACHEPREFIX || path.join(process.cwd(), ".pycache"),
};

const files = [
  "local-job-crm/app.py",
  "local-job-crm/app_config.py",
  "local-job-crm/demo_data.py",
  "local-job-crm/import_tracker.py",
];

const result = spawnSync(python, ["-m", "py_compile", ...files], {
  env,
  stdio: "inherit",
});

process.exit(result.status ?? 1);
