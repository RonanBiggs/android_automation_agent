run the ollama server:

1. ollama serve
old
2. ollama run hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q5_K_M
3. ollama run qwen2.5vl:7b
old visual model llava:7b 

new
ollama run qwen3-coder:30b
ollama run llama3.2-vision:11b

NOTE: rn we use the old llm and new vision model

------- EMULATOR -----
emulator -avd agent_phone_1 -gpu host -no-metrics -no-boot-anim -no-snapshot

for production use remove -no-snapshot its js for debugging


