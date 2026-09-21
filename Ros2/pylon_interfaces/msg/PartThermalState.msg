# One part per message; compare frame/epoch to join with vessel power state.
std_msgs/Header header
string vessel_id
string runtime_instance
string runtime_epoch
uint64 runtime_generation
uint64 observation_sequence
float64 universal_time
uint32 part_flight_id
uint32 part_persistent_id
string part_name
# Internal and skin temperatures and failure limits, in kelvin.
float64 temperature
float64 max_temperature
float64 skin_temperature
float64 max_skin_temperature
bool shielded_from_airstream
# KSP ElectricCharge units; no fixed conversion to joules is assumed.
float64 electric_charge
float64 electric_capacity
