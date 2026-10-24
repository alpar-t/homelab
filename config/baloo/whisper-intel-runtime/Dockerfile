# syntax=docker/dockerfile:1
# Isolate the SYCL build toolchain from the copied runtime artifacts. The
# final Intel base must be scanned before claiming any CVE reduction.
# Both stages use the same oneAPI/Ubuntu release for ABI parity.
FROM docker.io/intel/oneapi-basekit:2025.2.2-0-devel-ubuntu24.04@sha256:863d7dd7cfd637294c0dc0febad7d5252c0d274947d509eb2aad78d5ea505053 AS build

ARG WHISPER_COMMIT=8a9ad7844d6e2a10cddf4b92de4089d7ac2b14a9
ARG WYOMING_CLIENT_COMMIT=45382bc998d57c8312e1f3bef6a537eed6db217e

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates cmake git build-essential python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/ggml-org/whisper.cpp.git /whisper.cpp \
    && git -C /whisper.cpp checkout --detach "$WHISPER_COMMIT" \
    && cmake -S /whisper.cpp -B /whisper.cpp/build \
      -DGGML_SYCL=ON -DGGML_SYCL_F16=ON \
      -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx \
    && cmake --build /whisper.cpp/build --parallel 2

RUN git clone https://github.com/ser/wyoming-whisper-api-client.git /wyoming-whisper-api-client \
    && git -C /wyoming-whisper-api-client checkout --detach "$WYOMING_CLIENT_COMMIT"

COPY requirements.txt /tmp/wyoming-requirements.txt
RUN python3 -m venv /opt/wyoming-venv \
    && /opt/wyoming-venv/bin/pip install --no-cache-dir -r /tmp/wyoming-requirements.txt

RUN mkdir -p /runtime-root/whisper.cpp/build/bin \
      /runtime-root/whisper.cpp/build/src \
      /runtime-root/whisper.cpp/build/ggml/src/ggml-sycl \
    && cp -a /whisper.cpp/build/bin/whisper-server /runtime-root/whisper.cpp/build/bin/ \
    && cp -a /whisper.cpp/build/src/libwhisper.so* /runtime-root/whisper.cpp/build/src/ \
    && cp -a /whisper.cpp/build/ggml/src/libggml*.so* /runtime-root/whisper.cpp/build/ggml/src/ \
    && cp -a /whisper.cpp/build/ggml/src/ggml-sycl/libggml-sycl.so* \
      /runtime-root/whisper.cpp/build/ggml/src/ggml-sycl/

FROM docker.io/intel/oneapi-runtime:2025.2.2-0-devel-ubuntu24.04@sha256:d431954c4dc7c388f74d4e873263faed89d61fb3d6ab61537750045a42edc796

RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates python3 wget intel-oneapi-umf-0.11 \
    && apt-get -s purge linux-libc-dev libc6-dev build-essential cmake gcc g++ git python3-dev \
      > /tmp/purge-plan \
    && ! grep -Eq '^(Remv|Purg) (intel-|oneapi-|libze|libmkl|libdnnl|libsycl)' /tmp/purge-plan \
    && apt-get purge -y linux-libc-dev libc6-dev build-essential cmake gcc g++ git python3-dev \
    && ! dpkg-query -W linux-libc-dev >/dev/null 2>&1 \
    && rm -rf /var/lib/apt/lists/*

# Preserve the build path because whisper-server's linked libraries resolve
# from /whisper.cpp/build. Copy linked artifacts without CMake objects or headers.
COPY --from=build /runtime-root/ /
COPY --from=build /opt/wyoming-venv /opt/wyoming-venv
COPY --from=build /wyoming-whisper-api-client/wyoming_whisper_api_client /wyoming-whisper-api-client/wyoming_whisper_api_client
COPY --from=build /whisper.cpp/LICENSE /licenses/whisper.cpp-LICENSE
COPY --from=build /wyoming-whisper-api-client/LICENSE /licenses/wyoming-whisper-api-client-LICENSE
COPY start-whisper.sh /usr/local/bin/start-whisper.sh

ENV PYTHONPATH=/wyoming-whisper-api-client \
    LD_LIBRARY_PATH=/opt/intel/oneapi/umf/0.11/lib:/opt/intel/oneapi/tcm/1.4/lib:/opt/intel/oneapi/compiler/latest/lib:/opt/intel/oneapi/compiler/latest/linux/lib:/opt/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/opt/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/opt/intel/oneapi/mkl/latest/lib

# SYCL loads its Level Zero adapter dynamically, so checking only the
# whisper-server ELF misses adapter dependencies such as libumf.so.0.
RUN chmod +x /usr/local/bin/start-whisper.sh \
    && ldd /whisper.cpp/build/bin/whisper-server > /tmp/whisper-ldd \
    && ! grep -q 'not found' /tmp/whisper-ldd \
    && ldd /opt/intel/oneapi/redist/lib/libur_adapter_level_zero.so.0 > /tmp/level-zero-ldd \
    && ! grep -q 'not found' /tmp/level-zero-ldd \
    && ldd /opt/intel/oneapi/redist/lib/libur_adapter_level_zero_v2.so.0 > /tmp/level-zero-v2-ldd \
    && ! grep -q 'not found' /tmp/level-zero-v2-ldd \
    && /opt/wyoming-venv/bin/python -m wyoming_whisper_api_client --version

# Exercise the real module entrypoint without an inference request or GPU.
RUN /opt/wyoming-venv/bin/python - <<'PY'
import socket
import subprocess
import time

process = subprocess.Popen(
    ['/opt/wyoming-venv/bin/python', '-m', 'wyoming_whisper_api_client',
     '--uri', 'tcp://127.0.0.1:17891',
     '--api', 'http://127.0.0.1:8910/inference'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError('Wyoming adapter exited during startup')
        try:
            with socket.create_connection(('127.0.0.1', 17891), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError('Wyoming adapter did not open its TCP listener')
finally:
    process.terminate()
    process.wait(timeout=5)
PY

EXPOSE 7891
ENTRYPOINT ["/usr/local/bin/start-whisper.sh"]
