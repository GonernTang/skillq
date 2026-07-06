---
name: grpc-kv-server
description: Build a Python gRPC server providing a simple key-value store (Get/Set RPCs) backed by an in-memory dict. Use when the task is to scaffold a gRPC service in Python with proto definition, code generation, and a thread-pooled server bound to a configurable port.
---

# Build a gRPC Key-Value Store Server (Python)

## When to use
The task asks for a small gRPC service exposing Get/Set (or similar CRUD) operations on keys, implemented in Python with an in-memory backing store.

## Procedure

1. **Install dependencies** via pip:
   - `grpcio` (runtime)
   - `grpcio-tools` (codegen for `.proto`)

2. **Define the service in a `.proto` file** (e.g. `kvstore.proto`):
   - Declare `syntax = "proto3";`
   - Declare a `package` and a `service` with the RPCs required (e.g. `rpc GetVal(Key) returns (Value);`, `rpc SetVal(KeyValue) returns (Status);`).
   - Define request/response `message` types with primitive fields appropriate to the store (e.g. `string key`, `int32 value`, `bool found`).

3. **Generate Python stubs** using `grpc_tools.protoc`:
   ```
   python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. kvstore.proto
   ```
   This produces `<name>_pb2.py` (messages) and `<name>_pb2_grpc.py` (servicers/stubs).

4. **Implement a servicer subclass** of the generated `*Servicer` base class:
   - Hold state in an in-memory `dict` (mapping `key -> value`).
   - Override each RPC method declared in the `.proto`.
   - For `Get`-style RPCs, handle the missing-key case by returning a sentinel/default value and/or a `found` flag set to `false`.
   - For `Set`-style RPCs, write the value into the dict and return an acknowledgement/`Status`.

5. **Wire up the server**:
   ```python
   from concurrent import futures
   import grpc

   server = grpc.server(futures.ThreadPoolExecutor(max_workers=N))
   <service>_pb2_grpc.add_<Service>Servicer_to_server(<ServicerImpl>(), server)
   server.add_insecure_port("[::]:<PORT>")
   server.start()
   server.wait_for_termination()
   ```
   Choose a worker count sized to expected concurrency; bind the port to all interfaces (or a specific address) per the task. `wait_for_termination()` keeps the process alive.

6. **Smoke test** (optional but recommended) by instantiating a channel on the same port and calling the RPCs from a stub to confirm read/write round-trip and missing-key behaviour.

## Notes
- Use `add_insecure_port` only for local/dev/test; production should switch to credentials.
- Generated modules import each other with bare names, so the directory containing `<name>_pb2_grpc.py` must be on `PYTHONPATH` (or run from that directory).
- If the proto's RPC signatures differ (e.g. a single `SetVal(KeyValue)` versus separate `Key`/`Value` messages), match the message types exactly when overriding — Python's dynamic typing won't catch a mismatched attribute.