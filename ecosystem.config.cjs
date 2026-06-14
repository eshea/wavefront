module.exports = {
  apps: [
    {
      name: "wavefront",
      script: "app.py",
      interpreter: process.env.PYTHON || ".venv/bin/python",
      cwd: __dirname,
      env: {
        HOST: "0.0.0.0",
        PORT: process.env.APP_PORT || "8002",
        FLASK_DEBUG: "0",
      },
    },
  ],
};
