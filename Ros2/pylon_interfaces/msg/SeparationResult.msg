# Operation identity is immutable across topology changes and lease replacement.
std_msgs/Header header
string operation_id
string original_runtime_instance
string original_runtime_epoch
string original_vessel_id
uint64 original_runtime_generation
string id
string controller_id
uint64 sequence
# Pending receipts have completed=false; only success=true confirms separation.
bool completed
bool success
# True if KSP holds this receipt in its bounded operation journal.
bool retained
string reason
string result_runtime_epoch
uint64 result_runtime_generation
string active_vessel_id
string[] resulting_vessel_ids
float64 retention_remaining_sec
