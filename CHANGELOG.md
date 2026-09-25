# Changelog

## [0.5.0](https://github.com/dcc-mcp/dcc-mcp-capcut/compare/v0.4.0...v0.5.0) (2026-09-25)


### Features

* **handoff:** add agent interface descriptors and the upstream handoff format ([#32](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/32)) ([d2ac9a8](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/d2ac9a8c5a6d667885cad8c26fa17c0339d7dfb5))


### Bug Fixes

* **batch:** keep what a resume learns before it refuses to continue ([58e1f52](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/58e1f52f7d00c9f451d7383614343b2055d112ed))
* **batch:** settle an orphan the host cannot describe as one item's failure ([a430eaa](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/a430eaad344024e6b03e75aee7394299200e1f53))
* **handoff:** close three P3 gaps in the descriptors, the index and dispatch ([398fe6b](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/398fe6b57fb10e82469be2084f960141f13a0905))
* **verify:** report duplicate archive members without hiding other problems ([0ecf9bb](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/0ecf9bbebcee1a0af45c5f583d359b9a46292df9))

## [0.4.0](https://github.com/dcc-mcp/dcc-mcp-capcut/compare/v0.3.0...v0.4.0) (2026-09-24)


### Features

* **export:** add an opt-in export receipt for size, duration and streams ([#26](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/26)) ([ccb75e5](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/ccb75e5eba5fbe1ac41c6781ded540676b144a21))
* **host:** read the Windows host version from the .exe version resource ([#29](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/29)) ([951427e](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/951427edb4681c0248141e7f1c8bd4b69f0e9162))

## [0.3.0](https://github.com/dcc-mcp/dcc-mcp-capcut/compare/v0.2.0...v0.3.0) (2026-09-24)


### Features

* **host:** add a machine-readable host version matrix and report the default bridge token ([#25](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/25)) ([9177a09](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/9177a09ddf70171f3cca1ae9b39dba52a4358fd8))


### Bug Fixes

* **tests:** read the skill version from the package instead of a literal ([#23](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/23)) ([5b18e24](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/5b18e247300d2fa501186b7cbe1812e9d42a6397))

## [0.2.0](https://github.com/dcc-mcp/dcc-mcp-capcut/compare/v0.1.0...v0.2.0) (2026-09-23)


### Features

* add optional native Qt metadata probe ([#5](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/5)) ([d0fd895](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/d0fd895e7b77a87b81bfdf12da2cd37b4f6bd729))
* add read-only doctor preflight CLI ([b918442](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/b918442b10892e4f09329bb7c24999bf4ef1db3d))
* **ci:** record panel artifact digests and prove the dcc-mcp-core floor ([#10](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/10)) ([134c6a5](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/134c6a5edb4855aa284e9234887eb5262e81c4f6))
* export portable frame-based OpenTimelineIO timelines ([5fec6b8](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/5fec6b8f4ca972dda69925b71c6260ab6f3af089))
* **host:** dispatch host binding through platform providers ([9e7951a](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/9e7951abc32fc7fa98b4526068abe1bb38fbd481))
* **installer:** discover both CapCut and JianyingPro editions ([#8](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/8)) ([97dea3a](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/97dea3a0e489485500dcce67b0a85f66e9bef716))
* **plan:** unify edit plans on one canonical contract and add the assembly direction ([#13](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/13)) ([aae3e09](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/aae3e09029c48898596284f7e76065c1b7336d2f))
* **subtitles:** add the external ASR executor seam and batch subtitles ([#14](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/14)) ([70c3b8f](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/70c3b8f7667778ba41be395ad7ab481b6ef3fb8a))


### Bug Fixes

* **ci:** run the doctor smoke step under bash ([9cc8a61](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/9cc8a61e7174363676f252c29aec54dee7a6652d))
* **host:** keep health-probe failures as evidence and align the bridge token ([#16](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/16)) ([73befb8](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/73befb825ca5f2bb74b934c95efbd468a7b539f8))
* **host:** surface bridge errors, probe health on the default token, gate configure_environment ([#15](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/15)) ([d82e802](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/d82e80220a5517715e1e425286f851c0a3ef779b))
* reject reserved characters in media path components ([8be76d0](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/8be76d00d9acca29381bb0b8d08f00299f56f490))
* **release:** let conventional commits drive the version instead of release-as ([#17](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/17)) ([4cd17e3](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/4cd17e3536f6081d174b32d04dbc5830972d6fef))
* **release:** make release-please actually bump the in-tree version ([#20](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/20)) ([7e87e00](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/7e87e00a428712e1f8dac5b4f7d36d776120cc41))
* resolve explicit window titles from native inventory ([#3](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/3)) ([5b10f74](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/5b10f74f9b9585622619711af5f22b4b40562652))
* **skills:** give the bundled skills a release-please version anchor ([#22](https://github.com/dcc-mcp/dcc-mcp-capcut/issues/22)) ([5404b6c](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/5404b6c62661db30376ae36a709022be045573bc))

## 0.1.0 (2026-09-12)


### Features

* introduce CapCut MCP adapter ([65f8651](https://github.com/dcc-mcp/dcc-mcp-capcut/commit/65f8651d0c9768bda052513d2a0a05c2bf7458bd))
