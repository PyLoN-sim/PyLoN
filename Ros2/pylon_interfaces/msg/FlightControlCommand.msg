# Lease-bound stock flight inputs. Engines use EngineCommand separately.
# Normalized KSP inputs, not radians or ROS body torques.
std_msgs/Header header
string vessel_id
string controller_id
string lease_id
uint64 sequence
float64 pitch
float64 yaw
float64 roll
bool landing_gear
float64 timeout_sec
