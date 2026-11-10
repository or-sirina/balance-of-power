"""Editable provider presets. Models are examples, not availability guarantees.

Wire formats verified against official documentation (2026-11-10):
https://openrouter.ai/docs/api_reference/overview
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
https://api-docs.deepseek.com/api/create-chat-completion/
https://platform.claude.com/docs/en/api/messages/create
https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope
https://www.alibabacloud.com/help/en/model-studio/deep-thinking
https://ai.google.dev/gemini-api/docs/openai

Qwen's regional legacy URLs remain documented; users may replace them with
workspace-specific HTTPS endpoints from their Model Studio console. Keys are
regional. Local endpoints must implement OpenAI chat completions.
"""
from urllib.parse import urlsplit

PROVIDERS = {}
for _id, _name, _url, _model, _env in (
 ('openrouter','OpenRouter','https://openrouter.ai/api/v1','qwen/qwen3.8-27b','OPENROUTER_API_KEY'),
 ('openai','OpenAI','https://api.openai.com/v1','gpt-5-mini','OPENAI_API_KEY'),
 ('deepseek','DeepSeek','https://api.deepseek.com','deepseek-flash','DEEPSEEK_API_KEY'),
 ('anthropic','Anthropic','https://api.anthropic.com/v1','claude-sonnet-4-6','ANTHROPIC_API_KEY'),
 ('qwen','Qwen (Singapore)','https://dashscope-intl.aliyuncs.com/compatible-mode/v1','qwen-plus','DASHSCOPE_API_KEY'),
 ('qwen_china','Qwen (China)','https://dashscope.aliyuncs.com/compatible-mode/v1','qwen-plus','DASHSCOPE_API_KEY'),
 ('gemini','Gemini','https://generativelanguage.googleapis.com/v1beta/openai','gemini-2.5-flash','GEMINI_API_KEY'),
 ('custom','Custom OpenAI compatible','','',''),
 ('local','Local OpenAI compatible','http://localhost:11434/v1','','')):
    PROVIDERS[_id] = dict(id=_id,name=_name,base_url=_url,default_model=_model,api_key_env=_env,
                         protocol='anthropic' if _id == 'anthropic' else 'openai')


def provider_preset(provider):
    return dict(PROVIDERS.get(provider, PROVIDERS['custom']))


def provider_catalog():
    return [dict(preset) for preset in PROVIDERS.values()]


def infer_provider(base_url):
    host = (urlsplit(base_url or '').hostname or '').lower()
    if host in ('localhost', '127.0.0.1', '::1'):
        return 'local'
    for provider, preset in PROVIDERS.items():
        if host and host == urlsplit(preset['base_url']).hostname:
            return provider
    if host.endswith('.maas.aliyuncs.com'):
        return 'qwen_china' if '.cn-beijing.' in host else 'qwen'
    return 'custom'
