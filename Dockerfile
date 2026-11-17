FROM --platform=linux/amd64 ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libgl1 libfontconfig1 libx11-6 libfreetype6 xvfb xauth && rm -rf /var/lib/apt/lists/*
ENV QT_QPA_PLATFORM=xcb
