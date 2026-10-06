# Build context: PyLoN repository root.
ARG ROS_IMAGE=ros:jazzy-ros-base-noble@sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca
FROM ${ROS_IMAGE} AS builder
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
WORKDIR /opt/pylon_ws

# Resolve manifests before copying implementation files to cache dependencies.
COPY Ros2/pylon_interfaces/package.xml src/pylon_interfaces/package.xml
COPY Ros2/pylon_bridge/package.xml src/pylon_bridge/package.xml
COPY Ros2/pylon_vehicle_control/package.xml src/pylon_vehicle_control/package.xml
RUN apt-get update && rosdep update --rosdistro jazzy && \
    rosdep install --from-paths src --ignore-src --rosdistro jazzy -y && \
    apt-get install -y --no-install-recommends python3-pytest && \
    rm -rf /var/lib/apt/lists/*
COPY Ros2/pylon_interfaces src/pylon_interfaces
COPY Ros2/pylon_bridge src/pylon_bridge
COPY Ros2/pylon_vehicle_control src/pylon_vehicle_control
RUN source /opt/ros/jazzy/setup.bash && \
    colcon build --packages-up-to pylon_bridge pylon_vehicle_control \
      --executor sequential --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

# Run explicitly with --target test; production does not contain test sources.
FROM builder AS test
RUN source /opt/ros/jazzy/setup.bash && source install/local_setup.bash && \
    python3 -m pytest -q src/pylon_bridge/test && \
    python3 -m pytest -q src/pylon_vehicle_control/test

FROM ${ROS_IMAGE} AS runtime
LABEL org.opencontainers.image.source="https://github.com/PyLoN-sim/PyLoN" \
      org.opencontainers.image.description="PyLoN bridge and vehicle control on ROS 2 Jazzy" \
      org.opencontainers.image.licenses="MIT"
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-diagnostic-msgs ros-jazzy-geometry-msgs ros-jazzy-sensor-msgs \
      ros-jazzy-std-msgs ros-jazzy-tf2-ros ros-jazzy-tf2-msgs \
      ros-jazzy-rosidl-default-runtime ros-jazzy-rmw-cyclonedds-cpp && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 --shell /bin/bash pylon
COPY --from=builder /opt/pylon_ws/install /opt/pylon_ws/install
COPY LICENSE /opt/pylon/LICENSE
COPY Docker/jazzy/entrypoint.sh /pylon-entrypoint.sh
RUN chmod 755 /pylon-entrypoint.sh
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    ROS_DOMAIN_ID=0 \
    PYTHONUNBUFFERED=1
USER pylon
WORKDIR /opt/pylon_ws
ENTRYPOINT ["/pylon-entrypoint.sh"]
CMD ["ros2", "run", "pylon_bridge", "udp_bridge", "--host", "127.0.0.1", "--port", "49010", "--command-host", "127.0.0.1", "--command-port", "49011"]
