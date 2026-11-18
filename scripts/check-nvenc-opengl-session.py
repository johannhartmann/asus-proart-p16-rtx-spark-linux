#!/usr/bin/env python3
"""Build the direct EGL/OpenGL NVENC session probe against two header sets."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def run(command, timeout=30):
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers-12-2", type=Path, required=True)
    parser.add_argument("--headers-13-1", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).with_name("probe-nvenc-session-opengl.c")
    driver = run(["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"])
    result = {"source": str(source), "driver_and_gpu": driver.stdout.strip(),
              "device_type": "NV_ENC_DEVICE_TYPE_OPENGL",
              "cases": {}, "pass": False}
    with tempfile.TemporaryDirectory(prefix="p16-nvenc-gl-") as temporary:
        for label, headers in (("12.2", args.headers_12_2), ("13.1", args.headers_13_1)):
            executable = Path(temporary) / f"probe-{label}"
            compile_result = run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                                  f"-I{headers / 'include'}", str(source),
                                  "-lEGL", "-lGL", "-lnvidia-encode", "-o", str(executable)])
            if compile_result.returncode:
                raise RuntimeError(f"{label} build failed: {compile_result.stderr}")
            probe = run([str(executable)])
            fields = dict(re.findall(r"(\w+)=([^\s]+)", probe.stdout))
            case = {"header_tree": str(headers), "compile_exit_code": compile_result.returncode,
                    "probe_exit_code": probe.returncode,
                    "gl_vendor": re.search(r"gl_vendor=(.+?) gl_renderer=", probe.stdout).group(1)
                    if " gl_renderer=" in probe.stdout else None,
                    "gl_renderer": re.search(r"gl_renderer=(.+)", probe.stdout).group(1)
                    if "gl_renderer=" in probe.stdout else None,
                    "header_api_version": fields.get("header_api_version"),
                    "driver_max_api_version": fields.get("driver_max_api_version"),
                    "create_instance_status": int(fields["create_instance_status"])
                    if "create_instance_status" in fields else None,
                    "open_session_status": int(fields["open_session_status"])
                    if "open_session_status" in fields else None,
                    "stderr": probe.stderr.strip()}
            result["cases"][label] = case
    result["pass"] = any(case["open_session_status"] == 0 for case in result["cases"].values())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
