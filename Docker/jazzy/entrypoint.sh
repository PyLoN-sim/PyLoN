#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/pylon_ws/install/local_setup.bash
exec "$@"
