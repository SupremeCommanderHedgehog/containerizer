# Changelog

## [0.7.0](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.6.0...v0.7.0) (2026-06-21)


### Features

* **trace,build:** multi-deb input + apt sources ([#103](https://github.com/SupremeCommanderHedgehog/containerizer/issues/103)) ([d9e01f6](https://github.com/SupremeCommanderHedgehog/containerizer/commit/d9e01f6b7dff316611f4399bcd09c6ea81d29ca2))

## [0.6.0](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.5.0...v0.6.0) (2026-06-21)


### Features

* **probe,trace:** Debian .deb installer support ([#100](https://github.com/SupremeCommanderHedgehog/containerizer/issues/100)) ([195c681](https://github.com/SupremeCommanderHedgehog/containerizer/commit/195c681cbf674fb75da9648c978ae34b18440f9c))

## [0.5.0](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.4.0...v0.5.0) (2026-06-11)


### Features

* **analyze:** parse strace fallback logs for bind/connect/accept ([#93](https://github.com/SupremeCommanderHedgehog/containerizer/issues/93)) ([6f9e29d](https://github.com/SupremeCommanderHedgehog/containerizer/commit/6f9e29d6dbcdd05389535a585b0170da8614d3d9))
* **runner:** boot systemd as PID 1 for trace runner ([#96](https://github.com/SupremeCommanderHedgehog/containerizer/issues/96)) ([46ad019](https://github.com/SupremeCommanderHedgehog/containerizer/commit/46ad01990cf4c71195b9282de05d7a94c9307bbc))


### Bug Fixes

* **runner:** force LF line endings on runner-image scripts ([#88](https://github.com/SupremeCommanderHedgehog/containerizer/issues/88)) ([2671098](https://github.com/SupremeCommanderHedgehog/containerizer/commit/2671098b293602f86d46c12657065fa03ae138fd))
* **trace,build:** allocate TTY for interactive installers + surface fallback gaps ([#91](https://github.com/SupremeCommanderHedgehog/containerizer/issues/91)) ([e9719eb](https://github.com/SupremeCommanderHedgehog/containerizer/commit/e9719eba38ed028a442757aca6e2ed074c6a456b))
* **trace:** example-app Y/N prompt under systemd-PID-1 runner ([#97](https://github.com/SupremeCommanderHedgehog/containerizer/issues/97)) ([8fea5e2](https://github.com/SupremeCommanderHedgehog/containerizer/commit/8fea5e2754f99d012584f06a6b5b56cfcb935b16))


### Documentation

* **issue-90:** spec + plan for systemd-as-PID-1 trace runner ([#94](https://github.com/SupremeCommanderHedgehog/containerizer/issues/94)) ([7bf2990](https://github.com/SupremeCommanderHedgehog/containerizer/commit/7bf2990085a10a8127a9227223ef9b05bfe21102))

## [0.4.0](https://github.com/SupremeCommanderHedgehog/containerizer/compare/v0.3.0...v0.4.0) (2026-06-09)


### Features

* **analyze:** M3 analyzer + policy derivation ([#80](https://github.com/SupremeCommanderHedgehog/containerizer/issues/80)) ([7cfd1fa](https://github.com/SupremeCommanderHedgehog/containerizer/commit/7cfd1fa4d5a2c34652d917997d1f0693f5a153e0))
* **build:** M6 build subcommand end-to-end orchestrator ([#86](https://github.com/SupremeCommanderHedgehog/containerizer/issues/86)) ([4ab3873](https://github.com/SupremeCommanderHedgehog/containerizer/commit/4ab3873b9ae38e15bfa027b30e7c1a174094ccb0))
* **generate:** M4 generators (Containerfile + Quadlet + seccomp + README) ([#82](https://github.com/SupremeCommanderHedgehog/containerizer/issues/82)) ([44901b4](https://github.com/SupremeCommanderHedgehog/containerizer/commit/44901b44ce801d5e173f76989c4e57ee55404e83))
* **verify:** M5 verify (diff-only) ([#84](https://github.com/SupremeCommanderHedgehog/containerizer/issues/84)) ([8410197](https://github.com/SupremeCommanderHedgehog/containerizer/commit/8410197de7ff50f2474af283eb675fa0dea4a5e6))


### Bug Fixes

* **sandbox/collectors:** drop stray BEGIN printf opener from .bt files ([#70](https://github.com/SupremeCommanderHedgehog/containerizer/issues/70)) ([78aecdd](https://github.com/SupremeCommanderHedgehog/containerizer/commit/78aecdd3b4b3715925e6fae450cbc8072592a4ad)), closes [#58](https://github.com/SupremeCommanderHedgehog/containerizer/issues/58)
* **sandbox/collectors:** key bind.bt proto map by (pid&lt;&lt;32 | fd) instead of tid ([#71](https://github.com/SupremeCommanderHedgehog/containerizer/issues/71)) ([664c594](https://github.com/SupremeCommanderHedgehog/containerizer/commit/664c594b18c39c0380b84790179711ef8ab8c919)), closes [#52](https://github.com/SupremeCommanderHedgehog/containerizer/issues/52)
* **sandbox:** kernel-headers in runner image + 15s grace for bcc compile ([#76](https://github.com/SupremeCommanderHedgehog/containerizer/issues/76)) ([87d05ee](https://github.com/SupremeCommanderHedgehog/containerizer/commit/87d05eeb932543919dbb0383011157cbd0500e21))
* **sandbox:** replace bcc tcpconnect/tcpaccept with bpftrace ([#77](https://github.com/SupremeCommanderHedgehog/containerizer/issues/77)) ([#78](https://github.com/SupremeCommanderHedgehog/containerizer/issues/78)) ([0d11f14](https://github.com/SupremeCommanderHedgehog/containerizer/commit/0d11f14203f82b2a39ddf844259e569bf0e4531b))
* **trace:** bind-mount kernel tracefs + headers + CI rootful podman ([#74](https://github.com/SupremeCommanderHedgehog/containerizer/issues/74)) ([716740e](https://github.com/SupremeCommanderHedgehog/containerizer/commit/716740e82cf49f0dc7c9a3e521adb549c0acde52))


### Documentation

* **m3:** analyzer + policy derivation spec + implementation plan ([#79](https://github.com/SupremeCommanderHedgehog/containerizer/issues/79)) ([122df45](https://github.com/SupremeCommanderHedgehog/containerizer/commit/122df451c84bf9df30e12a62a31838d306aacdf8))
* **m4:** spec + implementation plan for generators ([#81](https://github.com/SupremeCommanderHedgehog/containerizer/issues/81)) ([d1add90](https://github.com/SupremeCommanderHedgehog/containerizer/commit/d1add903bf801315090dda486a2c86c357bb867d))
* **m5:** spec + implementation plan for verify ([#83](https://github.com/SupremeCommanderHedgehog/containerizer/issues/83)) ([fff07d1](https://github.com/SupremeCommanderHedgehog/containerizer/commit/fff07d1fc19890b548fe2eabe41c27583a0a5559))
* **m6:** spec + implementation plan for build subcommand ([#85](https://github.com/SupremeCommanderHedgehog/containerizer/issues/85)) ([7f7dcc1](https://github.com/SupremeCommanderHedgehog/containerizer/commit/7f7dcc1e282af64a0b908c7ffb184e1768e31beb))
* **plan:** add M2 sandbox + trace implementation plan ([#46](https://github.com/SupremeCommanderHedgehog/containerizer/issues/46)) ([7ba3bd3](https://github.com/SupremeCommanderHedgehog/containerizer/commit/7ba3bd3209b0a1c2f3836c1c60dd6c710e275668))
* **spec:** add M2 sandbox + trace design spec ([#45](https://github.com/SupremeCommanderHedgehog/containerizer/issues/45)) ([d540fc4](https://github.com/SupremeCommanderHedgehog/containerizer/commit/d540fc4b0e46add0562ed430824a393f509a2be1))

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
