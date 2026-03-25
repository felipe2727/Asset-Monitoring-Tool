"""
Sentinel Pipeline — Modal Deployment
=====================================
Deploy:  modal deploy modal_app.py
Run now: modal run modal_app.py
Logs:    modal app logs sentinel-pipeline
"""
import modal

app = modal.App("sentinel-pipeline")

# Container image with all pip dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .copy_local_dir("sentinel", "/root/sentinel")
    .copy_local_file("main.py", "/root/main.py")
)

# Persistent volume for SQLite DB, logs, and cache
volume = modal.Volume.from_name("sentinel-data", create_if_missing=True)

# All API keys stored as a single Modal secret
secrets = modal.Secret.from_name("sentinel-keys")


@app.function(
    image=image,
    secrets=[secrets],
    volumes={"/data": volume},
    schedule=modal.Cron("0 14 * * *"),  # 9 AM EST / 2 PM UTC
    timeout=1800,  # 30 min max
    memory=2048,   # 2 GB RAM
)
async def run_daily():
    """Scheduled daily pipeline run."""
    import os
    os.chdir("/root")

    # Ensure volume subdirectories exist
    os.makedirs("/data/logs/emails", exist_ok=True)
    os.makedirs("/data/cache", exist_ok=True)

    from main import run_pipeline
    await run_pipeline()

    # Commit volume writes so they persist
    volume.commit()


@app.local_entrypoint()
def main():
    """Manual trigger: `modal run modal_app.py`"""
    run_daily.remote()
