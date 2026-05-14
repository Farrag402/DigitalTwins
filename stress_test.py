import asyncio
import websockets
import json
import base64
import time
import argparse
import os

async def run_client(client_id: int, ws_url: str, wav_path: str, speaker: str):
    print(f"[Client {client_id}] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            # 1. Send InitMessage
            init_msg = {"type": "init", "speaker": speaker}
            await ws.send(json.dumps(init_msg))
            print(f"[Client {client_id}] Sent init message.")
            
            # 2. Read wav file and send as audio_chunk
            with open(wav_path, "rb") as f:
                wav_bytes = f.read()
                
            b64_data = base64.b64encode(wav_bytes).decode('utf-8')
            chunk_msg = {"type": "audio_chunk", "data": b64_data, "format": "wav"}
            
            # Start timer before sending the first chunk
            send_time = time.perf_counter()
            await ws.send(json.dumps(chunk_msg))
            print(f"[Client {client_id}] Sent audio chunk ({len(wav_bytes)} bytes).")
            
            # 3. Send audio_end to trigger pipeline
            end_msg = {"type": "audio_end"}
            await ws.send(json.dumps(end_msg))
            print(f"[Client {client_id}] Sent audio_end. Waiting for response...")
            
            # 4. Wait for the first response and track latency
            first_chunk_latency = None
            while True:
                response = await ws.recv()
                
                # Record latency on the very first message received (usually the first Opus frame payload or error)
                if first_chunk_latency is None:
                    recv_time = time.perf_counter()
                    first_chunk_latency = recv_time - send_time
                    print(f"[Client {client_id}] First response latency: {first_chunk_latency:.4f} seconds")
                    
                if isinstance(response, bytes):
                    # Incoming raw Opus frame
                    pass
                else:
                    # Incoming JSON payload
                    try:
                        data = json.loads(response)
                        if data.get("type") == "complete":
                            print(f"[Client {client_id}] Pipeline complete.")
                            break
                        elif data.get("type") == "error":
                            print(f"[Client {client_id}] Received error: {data.get('error')}")
                            break
                    except json.JSONDecodeError:
                        pass
                        
            return first_chunk_latency
            
    except Exception as e:
        print(f"[Client {client_id}] Error: {e}")
        return None

async def main():
    parser = argparse.ArgumentParser(description="WebSocket Concurrency Latency Test")
    parser.add_argument("--url", type=str, default="wss://p7lh5vjm-8001.thundercompute.net/ws", help="Server WebSocket URL")
    parser.add_argument("--wav", type=str, required=True, help="Path to the WAV file to send")
    parser.add_argument("--speaker", type=str, default="alaa", help="Speaker name for init message")
    parser.add_argument("--clients", type=int, default=20, help="Number of concurrent connections to spawn")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.wav):
        print(f"Error: could not find audio file at {args.wav}")
        return
        
    print(f"Starting {args.clients} concurrent clients, targeting {args.url}")
    
    # Fire off all WebSocket clients concurrently
    tasks = [run_client(i, args.url, args.wav, args.speaker) for i in range(args.clients)]
    results = await asyncio.gather(*tasks)
    
    # Process results
    valid_results = [r for r in results if r is not None]
    if valid_results:
        avg_latency = sum(valid_results) / len(valid_results)
        print("\n=== Concurrency Results ===")
        print(f"Successful clients : {len(valid_results)}/{args.clients}")
        print(f"Min Latency        : {min(valid_results):.4f} seconds")
        print(f"Max Latency        : {max(valid_results):.4f} seconds")
        print(f"Average Latency    : {avg_latency:.4f} seconds")
    else:
        print("\nAll clients failed to complete the pipeline.")

if __name__ == "__main__":
    asyncio.run(main())
