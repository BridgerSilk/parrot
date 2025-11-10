from pathlib import Path
import importlib.util
import subprocess
import sys
import traceback
from typing import Optional
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parent.parent
CONVERTER_PATH = ROOT / "mml_converter.py"

def _load_converter_module():
    """
    Load the mml_converter.py from the project root (CONVERTER_PATH) using spec_from_file_location.
    This avoids depending on sys.path and ensures we load the user's file.
    """
    if not CONVERTER_PATH.exists():
        print(f"[parrot] mml_converter.py not found at {CONVERTER_PATH}")
        return None

    try:
        spec = importlib.util.spec_from_file_location("mml_converter", str(CONVERTER_PATH))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # may raise; catch in caller
        return module
    except Exception as e:
        print(f"[parrot] Failed to load mml_converter.py: {e}")
        traceback.print_exc()
        return None

def _run_subprocess_and_capture(mml_path: str) -> Optional[str]:
    """
    Fallback: run `python mml_converter.py <mml_path> --stdout` (tries several variants)
    and return stdout if it looks like HTML.
    """
    attempts = [
        [sys.executable, str(CONVERTER_PATH), mml_path, "--stdout"],
        [sys.executable, str(CONVERTER_PATH), mml_path, "-"],
        [sys.executable, str(CONVERTER_PATH), mml_path],
    ]
    for cmd in attempts:
        try:
            proc = subprocess.run(cmd, capture_output=True, check=False, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout and proc.stdout.strip():
                return proc.stdout
            # if there's stderr, print it for debugging
            if proc.stderr:
                print(f"[parrot] converter stderr for {' '.join(cmd)}:\n{proc.stderr}")
        except Exception as e:
            print(f"[parrot] subprocess attempt failed ({' '.join(cmd)}): {e}")
    return None

def convert_mml_file_to_html_string(mml_path: str) -> Optional[str]:
    """
    Convert an MML file to an HTML string using the user's converter.

    This function:
    1. Loads mml_converter.py directly from project root.
    2. Tries to call functions in several ways:
       - fn(input_path, output_path)  (writes file)
       - fn(input_path)              (returns string)
       - fn(mml_content)             (content-based converter)
    3. If the converter writes a file, read the temp file and return its contents.
    4. If import/calls fail, fallback to subprocess invocation.
    """
    mml_path = str(mml_path)
    module = _load_converter_module()
    if module is None:
        return _run_subprocess_and_capture(mml_path)

    # Candidate function names that may convert files
    file_fn_candidates = ("compile_mml_to_html", "convert_file", "convert_mml_to_html", "convert")
    for fn_name in file_fn_candidates:
        fn = getattr(module, fn_name, None)
        if not callable(fn):
            continue

        # Try calling with (input, out) and with (input,) and handle both return-or-write behaviours.
        # Use a temporary file for output if needed.
        tmp_path = None
        try:
            with NamedTemporaryFile("w+b", suffix=".html", delete=False) as tmp:
                tmp_path = tmp.name

            # First try calling with (input, out_path)
            try:
                ret = fn(mml_path, tmp_path)
            except TypeError:
                # try single-arg call
                try:
                    ret = fn(mml_path)
                except TypeError:
                    # unknown signature; skip to next candidate
                    ret = None

            # If function returned a string, use it
            if isinstance(ret, str) and ret.strip():
                return ret

            # Otherwise, try reading the temp file if it exists
            try:
                with open(tmp_path, "r", encoding="utf-8") as f:
                    data = f.read()
                if data and data.strip():
                    return data
            except Exception:
                # no usable temp output
                pass

        except Exception as e:
            print(f"[parrot] Error when calling {fn_name}: {e}")
            traceback.print_exc()
            # try next candidate
            continue
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass

    # Fallback: maybe the module exposes a content-based converter that takes MML text
    content_fn = getattr(module, "convert_mml_to_html", None)
    if callable(content_fn):
        try:
            with open(mml_path, "r", encoding="utf-8") as f:
                mml_content = f.read()
            ret = content_fn(mml_content)
            if isinstance(ret, str) and ret.strip():
                return ret
        except Exception as e:
            print(f"[parrot] Fallback content conversion failed: {e}")
            traceback.print_exc()

    # Last resort: subprocess invocation
    return _run_subprocess_and_capture(mml_path)
