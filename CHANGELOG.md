# Changelog

All notable changes to memwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until v1.0, breaking
changes may land between minor versions per the spec evolution policy in
[`docs/spec/v0.md`](docs/spec/v0.md).

## 0.1.0 (2026-05-31)


### Added

* 2 more adapters (Cognee + pgvector), threat model, MCP positioning, citation + arch diagram ([bc4533f](https://github.com/mthamil107/agent-memory-protocol/commit/bc4533f4075cc25017415938116e8000032e72e0))
* 3rd backend (Letta), recall microbenchmark, pinned UI CSRF secret ([267a969](https://github.com/mthamil107/agent-memory-protocol/commit/267a969bcadb1cceadd1673f284ce1dbd1ed6a73))
* conformance suite + adversarial experiment + blog draft + Fly.io scaffold ([e9102e9](https://github.com/mthamil107/agent-memory-protocol/commit/e9102e9faab610e4dfcf5968609ac3c588f0c8e8))
* **core:** Memory facade, full CLI, FSM procedural backend, STM-LTM transformer, quickstart ([2819f44](https://github.com/mthamil107/agent-memory-protocol/commit/2819f44593fa47b79cd9c20b94b13d5187011489))
* **core:** pydantic v2 models and MemoryStore Protocol ([f9ecb9f](https://github.com/mthamil107/agent-memory-protocol/commit/f9ecb9f71b1edcc6edee3c65cf91f0e11caf6940))
* **launch:** LinkedIn explainer GIF + corrected-framing post body ([34c1abc](https://github.com/mthamil107/agent-memory-protocol/commit/34c1abce55eb11eb87074ca0e2d88eea044fecdd))
* **router:** memory router with RRF fusion + 1-hop graph boost ([c5a7f7d](https://github.com/mthamil107/agent-memory-protocol/commit/c5a7f7dec28d8946a3c9275a371c9f5a303232ce))
* **spec:** publish AMP spec v0 with 12 JSON Schemas and 15 worked examples ([24997a6](https://github.com/mthamil107/agent-memory-protocol/commit/24997a691477936e1496dcb1dcaae8e3152a7dca))
* **store:** sqlite-vec and mem0 MemoryStore adapters ([d67f616](https://github.com/mthamil107/agent-memory-protocol/commit/d67f616e2d3ec302702d60ddd5c32a5218f884db))
* **ui:** governance UI with 5 screens (Starlette + HTMX + Tailwind, FSL-licensed) ([cd68185](https://github.com/mthamil107/agent-memory-protocol/commit/cd6818515744b60447f8f57288508aa0924f22ab))
* Wave D — paper draft, eval harnesses, user study, PyPI release wiring ([b9080e2](https://github.com/mthamil107/agent-memory-protocol/commit/b9080e2be72fa7a3862f0acb660f54b02ae43b6e))


### Fixed

* 4 critical findings from independent code+security review ([2ebab61](https://github.com/mthamil107/agent-memory-protocol/commit/2ebab61b6186afa1c46aa37d9f67d4f764913405))
* 5 critical findings from code-review + security-review ([c828d76](https://github.com/mthamil107/agent-memory-protocol/commit/c828d76c6baaee924750bd4151628b063015c66c))
* **author:** correct author name everywhere — Thamilvendhan Munirathinam ([406dd18](https://github.com/mthamil107/agent-memory-protocol/commit/406dd18ef7f761388d8af0de0df30d2076f21e02))
* **ci:** exclude benchmark marker from default test run ([1fa19cf](https://github.com/mthamil107/agent-memory-protocol/commit/1fa19cfbdf11c5c1532c105d0a7bad9bd16a04f0))
* **ci:** unblock scripts.lib import — gitignore was hiding the package ([7825611](https://github.com/mthamil107/agent-memory-protocol/commit/7825611cde449b4be8f518ac1b585f4506de6363))
* **ci:** unblock Wave E — pytest pythonpath + release-please continue-on-error ([ee83119](https://github.com/mthamil107/agent-memory-protocol/commit/ee8311922b91b001eabdb89ed6ad06235c060092))
* **eval:** accept extension-less LongMemEval filenames from HF Hub ([bf2ee1f](https://github.com/mthamil107/agent-memory-protocol/commit/bf2ee1ff22887907cb50212c66e3e9531e90d27f))
* **eval:** per-question SQLite isolation for LME + LoCoMo harnesses ([b9b1537](https://github.com/mthamil107/agent-memory-protocol/commit/b9b153722b1ea8e42e34c4362d99b85ca43cd6a7))
* **ui:** out-of-band count swap and non-wrapping audit headers ([bf72267](https://github.com/mthamil107/agent-memory-protocol/commit/bf72267f95e148b100e2e0ff8b29c2f4fc503150))


### Documentation

* add governance UI + CLI demo GIFs to README ([514410c](https://github.com/mthamil107/agent-memory-protocol/commit/514410c299b332033ba450631de10f6fdcb979d5))
* **bench:** first real LongMemEval + LoCoMo numbers ([ad3b4cf](https://github.com/mthamil107/agent-memory-protocol/commit/ad3b4cfe9b482ba2ecfd8a2c321f265f9128fb7b))
* **launch:** post-arXiv-announce playbook (5 files in docs/launch/) ([3aa5278](https://github.com/mthamil107/agent-memory-protocol/commit/3aa5278bc6998b67ed20f9afc6af24e86d9d5f85))
* **paper:** arXiv bundle README — primary category cs.CR (auto-endorsed via 2604.18248) ([bdecc9e](https://github.com/mthamil107/agent-memory-protocol/commit/bdecc9e5778fd3e6997b63088dd0937c9ec92940))
* **paper:** arXiv preflight check + DRAFT-comment cleanup ([8b5a312](https://github.com/mthamil107/agent-memory-protocol/commit/8b5a312be33852959b2e810ddd1b6d566ddbb605))
* **paper:** arXiv submission bundle ready ([44f6547](https://github.com/mthamil107/agent-memory-protocol/commit/44f6547666866376f13e2a629237c4c65487259b))
* **paper:** canonical .md frontmatter now matches arXiv bundle author + venue ([434fb89](https://github.com/mthamil107/agent-memory-protocol/commit/434fb8975363e861a1df67e1af2e91ea1bec9b24))
* **paper:** finalize, polish, factcheck, LaTeX + BibTeX ([53c3fe5](https://github.com/mthamil107/agent-memory-protocol/commit/53c3fe5ab8e90db58d5f9c2a7a7c690a86110172))
* **paper:** fold preliminary LME + LoCoMo numbers into §5 + abstract context ([a262b56](https://github.com/mthamil107/agent-memory-protocol/commit/a262b564701163f012f613758cf9953d94b6d009))
* **paper:** pre-flight arXiv bundle validator ([e93c8f3](https://github.com/mthamil107/agent-memory-protocol/commit/e93c8f3542ae09be2fe3b268193b0a0ead5b4989))
* **paper:** tiny helper to extract abstract as paste-ready plain text for arXiv ([8ceacd6](https://github.com/mthamil107/agent-memory-protocol/commit/8ceacd65fffc352ca4602e649a0ff40b5567075e))
* polish README to launch-grade ([3262bd6](https://github.com/mthamil107/agent-memory-protocol/commit/3262bd6999642efa233595ef4e133f3e231a9902))
* **readme:** embed the amp-explainer.gif at the top of the hero ([0c6ffcb](https://github.com/mthamil107/agent-memory-protocol/commit/0c6ffcbab3561f0e588db36a379b258779779148))

## [Unreleased]

## [0.1.0] - 2026-06-10

### Added
- Initial public release of the memwire.
- JSON Schema 2020-12 specification covering 5 operations
  (`remember`, `recall`, `forget`, `merge`, `expire`) over 4 memory types
  (semantic, episodic, procedural, emotional).
- Five backend adapters implementing the `MemoryStore` protocol:
  `sqlite-vec`, `mem0`, `Letta`, `Cognee`, and `pgvector`.
- Memory router with Reciprocal Rank Fusion (RRF, k=60) and an optional
  1-hop graph boost for cross-store recall fusion.
- FSM-based procedural-memory backend powered by `pytransitions`.
- Asynchronous STM &harr; LTM transformer for short-term to long-term
  memory consolidation.
- `amp` CLI exposing `remember`, `recall`, and `forget` subcommands.
- Apache-2.0 licensed protocol and reference implementation.
- Microbenchmark harness, adversarial-fusion sub-experiment, and a
  16-scenario cross-adapter conformance suite.
- 290+ tests passing by default; `ruff` and `mypy --strict` clean.

[Unreleased]: https://github.com/mthamil107/memwire/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mthamil107/memwire/releases/tag/v0.1.0
