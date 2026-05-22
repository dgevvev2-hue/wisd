"""List all sound devices (input/output) so the user can pick mic and output."""
import sounddevice as sd

print("Available audio devices:\n")
for i, d in enumerate(sd.query_devices()):
    kind = []
    if d["max_input_channels"] > 0:
        kind.append(f"IN={d['max_input_channels']}")
    if d["max_output_channels"] > 0:
        kind.append(f"OUT={d['max_output_channels']}")
    print(f"  [{i:2d}]  {', '.join(kind):12s}  hostapi={d['hostapi']}  {d['name']}")

print()
print(f"Default input : {sd.default.device[0]}")
print(f"Default output: {sd.default.device[1]}")
print()
print("Host APIs:")
for i, h in enumerate(sd.query_hostapis()):
    print(f"  [{i}] {h['name']}")
