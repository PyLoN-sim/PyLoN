# Simulator truth: SI units, angles in degrees, resources in KSP resource units.
# All vectors expressed in base_link; east/north/up are instantaneous surface axes.
std_msgs/Header header
string runtime_instance
uint64 runtime_generation
string runtime_epoch
uint64 observation_sequence
string vessel_id
string body_name
float64 universal_time
float64 altitude_asl
float64 altitude_agl
float64 latitude
float64 longitude
float64 mass
float64 liquid_fuel
float64 oxidizer
float64 electric_charge
float64 gravity
float64 body_radius
float64 gravitational_parameter
float64 atmosphere_depth
float64 apoapsis
float64 periapsis
float64 time_to_apoapsis
float64 vertical_speed
float64 horizontal_speed
float64 dynamic_pressure
bool landed
bool splashed
geometry_msgs/Vector3 up_body
geometry_msgs/Vector3 east_body
geometry_msgs/Vector3 north_body
geometry_msgs/Vector3 surface_velocity_body
geometry_msgs/Vector3 orbital_velocity_body
geometry_msgs/Vector3 angular_velocity_body

# Inputs last written by PyLoN into OnFlyByWire, not physical actuator deflection.
bool applied_input_valid
bool flight_command_active
uint64 applied_input_sequence
float64 applied_input_age
float64 applied_pitch
float64 applied_yaw
float64 applied_roll
# True when a normalized input is at its bound; not measured torque saturation.
bool input_at_limit
