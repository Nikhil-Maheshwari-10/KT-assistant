import os
import sys

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _is_running_via_streamlit() -> bool:
    """Check if this script is being executed by `streamlit run` (not plain `python`).
    Uses importlib to avoid Pylance false-positive on systems where Streamlit
    is only installed inside the poetry venv, not the system Python.
    """
    try:
        import importlib
        mod = importlib.import_module("streamlit.runtime.scriptrunner")
        get_ctx = getattr(mod, "get_script_run_ctx", None)
        return get_ctx is not None and get_ctx() is not None
    except Exception:
        return False

if _is_running_via_streamlit():
    # --- Streamlit Cloud / `streamlit run main.py` ---
    # Streamlit is already running us; just import the UI file to execute it.
    from ui import streamlit  # noqa: F401
else:
    # --- Local: `python main.py` or `poetry run python main.py` ---
    # Launch Streamlit as a subprocess, exactly as before.
    import subprocess

    print("Starting KT Assistant...")
    streamlit_path = os.path.join(os.path.dirname(__file__), "ui", "streamlit.py")

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["streamlit", "run", streamlit_path], env=env)
    except KeyboardInterrupt:
        print("\nStopping KT Assistant...")
    except Exception as e:
        print(f"Error starting KT Assistant: {e}")
        sys.exit(1)
