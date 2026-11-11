# LLM backends

Every LLM call in Annalist goes through one backend. The default is `claude-cli`, which runs `claude -p` on your Claude subscription, exactly as before. Pick another backend in the run's `book.json`, or for one command with the `ANNALIST_BACKEND` environment variable.

| Backend | What it calls | Credentials |
| --- | --- | --- |
| `claude-cli` | `claude -p` (Claude Code) | your Claude login |
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY`, or the variable named in `api_key_env` |
| `openai` | any OpenAI-compatible Chat Completions server: OpenAI, OpenRouter, LM Studio, Ollama | `OPENAI_API_KEY` or `api_key_env`; none needed for a local server |
| `fake` | scripted replies from a JSON file, for tests | none |

## Config

A `backend` block in `book.json` picks the backend and its options. `model` is the default model for every step. The existing `models` map still sets the model per step and wins over `model`.

```json
{
  "backend": {
    "name": "openai",
    "base_url": "http://localhost:1234/v1",
    "model": "qwen3-8b",
    "max_tokens": 16000,
    "prices": {"qwen3-8b": {"input": 0, "output": 0}}
  },
  "models": {"extract": "qwen3-32b"}
}
```

OpenRouter: `"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY", "model"` set to an OpenRouter model id. Ollama: `"base_url": "http://localhost:11434/v1"`. Local models are experimental. Load them with a context of 32k tokens or more, because LM Studio's default 8k cuts prompts short. In a test with a 12B model, reasoning took over three minutes per chapter and ran away on one call, and with reasoning off, 2 of 5 chapter reads came back as broken JSON on the first try. The Anthropic backend accepts the aliases `opus`, `sonnet` and `haiku`, so a book written for `claude-cli` runs on it unchanged.

Options per backend:

- `anthropic`: `base_url`, `api_key_env`, `max_tokens` (default 32000), `timeout_s` (default 900), `prices`.
- `openai`: `base_url` (default `$OPENAI_BASE_URL`, then `https://api.openai.com/v1`), `api_key_env`, `max_tokens` (sent only when set), `timeout_s`, `prices`.
- `fake`: `script`, a path relative to the run directory.

`prices` maps a model id to dollars per million input and output tokens. Anthropic models have built-in prices. A model with no price logs a null cost.

`ANNALIST_BACKEND=claude-cli annalist read run --to 5` overrides the block's `name`. When it names a different backend than the block, the block's options and `model` are ignored.

A bad config stops the command with a one-line reason, such as `annalist: backend.max_tokens must be a whole number`.

## Effort

With the `claude-cli` backend, an `efforts` map in `book.json` sets the reasoning effort per step, passed to `claude -p --effort`. Values are `low`, `medium`, `high`, `xhigh` and `max`, and a `default` key covers every step not named. Without the map, `claude -p` uses its own default.

```json
{"efforts": {"default": "high", "extract": "medium"}}
```

The `proofread` step runs at `high` unless the map names `proofread` itself, because its prompts hold a whole volume, and at the default effort such a prompt got no reasoning and empty replies. A `default` key does not lower it.

Replies saved at one effort are never reused at another.

## Retries

Rate limits, overloads, server errors and timeouts (HTTP 408, 409, 429, 5xx and 529) back off 60, 120, 300, 600 and 720 seconds, longer if the server sends `retry-after`, then stop the command so you can rerun it. Errors that a retry will not fix stop at once: a rejected key, a bad request, or a refused connection to a local server that is not running.

## Cache

Cached replies are keyed by backend, model and prompt, so switching models never reuses another model's answer. Caches written before backends existed are keyed by prompt alone. `claude-cli` still reads them, so existing runs replay without new calls. Other backends ignore them.

## Fake script

```json
{"replies": [
  {"purpose": "extract", "chapter": 1, "reply": {"synopsis": "...", "entities": []}},
  {"prompt_sha1": "3f2a...", "reply": "raw text"}
]}
```

A reply matches on the SHA-1 of the exact prompt first, then on purpose and chapter. Steps without a chapter, such as `summary`, match `"chapter": null` or an omitted chapter. A call with no scripted reply stops the command and names the purpose, chapter and prompt hash.
