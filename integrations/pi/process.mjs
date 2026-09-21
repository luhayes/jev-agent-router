import { spawn } from "node:child_process";

/** Local CLI only: no shell, credentials stay in inherited environment. */
export function runCli(payload, signal, options = {}) {
  if (signal?.aborted) return Promise.reject(new Error("Jev routing cancelled"));
  return new Promise((resolve, reject) => {
    const child = spawn(options.command ?? process.env.JEV_ROUTE_BIN ?? "jev-route", options.args ?? [], {
      shell: false, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
    });
    let output = "", bytes = 0, stopped = false;
    let killTimer;
    const cleanup = () => {
      clearTimeout(timer);
      clearTimeout(killTimer);
      signal?.removeEventListener("abort", abort);
    };
    const stop = (message) => {
      if (stopped) return;
      stopped = true;
      child.kill("SIGTERM");
      killTimer = setTimeout(() => child.kill("SIGKILL"), 250);
      reject(new Error(message));
    };
    const abort = () => stop("Jev routing cancelled");
    const timer = setTimeout(() => stop("Jev routing timed out"), options.timeoutMs ?? 50000);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", chunk => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > 1024 * 1024) stop("Jev response too large");
      else output += chunk;
    });
    child.stderr.resume(); // Drain but never expose dependency messages or secrets.
    child.stdin.on("error", () => stop("Jev input failed"));
    child.on("error", () => { cleanup(); reject(new Error("Jev CLI could not start")); });
    child.on("close", code => {
      cleanup();
      if (stopped) return;
      if (code !== 0) return reject(new Error("Jev CLI failed; check configuration"));
      try { resolve(JSON.parse(output)); }
      catch { reject(new Error("Jev CLI returned invalid JSON")); }
    });
    try { child.stdin.end(JSON.stringify(payload)); }
    catch { stop("Jev request is not JSON serializable"); }
  });
}
