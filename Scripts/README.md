# VCORE launch scripts

Run these scripts from any working directory:

- `LaunchAll.bat` — llama backend, web services, Pixel Streaming, then packaged UE5.
- `LaunchUE5.bat [path-to-VCORE.exe]` — packaged UE5 only.
- `LaunchWeb.bat [--build]` — Docker web services only.
- `LaunchPixelStreaming.bat` — local signalling server and player only.
- `LaunchLlamaBackend.bat [--force]` — llama backend only.

Runtime URLs:

- Web: <http://localhost:5199>
- Backend API: <http://localhost:8000>
- Llama backend: <http://localhost:8080>
- Pixel Streaming player: <http://localhost:8880>

Environment overrides:

- `VCORE_PACKAGED_EXE`
- `VCORE_PIXEL_STREAMING_URL`
- `VCORE_LLAMA_SERVER`
- `VCORE_LLM_BASE_MODEL`
- `VCORE_LLM_ADAPTER`
