std_msgs/Header header
string vessel_id
string runtime_instance
string runtime_epoch
uint64 runtime_generation
uint64 observation_sequence
float64 universal_time
# KSP ElectricCharge units, summed over all parts (including locked resources).
float64 electric_charge
float64 electric_capacity
# Estimated d(stored ElectricCharge)/d(UT), EC per simulation second.
# Positive means charging. Full/empty storage can hide generation or demand.
float64 net_charge_rate_estimate
bool net_charge_rate_valid
float64 rate_sample_interval_sec
# Generation and consumption cannot be recovered separately from charge delta.
# Numeric placeholders are not measurements when their validity flags are false.
float64 generation_rate
bool generation_rate_valid
float64 consumption_rate
bool consumption_rate_valid
