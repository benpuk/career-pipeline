import { spawn } from "node:child_process";
import path from "node:path";

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const env = {
  ...process.env,
  PYTHONPYCACHEPREFIX: process.env.PYTHONPYCACHEPREFIX || path.join(process.cwd(), ".pycache"),
};

const child = spawn(python, ["local-job-crm/app.py"], {
  env,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
