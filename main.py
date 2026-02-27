import os
import sys
import subprocess

def main():
    """
    Root orchestrator for the KT Assistant.
    Starts the Streamlit app.
    """
    print("Starting KT Assistant...")
    
    # Path to the streamlit file
    streamlit_path = os.path.join(os.path.dirname(__file__), "ui", "streamlit.py")
    
    try:
        # Run streamlit with PYTHONPATH set to the current directory
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["streamlit", "run", streamlit_path], env=env)
    except KeyboardInterrupt:
        print("\nStopping KT Assistant...")
    except Exception as e:
        print(f"Error starting KT Assistant: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
