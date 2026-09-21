# Heartbeat health uses real time; progression uses KSP universal time.
# Published during pause and packed warp, independently of physics sensors.
uint8 STATE_INITIALIZING=0
uint8 STATE_ADVANCING=1
uint8 STATE_PAUSED=2
uint8 STATE_STALLED=3
uint8 STATE_UNAVAILABLE=4
uint8 STATE_STALE=5

# Receipt time, not the simulation clock (which can be paused).
std_msgs/Header header
string vessel_id
string runtime_instance
string runtime_epoch
uint64 runtime_generation
# Unity frame number shared with other telemetry; compare only within an epoch.
uint64 observation_sequence
uint8 state
bool communication_alive
# Last observed flags; do not treat them as current when communication_alive=false.
bool paused
bool packed
bool physics_warp
# Whether the vessel is unpacked and commands can currently be accepted.
bool control_available
# True only when UT advanced between the latest two heartbeat observations.
bool simulation_advancing
float64 universal_time
float64 realtime_since_startup
float64 warp_rate
float64 seconds_since_progress
float64 heartbeat_age_sec
