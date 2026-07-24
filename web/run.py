import os
import argparse
import uvicorn


def main():
    p = argparse.ArgumentParser(description="JustAsk Web UI")
    p.add_argument("--host", default=os.environ.get("JUSTASK_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("JUSTASK_PORT", "8000")))
    p.add_argument("--reload", action="store_true")
    args = p.parse_args()
    uvicorn.run(
        "web.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
