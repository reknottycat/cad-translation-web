# Backend Modern Guide

## Quick Start

1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

2. Prepare config

```bash
copy .env.example .env
```

3. Set provider and key in `.env`

```env
TRANSLATION_PROVIDER=openai_compatible
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=your_key
LLM_MODEL=qwen-max
```

4. Start API

```bash
python run_server.py
```

## New APIs

- `GET /api/translation/config`: runtime config + provider presets
- `GET /api/translation/providers`: active provider + all presets
- `POST /api/translation/text`: single text translation
- `POST /api/translation/batch`: batch translation
- `POST /api/translation/excel`: excel translation

## Notes

- Legacy imports are preserved (`alibaba_ai_translation_service`) but internally routed to the new unified service.
- Provider preset list includes OpenAI/OpenRouter/DashScope/DeepSeek/Groq/MiniMax/Zhipu/Moonshot/SiliconFlow/Together/Custom.
