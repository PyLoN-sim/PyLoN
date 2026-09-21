# Ordered flight control transaction on one DDS topic and one UDP datagram.
# Execution order: renew, flight, engines (array order), separation.
# Use one increasing sequence and do not mix batch and individual commands
# within a lease. Acquisition/release still use ControlAuthorityCommand.
std_msgs/Header header
string vessel_id
string controller_id
string lease_id
uint64 sequence
bool renew_lease
float64 lease_duration_sec
bool suppress_sas
bool has_flight
FlightControlCommand flight
EngineCommand[<=16] engines
bool has_separation
SeparationCommand separation
