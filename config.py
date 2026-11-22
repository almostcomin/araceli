# Araceli configuration

BASE_URL = "http://127.0.0.1:1234/v1"
API_KEY = "lm-studio"

MODEL = "qwen/qwen3.5-9b"

CONTEXT_LENGTH = 24576

# Maximum tool-call rounds per user turn. Batch document work (read +
# write per document) needs more rounds than short conversations.
MAX_TOOL_ROUNDS = 16

TEMPERATURE = 0.7
MAX_TOKENS = 4096

SYSTEM_PROMPT_FILE = "system_prompt.md"
