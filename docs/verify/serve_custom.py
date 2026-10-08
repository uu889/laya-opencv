"""Step 3: serve a custom local checkpoint through Laya's own /v1/systemone server.

`laya-serve` (the CLI) only knows the built-in checkpoints; a custom one is served
by building the Router ourselves, registering the local directory, and handing the
Router to `create_app`. An `on_route` hook pins every request to our checkpoint, so
the language router never reaches for a built-in checkpoint that is not installed,
and the same files are never loaded twice under two names.
"""
import os
import sys

import uvicorn
from laya.hooks import BaseHook
from laya.router import RouteDecision, Router
from laya.serve import create_app

ckpt, name, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
path = os.path.abspath(ckpt)


class PinTo(BaseHook):
    def __init__(self, model: str, repo: str):
        self.model, self.repo = model, repo

    def on_route(self, ctx):
        if ctx.decision["model"] != self.model:
            ctx.decision = RouteDecision(model=self.model, repo=self.repo,
                                         reason="pinned to %r (was %s: %s)" % (self.model, ctx.decision["model"],
                                                                                 ctx.decision["reason"]))


router = Router(models={name: path}, default=name, device="cpu", max_loaded=1, hooks=[PinTo(name, path)])
router.preload([name])                       # only our model: never touches the Hub
print("registered:", router.registered, flush=True)
uvicorn.run(create_app(router), host="127.0.0.1", port=port, log_level="warning")
