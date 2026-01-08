FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive

# Base system + build deps (includes cmake + python headers needed for building cyclonedds python bindings)
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      ca-certificates git \
      build-essential cmake pkg-config \
      python3 python3-pip python3-venv python3-dev \
      pipx \
      libssl-dev \
      portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Keep pip tooling current
RUN apt install  python3-setuptools python3-wheel

# ---- Build & install CycloneDDS (C library) ----
WORKDIR /opt
RUN git clone --depth 1 https://github.com/eclipse-cyclonedds/cyclonedds.git -b releases/0.10.x && \
    cd cyclonedds && mkdir build install && cd build &&\
    cmake .. -DCMAKE_INSTALL_PREFIX=../install && \
    cmake --build . --target install
# Let cyclonedds-python (and unitree_sdk2py) find the installed CycloneDDS
ENV CYCLONEDDS_HOME=/opt/cyclonedds/install
ENV CMAKE_PREFIX_PATH=/opt/cyclonedds/install
ENV LD_LIBRARY_PATH=/opt/cyclonedds/install/lib:${LD_LIBRARY_PATH}

# ---- Clone your repos ----
WORKDIR /packages
RUN git clone https://github.com/dgayet/tgn-g1-voice-assistant.git
RUN git clone https://github.com/unitreerobotics/unitree_sdk2_python.git

# ---- Install unitree_sdk2py ----
RUN pip install --break-system-packages -e /packages/unitree_sdk2_python

# ---- Install your assistant requirements ----
RUN pip install --break-system-packages -r /packages/tgn-g1-voice-assistant/requirements.txt

RUN pip install --break-system-packages scipy

RUN apt update && apt install -y alsa-base alsa-utils libasound2t64 && \
    apt install vim nmap -y 

# Keep container running by default
CMD ["bash"]

