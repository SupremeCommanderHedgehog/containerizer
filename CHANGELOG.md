# Changelog

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
