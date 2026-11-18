#!/usr/bin/env python3
"""Prove nvJPEG GPU-hybrid batch decode with pixels and CUDA kernel tracing."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone


SOURCE = Path(__file__).with_name("probe-nvjpeg-gpu-batch.c")


def run(command, timeout=60):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=timeout)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")

    with tempfile.TemporaryDirectory(prefix="p16-nvjpeg-gpu-") as folder:
        work = Path(folder)
        executable = work / "probe"
        jpeg = work / "testsrc.jpg"
        nvjpeg_rgb = work / "nvjpeg.rgb"
        software_rgb = work / "software.rgb"
        encoded_jpeg = work / "nvjpeg-encoded.jpg"
        encoded_software_rgb = work / "encoded-software.rgb"
        report = work / "gpu-hybrid"
        run(["/usr/bin/gcc", "-std=c11", "-O2", "-Wall", "-Wextra",
             "-I/opt/cuda/include", str(SOURCE), "-L/opt/cuda/lib64",
             "-Wl,-rpath,/opt/cuda/lib64", "-lnvjpeg", "-lcudart",
             "-o", str(executable)])
        run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=1",
             "-frames:v", "1", "-q:v", "2", "-y", str(jpeg)])
        stream = json.loads(run(["/usr/bin/ffprobe", "-v", "error",
                                 "-select_streams", "v:0", "-show_entries",
                                 "stream=profile,pix_fmt,width,height", "-of",
                                 "json", str(jpeg)]).stdout)["streams"][0]
        profile = run(["/usr/bin/nsys", "profile", "--trace=cuda",
                       "--sample=none", "--force-overwrite=true", "--output",
                       str(report), str(executable), str(jpeg), str(nvjpeg_rgb),
                       str(encoded_jpeg)],
                      timeout=120)
        probe = json.loads(next(line for line in profile.stdout.splitlines()
                                if line.startswith('{"backend":')))
        run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", str(jpeg), "-frames:v", "1", "-pix_fmt", "rgb24",
             "-f", "rawvideo", "-y", str(software_rgb)])
        run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", str(encoded_jpeg), "-frames:v", "1", "-pix_fmt", "rgb24",
             "-f", "rawvideo", "-y", str(encoded_software_rgb)])
        encoded_stream = json.loads(run(["/usr/bin/ffprobe", "-v", "error",
                                         "-select_streams", "v:0", "-show_entries",
                                         "stream=profile,pix_fmt,width,height", "-of",
                                         "json", str(encoded_jpeg)]).stdout)["streams"][0]
        stats = run(["/usr/bin/nsys", "stats", "--report", "cuda_gpu_kern_sum",
                     "--format", "csv", str(report) + ".nsys-rep"], timeout=90)
        csv_output = stats.stdout[stats.stdout.index("Time (%),"):]
        rows = list(csv.DictReader(io.StringIO(csv_output)))
        kernels = [{"name": row["Name"], "instances": int(row["Instances"]),
                    "total_time_ns": int(row["Total Time (ns)"])} for row in rows]
        actual = nvjpeg_rgb.read_bytes()
        expected = software_rgb.read_bytes()
        encoded_decoded = encoded_software_rgb.read_bytes()
        if len(actual) != len(expected) or len(actual) != len(encoded_decoded):
            raise RuntimeError("nvJPEG/software RGB size mismatch")
        squared = sum((a - b) ** 2 for a, b in zip(actual, expected))
        absolute = sum(abs(a - b) for a, b in zip(actual, expected))
        mse = squared / len(actual)
        max_error = max(abs(a - b) for a, b in zip(actual, expected))
        encode_mse = sum((a - b) ** 2 for a, b in zip(actual, encoded_decoded)) / len(actual)
        gpu_huffman = any("DecodeBatchedCujpeg::decodeDcHuffman" in row["name"]
                          for row in kernels)
        gpu_encode = any("nvjpeg::encoding::ACKernel" in row["name"]
                         for row in kernels)
        result = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
            "driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                           "--format=csv,noheader"]).stdout.strip(),
            "cuda_package": run(["/usr/bin/pacman", "-Q", "cuda"]).stdout.strip(),
            "source_sha256": sha256(SOURCE.read_bytes()),
            "executable_sha256": sha256(executable.read_bytes()),
            "input_jpeg_sha256": sha256(jpeg.read_bytes()),
            "jpeg_stream": stream,
            "nvjpeg": probe,
            "software_rgb_sha256": sha256(expected),
            "nvjpeg_rgb_sha256": sha256(actual),
            "encoded_jpeg_sha256": sha256(encoded_jpeg.read_bytes()),
            "encoded_jpeg_stream": encoded_stream,
            "encoded_software_rgb_sha256": sha256(encoded_decoded),
            "mean_absolute_error": absolute / len(actual),
            "max_absolute_error": max_error,
            "mse": mse,
            "psnr_db": math.inf if mse == 0 else 10 * math.log10(255 * 255 / mse),
            "encode_roundtrip_mse": encode_mse,
            "encode_roundtrip_psnr_db": (math.inf if encode_mse == 0 else
                                         10 * math.log10(255 * 255 / encode_mse)),
            "cuda_gpu_kernels": kernels,
            "gpu_huffman_kernel_observed": gpu_huffman,
            "gpu_encode_kernel_observed": gpu_encode,
            "camera_or_test_pixels_retained": False,
        }
        result["pass"] = (stream["profile"] == "Baseline" and
                          stream["width"] == 320 and stream["height"] == 180 and
                          probe["batch"] == 64 and
                          probe["batch_output_identical"] and
                          probe["rgb_bytes"] == len(actual) and
                          probe["encode_backend"] == "NVJPEG_ENC_BACKEND_GPU" and
                          probe["encoded_jpeg_bytes"] == encoded_jpeg.stat().st_size and
                          encoded_stream["profile"] == "Baseline" and
                          encoded_stream["width"] == 320 and
                          encoded_stream["height"] == 180 and
                          gpu_huffman and gpu_encode and mse < 1 and
                          max_error <= 4 and
                          result["encode_roundtrip_psnr_db"] >= 35)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "batch": probe["batch"],
                      "gpu_huffman_kernel_observed": gpu_huffman,
                      "gpu_encode_kernel_observed": gpu_encode,
                      "psnr_db": result["psnr_db"],
                      "encode_roundtrip_psnr_db": result["encode_roundtrip_psnr_db"],
                      "max_absolute_error": max_error}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
