"""改完 config 后跑这一句，立刻知道当前 provider / key / model 通不通：
    cd backend && python ping_llm.py
测的就是应用核心分析实际用的那套（同一份 config、同一个 key、同一个模型）。"""
import asyncio

from app.harness.model_router import model_router
from app.harness.orchestrator import get_openai_client


def main():
    cfg = model_router.route("multi_perspective_analysis", 100)   # 核心读用的档
    cli = get_openai_client(cfg.provider)
    k = str(getattr(cli, "api_key", "") or "")
    print(f"provider={cfg.provider}  base_url={cli.base_url}  model={cfg.model}")
    print(f"key={(k[:6] + '...' + k[-4:]) if k else '(空)'}")
    try:
        r = asyncio.run(cli.chat.completions.create(
            model=cfg.model, max_tokens=5,
            messages=[{"role": "user", "content": "回一个字：好"}]))
        print("✅ 正常 →", (r.choices[0].message.content or "").strip())
    except Exception as e:
        print("✗ 不通 →", str(e)[:220])


if __name__ == "__main__":
    main()
