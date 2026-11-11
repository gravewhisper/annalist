import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path

from .book import load_book


@dataclass(frozen=True)
class Request:
    system: str
    prompt: str
    model: str
    purpose: str
    chapter: int | None = None
    effort: str | None = None


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None
    duration_s: float | None = None
    meta: dict = field(default_factory=dict)


class ConfigError(Exception):
    pass


class Transient(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class Fatal(Exception):
    pass


def prompt_sha1(prompt):
    return hashlib.sha1(prompt.encode()).hexdigest()


def cost(prices, model, usage):
    price = prices.get(model)
    if price is None:
        return None
    return round((usage.get("input_tokens", 0) * price["input"] + usage.get("output_tokens", 0) * price["output"]) / 1e6, 6)


class ClaudeCLI:
    name = "claude-cli"
    default_model = "sonnet"

    def __init__(self, workdir, options):
        self.workdir = workdir

    def complete(self, request):
        try:
            proc = subprocess.run(
                ["claude", "-p", "--output-format", "json", "--model", request.model,
                 *(["--effort", request.effort] if request.effort else []),
                 "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                 "--no-session-persistence", "--system-prompt", request.system],
                input=request.prompt, capture_output=True, text=True, timeout=900, cwd=self.workdir,
                env={**os.environ, "DISABLE_PROMPT_CACHING": "1"},
            )
        except subprocess.TimeoutExpired:
            raise Transient("timeout after 900s")
        except FileNotFoundError:
            raise Fatal("the claude command is not on PATH; install Claude Code or choose another backend")
        try:
            envelope = json.loads(proc.stdout)
        except ValueError:
            raise Transient(f"CLI exit {proc.returncode}: {(proc.stderr or proc.stdout)[-500:].strip()}")
        if envelope.get("is_error") or envelope.get("subtype") != "success" or proc.returncode:
            raise Transient(f"CLI error {envelope.get('subtype')}: {str(envelope.get('result'))[:300]}")
        meta = {k: envelope.get(k) for k in ("duration_api_ms", "modelUsage", "num_turns")}
        return Reply(text=str(envelope.get("result") or ""), model=request.model, usage=envelope.get("usage") or {},
                     cost_usd=envelope.get("total_cost_usd"), duration_s=(envelope.get("duration_ms") or 0) / 1000,
                     meta={"returncode": proc.returncode, **meta})


def lower_keys(headers):
    return {k.lower(): v for k, v in headers.items()}


def post_json(url, headers, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, lower_keys(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, lower_keys(exc.headers or {}), exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            raise Fatal(f"cannot reach {url}: connection refused; is the server running?")
        raise Transient(f"cannot reach {url}: {exc.reason}")
    except TimeoutError:
        raise Transient(f"no reply from {url} within {timeout}s")


RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


def http_body(url, status, headers, body):
    if status in RETRYABLE or status >= 500:
        retry = headers.get("retry-after")
        raise Transient(f"HTTP {status} from {url}: {body[:300]}", float(retry) if retry and retry.isdigit() else None)
    if status != 200:
        raise Fatal(f"HTTP {status} from {url}: {body[:500]}")
    try:
        return json.loads(body)
    except ValueError:
        raise Transient(f"non-JSON body from {url}: {body[:300]}")


ANTHROPIC_ALIASES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


ANTHROPIC_PRICES = {
    "claude-fable-5-1": {"input": 10.0, "output": 50.0},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-5-5": {"input": 0.1, "output": 0.5},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}


class Anthropic:
    name = "anthropic"
    default_model = "sonnet"

    def __init__(self, workdir, options, post=post_json):
        self.base_url = options.get("base_url", "https://api.anthropic.com").rstrip("/")
        key_env = options.get("api_key_env", "ANTHROPIC_API_KEY")
        self.api_key = os.environ.get(key_env)
        if not self.api_key:
            raise ConfigError(f"the anthropic backend needs an API key in ${key_env}")
        self.max_tokens = options.get("max_tokens", 32000)
        self.timeout = options.get("timeout_s", 900)
        self.prices = {**ANTHROPIC_PRICES, **options.get("prices", {})}
        self.post = post

    def payload(self, request):
        return {"model": ANTHROPIC_ALIASES.get(request.model, request.model),
                "max_tokens": self.max_tokens, "system": request.system,
                "messages": [{"role": "user", "content": request.prompt}]}

    def complete(self, request):
        url = f"{self.base_url}/v1/messages"
        started = time.time()
        payload = self.payload(request)
        data = http_body(url, *self.post(url, {"x-api-key": self.api_key, "anthropic-version": "2026-10-21"}, payload, self.timeout))
        usage = data.get("usage") or {}
        model = data.get("model") or payload["model"]
        return Reply(text="".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text"),
                     model=model, usage=usage, cost_usd=cost(self.prices, model, usage),
                     duration_s=round(time.time() - started, 2), meta={"stop_reason": data.get("stop_reason")})


class OpenAI:
    name = "openai"
    default_model = None

    def __init__(self, workdir, options, post=post_json):
        self.base_url = options.get("base_url") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self.base_url = self.base_url.rstrip("/")
        key_env = options.get("api_key_env", "OPENAI_API_KEY")
        self.api_key = os.environ.get(key_env)
        if not self.api_key and "api.openai.com" in self.base_url:
            raise ConfigError(f"the openai backend needs an API key in ${key_env} for {self.base_url}")
        self.max_tokens = options.get("max_tokens")
        self.timeout = options.get("timeout_s", 900)
        self.prices = options.get("prices", {})
        self.post = post

    def payload(self, request):
        payload = {"model": request.model, "messages": [{"role": "system", "content": request.system},
                                                        {"role": "user", "content": request.prompt}]}
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        return payload

    def complete(self, request):
        url = f"{self.base_url}/chat/completions"
        started = time.time()
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = http_body(url, *self.post(url, headers, self.payload(request), self.timeout))
        choice = (data.get("choices") or [{}])[0]
        raw = data.get("usage") or {}
        usage = {"input_tokens": raw.get("prompt_tokens", 0), "output_tokens": raw.get("completion_tokens", 0)}
        model = data.get("model") or request.model
        return Reply(text=(choice.get("message") or {}).get("content") or "", model=model, usage=usage,
                     cost_usd=cost(self.prices, request.model, usage), duration_s=round(time.time() - started, 2),
                     meta={"finish_reason": choice.get("finish_reason")})


class Fake:
    name = "fake"
    default_model = "fake"

    def __init__(self, workdir, options):
        path = Path(workdir) / options["script"]
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))["replies"]
        except (OSError, ValueError, KeyError) as exc:
            raise ConfigError(f"fake backend script {path}: {exc}")
        self.by_hash = {e["prompt_sha1"]: e["reply"] for e in entries if "prompt_sha1" in e}
        self.by_text = [(e["purpose"], e["contains"], e.get("model"), e["reply"]) for e in entries if "contains" in e]
        self.by_step = {}
        for e in entries:
            if "purpose" in e and "contains" not in e:
                self.by_step.setdefault((e["purpose"], e.get("chapter")), []).append(e["reply"])

    def complete(self, request):
        digest = prompt_sha1(request.prompt)
        matched = [r for purpose, text, model, r in self.by_text
                   if purpose == request.purpose and text in request.prompt and model in (None, request.model)]
        if digest in self.by_hash:
            reply = self.by_hash[digest]
        elif matched:
            reply = matched[0]
        elif (request.purpose, request.chapter) in self.by_step or (request.purpose, None) in self.by_step:
            queue = self.by_step.get((request.purpose, request.chapter)) or self.by_step[(request.purpose, None)]
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            raise Fatal(f"fake backend has no scripted reply for purpose {request.purpose!r} chapter {request.chapter} "
                        f"prompt_sha1 {digest}")
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return Reply(text=text, model=request.model, usage={"input_tokens": 0, "output_tokens": 0}, cost_usd=0.0, duration_s=0.0)


BACKENDS = {b.name: b for b in (ClaudeCLI, Anthropic, OpenAI, Fake)}


OPTIONS = {
    "claude-cli": {},
    "anthropic": {"base_url": str, "api_key_env": str, "max_tokens": int, "timeout_s": int, "prices": dict},
    "openai": {"base_url": str, "api_key_env": str, "max_tokens": int, "timeout_s": int, "prices": dict},
    "fake": {"script": str},
}


EFFORTS = ("low", "medium", "high", "xhigh", "max")


EFFORT_BACKENDS = ("claude-cli", "fake")


DEFAULT_EFFORTS = {"proofread": "high"}


SEVERAL_MODELS = ("proofread",)


TYPE_NAMES = {str: "a string", int: "a whole number", dict: "an object"}


@dataclass(frozen=True)
class Settings:
    backend: str
    default_model: str | None
    models: dict
    options: dict
    efforts: dict = field(default_factory=dict)

    def effort_for(self, purpose):
        built_in = DEFAULT_EFFORTS.get(purpose) if self.backend in EFFORT_BACKENDS else None
        return self.efforts.get(purpose) or built_in or self.efforts.get("default")

    def models_for(self, purpose):
        model = self.models.get(purpose) or self.default_model
        if not model:
            raise ConfigError(f"the {self.backend} backend has no model for {purpose!r}; set backend.model in book.json")
        return tuple(model) if isinstance(model, list) else (model,)

    def model_for(self, purpose):
        model, *more = self.models_for(purpose)
        if more:
            raise ConfigError(f"book.json models.{purpose} names several models, but this step runs one")
        return model

    def with_model(self, purpose, model):
        return replace(self, models={**self.models, purpose: model})


def check_prices(prices):
    for model, price in prices.items():
        if not (isinstance(price, dict) and set(price) == {"input", "output"}
                and all(isinstance(v, (int, float)) for v in price.values())):
            raise ConfigError(f"backend.prices[{model!r}] must be {{\"input\": dollars per million tokens, \"output\": ...}}")


def parse_settings(book, env):
    block = book.get("backend") or {}
    if not isinstance(block, dict):
        raise ConfigError("book.json backend must be an object")
    name = env.get("ANNALIST_BACKEND") or block.get("name") or "claude-cli"
    if name not in BACKENDS:
        raise ConfigError(f"unknown backend {name!r}; choose one of {', '.join(BACKENDS)}")
    if block.get("name", name) != name:
        block = {}
    allowed = OPTIONS[name]
    options = {k: v for k, v in block.items() if k not in ("name", "model")}
    for key, value in options.items():
        if key not in allowed:
            raise ConfigError(f"backend.{key} is not an option of the {name} backend"
                              + (f"; it takes {', '.join(sorted(allowed))}" if allowed else ""))
        if not isinstance(value, allowed[key]) or isinstance(value, bool):
            raise ConfigError(f"backend.{key} must be {TYPE_NAMES[allowed[key]]}")
    if name == "fake" and "script" not in options:
        raise ConfigError("the fake backend needs backend.script, a JSON file of scripted replies")
    check_prices(options.get("prices", {}))
    models = book.get("models") or {}
    for purpose, named in models.items():
        if isinstance(named, list) and purpose not in SEVERAL_MODELS:
            raise ConfigError(f"book.json models.{purpose} must be one model name; only {', '.join(SEVERAL_MODELS)} takes a list")
        if isinstance(named, list) and not (named and all(isinstance(m, str) and m for m in named) and len(set(named)) == len(named)):
            raise ConfigError(f"book.json models.{purpose} must list different model names")
    model = block.get("model")
    if model is not None and not (isinstance(model, str) and model):
        raise ConfigError("backend.model must be a model name")
    if name == "openai":
        aliased = {p: m for p, m in models.items() if set(m if isinstance(m, list) else [m]) & set(ANTHROPIC_ALIASES)}
        if aliased:
            raise ConfigError(f"book.json models {aliased} name Claude CLI aliases, which an OpenAI-compatible server "
                              "does not know; give model ids the server serves")
    efforts = book.get("efforts") or {}
    if not isinstance(efforts, dict) or any(v not in EFFORTS for v in efforts.values()):
        raise ConfigError(f"book.json efforts must map steps to one of {', '.join(EFFORTS)}")
    if efforts and name not in EFFORT_BACKENDS:
        raise ConfigError(f"book.json efforts work only with the claude-cli backend, not {name}")
    return Settings(backend=name, default_model=model or BACKENDS[name].default_model, models=models, options=options,
                    efforts=efforts)


def load_settings(workdir):
    return parse_settings(load_book(workdir), os.environ)


def open_backend(workdir, settings):
    return BACKENDS[settings.backend](str(workdir), settings.options)
