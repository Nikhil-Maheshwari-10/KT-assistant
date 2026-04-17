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
    # Use runpy.run_path() instead of `from ui import streamlit`.
    # REASON: On every user interaction, Streamlit re-runs main.py.
    # A plain `import` would be CACHED by Python and produce no output on re-runs → blank screen.
    # runpy.run_path() executes the file directly every time, bypassing the module cache.
    import runpy
    _ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "streamlit.py")
    runpy.run_path(_ui_path, run_name="__main__")
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
