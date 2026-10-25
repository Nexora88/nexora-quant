module.exports = {
  apps: [
    {
      name: "nexora-quant",
      cwd: "/opt/nexora-quant",
      script: ".venv/bin/python",
      args: "-m app.main",
      interpreter: "none",
      autorestart: true,
      max_restarts: 50,
      min_uptime: "10s",
      env: { PYTHONUNBUFFERED: "1" },
    },
  ],
};
