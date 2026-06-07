# Changelog

## [0.3.0](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.2.1...v0.3.0) (2026-06-07)


### Features

* **sandbox/collectors:** bind.bt bpftrace tracer for bind() syscalls ([#51](https://github.com/SupremeCommanderHedgehog/containerizer/issues/51)) ([2eb5234](https://github.com/SupremeCommanderHedgehog/containerizer/commit/2eb5234a2a0b00f630bbfef16d24cc9808afc8ea))
* **sandbox/collectors:** capable bcc-tools wrapper to JSONL ([#56](https://github.com/SupremeCommanderHedgehog/containerizer/issues/56)) ([d0ca290](https://github.com/SupremeCommanderHedgehog/containerizer/commit/d0ca2900f5b1ed3ae6a0eaaba3840a86ff5e843c))
* **sandbox/collectors:** open.bt bpftrace tracer for file accesses ([#50](https://github.com/SupremeCommanderHedgehog/containerizer/issues/50)) ([e6cde13](https://github.com/SupremeCommanderHedgehog/containerizer/commit/e6cde1344f7dcd8020caa6c3375e66d49109b1ce))
* **sandbox/collectors:** syscalls.bt bpftrace tracer for syscall rollup ([#53](https://github.com/SupremeCommanderHedgehog/containerizer/issues/53)) ([71d89b4](https://github.com/SupremeCommanderHedgehog/containerizer/commit/71d89b44bd3670c064ce375363bd65da2df1c329))
* **sandbox/collectors:** tcpaccept bcc-tools wrapper to JSONL ([#55](https://github.com/SupremeCommanderHedgehog/containerizer/issues/55)) ([4ee02af](https://github.com/SupremeCommanderHedgehog/containerizer/commit/4ee02afcfaf2c10cd28dccc168724089d840bf78))
* **sandbox/collectors:** tcpconnect bcc-tools wrapper to JSONL ([#54](https://github.com/SupremeCommanderHedgehog/containerizer/issues/54)) ([c3d2ceb](https://github.com/SupremeCommanderHedgehog/containerizer/commit/c3d2ceb66df3234f7afe19883ef97c31bf19d9ca))
* **sandbox:** bash trace-orchestrator skeleton with EOF-as-Enter finalize ([#49](https://github.com/SupremeCommanderHedgehog/containerizer/issues/49)) ([76c2ac6](https://github.com/SupremeCommanderHedgehog/containerizer/commit/76c2ac69f0090706536e20b558a8a23c52476486))
* **sandbox:** runner image Containerfile and sandbox/ scaffolding ([#48](https://github.com/SupremeCommanderHedgehog/containerizer/issues/48)) ([f280851](https://github.com/SupremeCommanderHedgehog/containerizer/commit/f28085147db7c04b2eba911b87c3d2bf7bbeac2c))
* **sandbox:** strace fallback when bcc/bpftrace collector fails to attach ([#59](https://github.com/SupremeCommanderHedgehog/containerizer/issues/59)) ([2f69a27](https://github.com/SupremeCommanderHedgehog/containerizer/commit/2f69a2779d4bca7270b6ac72b60b32d60cfe9c58))
* **sandbox:** wire trace-orchestrator to launch all six collectors ([#57](https://github.com/SupremeCommanderHedgehog/containerizer/issues/57)) ([1d67384](https://github.com/SupremeCommanderHedgehog/containerizer/commit/1d67384e1748f27448ebe268dd7382698a870f25))
* **trace:** containerizer trace subcommand with pre-flight and summary ([#62](https://github.com/SupremeCommanderHedgehog/containerizer/issues/62)) ([7adec2a](https://github.com/SupremeCommanderHedgehog/containerizer/commit/7adec2a7eaf48a7ce8585c6a4160bdda2055df02))
* **trace:** RunnerImage with hash-based tag and lazy podman build ([#60](https://github.com/SupremeCommanderHedgehog/containerizer/issues/60)) ([eda9c2e](https://github.com/SupremeCommanderHedgehog/containerizer/commit/eda9c2edf808fc0b2a549726f48f49d7b65326a7))
* **trace:** TraceRunner constructs podman-run argv and execs ([#61](https://github.com/SupremeCommanderHedgehog/containerizer/issues/61)) ([eab0aef](https://github.com/SupremeCommanderHedgehog/containerizer/commit/eab0aef2d0c0e183272486cb2866ffb4f1a9527e))


### Documentation

* add MANUAL.md for hands-on testing ([#21](https://github.com/SupremeCommanderHedgehog/containerizer/issues/21)) ([f0bce6f](https://github.com/SupremeCommanderHedgehog/containerizer/commit/f0bce6f98a82796347e0f9c7e67393bf28646dcd))

## [0.2.1](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.2.0...v0.2.1) (2026-06-06)


### Bug Fixes

* **probe:** distinguish riscv32 vs riscv64 in arch mapping ([#17](https://github.com/SupremeCommanderHedgehog/containerizer/issues/17)) ([3ae07ea](https://github.com/SupremeCommanderHedgehog/containerizer/commit/3ae07eaf5bc7bf1b022309ddedce393f8fa89b44)), closes [#8](https://github.com/SupremeCommanderHedgehog/containerizer/issues/8)


### Tests

* **probe:** cover non-ELF detect_kind paths ([#16](https://github.com/SupremeCommanderHedgehog/containerizer/issues/16)) ([182b746](https://github.com/SupremeCommanderHedgehog/containerizer/commit/182b746973254df81c44eafb09696a556ab73cf1)), closes [#7](https://github.com/SupremeCommanderHedgehog/containerizer/issues/7)


### Continuous Integration

* wire pytest-cov with 90% gate ([#19](https://github.com/SupremeCommanderHedgehog/containerizer/issues/19)) ([92442e8](https://github.com/SupremeCommanderHedgehog/containerizer/commit/92442e8eb68ad218a9a6b87116bf69ccf947e00f)), closes [#9](https://github.com/SupremeCommanderHedgehog/containerizer/issues/9)

## [0.2.0](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.1.0...v0.2.0) (2026-06-06)


### Features

* **probe:** make ProbeResult frozen for symmetry with sibling models ([#13](https://github.com/SupremeCommanderHedgehog/containerizer/issues/13)) ([2010970](https://github.com/SupremeCommanderHedgehog/containerizer/commit/20109704f3d82c5170a2cee4834e0522f65d729f)), closes [#4](https://github.com/SupremeCommanderHedgehog/containerizer/issues/4)


### Bug Fixes

* **probe:** route glibc 2.35 to ubuntu:22.04, not 24.04 ([#11](https://github.com/SupremeCommanderHedgehog/containerizer/issues/11)) ([f9d70c2](https://github.com/SupremeCommanderHedgehog/containerizer/commit/f9d70c2bf3c5f0c23b321eda0284a0bd3ed9fe9f)), closes [#3](https://github.com/SupremeCommanderHedgehog/containerizer/issues/3)


### Build System

* **deps:** pin pyelftools<0.40 ([#14](https://github.com/SupremeCommanderHedgehog/containerizer/issues/14)) ([968a645](https://github.com/SupremeCommanderHedgehog/containerizer/commit/968a6455b8132af76c94e4a6f47aa6982cdca07d)), closes [#5](https://github.com/SupremeCommanderHedgehog/containerizer/issues/5)


### Continuous Integration

* run lint and typecheck on the full Python matrix ([#15](https://github.com/SupremeCommanderHedgehog/containerizer/issues/15)) ([f4918d5](https://github.com/SupremeCommanderHedgehog/containerizer/commit/f4918d52a9b94428414957548f0689ed38fdc053)), closes [#6](https://github.com/SupremeCommanderHedgehog/containerizer/issues/6)

## 0.1.0 (2026-06-06)


### Features

* **probe:** add ELF probe and 'containerizer probe' command ([d242c50](https://github.com/SupremeCommanderHedgehog/containerizer/commit/d242c506a664dc78f90c5d18ebef2545c3e226ab))


### Documentation

* add implementation plan for repo bootstrap + ELF probe ([883a269](https://github.com/SupremeCommanderHedgehog/containerizer/commit/883a269cfe45a7d460973a88f7273ec8a494f1c2))
* add README, LICENSE, SECURITY.md, CODEOWNERS ([fac8d5b](https://github.com/SupremeCommanderHedgehog/containerizer/commit/fac8d5beb7df0128c452fa574387e97bffa12ead))
