---
name: python-grpc-server
description: Build and run a Python gRPC service from scratch. Use when implementing a gRPC server whose contract is defined in a `.proto` file, when generating Python stubs with grpc_tools.protoc, or when starting a Python server with a `ThreadPoolExecutor` on a specific port.
---

# Build a Python gRPC service

## 1. Install the toolchain
Install the gRPC runtime and the code generator at pinned versions so regeneration is reproducible:
```
pip3 install grpcio==<VERSION> grpcio-tools==<VERSION>
```

## 2. Define the contract in a `.proto` file
Start the file with `syntax = "proto3";`, then define:
- a `service` block listing each `rpc` with its request and response message names
- one `message` per request/response, using `int32` for integer fields, `string` for text, `bool` for flags, etc.

## 3. Generate Python stubs
From the directory containing the `.proto` file, run:
```
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <protofile>
```
This produces two files: `<protofile>_pb2.py` (messages) and `<protofile>_pb2_grpc.py` (service stubs).
**Naming pitfall:** hyphens in the proto filename become underscores in the generated module names. Import the underscore form.

## 4. Implement the servicer
Create a class inheriting from `<ServiceName>Servicer` (auto-generated). For each declared RPC, define a method with the same name, taking the request as its single argument and returning the response. The class instance is what gets registered with the server.

## 5. Wire up and start the server
In `if __name__ == "__main__":`:
1. Build the server: `grpc.server(futures.ThreadPoolExecutor(max_workers=10))`
2. Register the servicer: `add_<ServiceName>Servicer_to_server(<ServicerImpl>(), server)`
3. Bind the port: `server.add_insecure_port('[::]:<PORT>')`
4. Call `server.start()` then `server.wait_for_termination()`.

## 6. Run in the background and verify
Launch the server detached so it survives the calling shell:
```
python3 <server>.py &
```
Confirm the process is actually listening — for an IPv6 wildcard bind, check `/proc/net/tcp6` for an entry whose local address (last hex quartet in little-endian) matches the chosen port, or use `ss -ltnp` / `lsof -iTCP -sTCP:LISTEN`.

## Common pitfalls
- **Forgetting to `wait_for_termination()`**: the server exits immediately after `start()` if no blocking call follows it.
- **Generating stubs from the wrong directory**: `-I.` is relative; `cd` into the directory that contains the `.proto` file before invoking `protoc`.
- **Importing `from <protofile> import ...`**: Python module names cannot contain hyphens. If the proto file is `my-svc.proto`, import it as `my_svc_pb2` / `my_svc_pb2_grpc`.
- **Port already in use**: pick a fresh port or stop the prior process before relaunching.